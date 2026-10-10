from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.evidence_engine.application import (
    build_evidence_source,
    generate_evidence_course,
    to_generation_artifacts,
)
from app.modules.ai.evidence_engine.assessment_axes import derive_assessment_axes, materialize_assessment
from app.modules.ai.evidence_engine.engine import admit_document_facts
from app.modules.ai.evidence_engine.models import AuthoredAssessment, CourseIntent, LessonDraft, SourceFact
from app.modules.ai.ingestion import DocumentChunker
from app.modules.ai.llm_client import AllProvidersFailedError, ValidatedLLMResult


def orbita_corpus() -> DirectSourceCorpus:
    source = (Path(__file__).parents[1] / "fixtures/ai/orbita_warehouse_policy.txt").read_bytes()
    assert hashlib.sha256(source).hexdigest() == "3eda7adafa730ee29460a1e633dbd8f94673b1611b2180aebfe6a169e482c8d6"
    text = source.decode("utf-8")
    revision = "document:3eda7adafa730ee29460a1e633dbd8f94673b1611b2180aebfe6a169e482c8d6"
    chunks = tuple(DirectSourceChunk(
        chunk_id=f"direct:orbita:{index}", doc_id="orbita", doc_name="orbita.txt",
        title="Приёмка склада Орбита", headings=(), text=str(chunk["text"]),
        source_revision=revision, chunk_index=index,
    ) for index, chunk in enumerate(DocumentChunker().chunk_markdown(text, "orbita", "orbita.txt")))
    return DirectSourceCorpus(
        tenant_id="synthetic-orbita", documents=(DirectSourceDocument(
            doc_id="orbita", title="Приёмка склада Орбита", filename="orbita.txt",
            category="training_material", source_revision=revision, chunks=chunks,
        ),), total_chars=len(text), total_chunks=len(chunks),
    )


def test_original_orbita_plain_headings_are_not_concatenated_into_operational_facts() -> None:
    bundle = build_evidence_source(orbita_corpus())
    values = "\n".join(fact.value for fact in bundle.all_facts)
    assert "Приёмка поставки Сотрудник" not in values
    assert "Завершение После сверки" not in values
    assert "Самостоятельно исправлять количество в накладной нельзя." in values
    assert "Это срок оформления акта, а не срок устранения недостачи." in values
    assert "отсутствующие сведения не выдумывает." in values
    assert "при наличии 10 запрещено." in values


def text_corpus(text: str) -> DirectSourceCorpus:
    corpus = orbita_corpus()
    document = corpus.documents[0]
    chunk = replace(document.chunks[0], text=text)
    return replace(corpus, documents=(replace(document, chunks=(chunk,)),), total_chars=len(text), total_chunks=1)


def test_authoring_instructions_are_retained_for_trace_but_not_admitted_as_training_facts() -> None:
    bundle = build_evidence_source(orbita_corpus())
    primary, supporting, _ = admit_document_facts(bundle.document)
    values = "\n".join(fact.value for fact in primary + supporting)
    assert "Урок должен учить" not in values
    assert "документ нужен только для проверки LMS" not in values
    assert "Версия 1" not in values
    assert "Учебный регламент вымышленного" not in values
    assert "номер акта и зону изоляции, если они есть" in values
    assert "при наличии 10 запрещено." in values
    excluded = [fact for fact in bundle.all_facts if fact.uncertainty == "source_authoring_metadata"]
    assert any("Урок должен учить" in fact.value for fact in excluded)
    assert any("документ нужен только для проверки LMS" in fact.value for fact in excluded)
    assert all("source_revision=document:" in fact.source_locator for fact in excluded)


@pytest.mark.parametrize("action", [
    "Проверьте накладную", "Сотрудник сверяет коробки", "Check the invoice",
    "Если коробка повреждена, сообщите руководителю", "1. Проверить накладную",
    "Остановитесь", "Проверьте", "Check",
])
def test_short_action_lines_are_not_mistaken_for_nominal_headings(action: str) -> None:
    text = f"{action}\nСверку фиксируют в журнале.\n\nИзоляция\nПовреждённую коробку изолируют.\n\nЗавершение\nНомер акта записывают в журнале."
    bundle = build_evidence_source(text_corpus(text))
    assert action in "\n".join(fact.value for fact in bundle.all_facts)


def test_employee_obligation_and_training_policy_are_not_authoring_metadata() -> None:
    text = (
        "Обучение\nСотрудник должен пройти урок до работы на складе.\n\n"
        "Проверка\nМетодист проверяет документ и учит сотрудника оформлять акт."
    )
    bundle = build_evidence_source(text_corpus(text))
    primary, supporting, _ = admit_document_facts(bundle.document)
    assert len(primary + supporting) == 2
    assert all(fact.confidence == 1.0 for fact in primary + supporting)


@pytest.mark.parametrize("rule", [
    "Курс должен содержать 32 часа практики.",
    "Вопрос должен содержать номер обращения клиента.",
    "The course must contain 32 hours of practice.",
])
def test_normative_training_and_customer_question_requirements_remain_teachable(rule: str) -> None:
    bundle = build_evidence_source(text_corpus(rule))
    primary, supporting, _ = admit_document_facts(bundle.document)
    assert rule in [fact.value for fact in primary + supporting]


def test_one_word_noun_headings_ending_in_t_are_not_infinitive_actions() -> None:
    bundle = build_evidence_source(text_corpus(
        "Безопасность\nСотрудник обязан надеть защитные очки.\n\n"
        "Ответственность\nРуководитель смены принимает решение о допуске."
    ))
    assert [section.title for section in bundle.document.sections] == ["Безопасность", "Ответственность"]
    assert bundle.all_facts[0].value == "Сотрудник обязан надеть защитные очки."


@pytest.mark.parametrize("separator", ["\r\n\r\n", "\n\n   \n"])
def test_plain_headings_allow_windows_line_endings_and_whitespace_only_lines(separator: str) -> None:
    text = f"Изоляция\nПовреждённую коробку изолируют.{separator}Завершение\nНомер акта записывают."
    if separator.startswith("\r"):
        text = text.replace("Изоляция\n", "Изоляция\r\n").replace("Завершение\n", "Завершение\r\n")
    bundle = build_evidence_source(text_corpus(text))
    assert [section.title for section in bundle.document.sections] == ["Изоляция", "Завершение"]
    assert bundle.all_facts[0].value == "Повреждённую коробку изолируют."


def test_retained_three_source_supported_keys_receive_clean_server_explanations(tmp_path: Path) -> None:
    fixtures = Path(__file__).parents[1] / "fixtures/ai"
    cases = json.loads((fixtures / "orbita_retained_assessment.json").read_text(encoding="utf-8"))
    source = (fixtures / "orbita_warehouse_policy.txt").read_bytes()
    assert hashlib.sha256(source).hexdigest() == cases["source_sha256"]
    source_text = source.decode("utf-8")
    corrected = []
    for index, case in enumerate(cases["cases"]):
        claim = case["source_supported_answer"]
        assert claim in source_text
        fact = SourceFact(f"retained-{index}", "QA: источник корректировки", case["attribute"], claim, "doc_id=orbita;part=1")
        lesson = LessonDraft("retained", "Приёмка", "Правила приёмки", "Применять правила", "", (fact.fact_id,), (), 1)
        axis = derive_assessment_axes(lesson, [fact], block_id="retained")[0]
        question = materialize_assessment(axis, AuthoredAssessment(
            axis_id=axis.axis_id, prompt=case["prompt"], distractors=tuple(case["distractors"]),
        ))
        assert question is not None
        assert question.correct_answer == claim
        assert set(question.options) == {claim, *case["distractors"]}
        assert claim in question.explanation
        assert "источник" not in question.explanation.casefold()
        assert "QA:" not in question.explanation
        assert "ответ должен" not in question.explanation.casefold()
        if index == 2:
            assert question.explanation.startswith("Запомните: ")
        corrected.append({"prompt": question.prompt, "explanation": question.explanation, "correct_answer": claim})
    (tmp_path / "explanations.json").write_text(json.dumps({
        "origin": "OFFLINE_SERVER_MATERIALIZATION_NOT_NEW_GENERATION_OR_PERSISTED_COURSE",
        "questions": corrected,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def test_real_dev_prohibition_question_cannot_ask_for_a_positive_journal_entry() -> None:
    # Replay the rejected real DEV question at the production assessment seam.
    # The source specifies a prohibition, not a fully defined journal-entry format.
    claim = "Вносить фиктивные сведения о принятии всех 12 коробок при наличии 10 запрещено."
    assert claim in (Path(__file__).parents[1] / "fixtures/ai/orbita_warehouse_policy.txt").read_text(encoding="utf-8")
    fact = SourceFact("dev-ban", "Завершение", "запрет", claim, "doc_id=orbita;part=1")
    lesson = LessonDraft("dev-final", "Приёмка", "Завершение приёмки", "Соблюдать правила", "", (fact.fact_id,), (), 1)
    axis = derive_assessment_axes(lesson, [fact], block_id="dev-final")[0]
    question = materialize_assessment(axis, AuthoredAssessment(
        axis_id=axis.axis_id,
        prompt="Сотрудник сверил поставку и обнаружил 10 коробок вместо 12. Какая запись в журнале приёмки соответствует правилам?",
        distractors=(
            "Отметить в журнале принятие 12 коробок, чтобы скрыть недостачу до конца смены.",
            "Внести запись о принятии 12 коробок, так как недостачу можно уточнить при следующей поставке.",
            "Отметить в журнале только 10 фактически принятых коробок, а недостающие 2 коробки записать как принятые после устранения недостачи.",
        ),
    ))
    assert question is not None
    assert question.prompt == "Допустимо ли вносить фиктивные сведения о принятии всех 12 коробок при наличии 10?"
    assert question.correct_answer == claim
    assert question.kind == "true_false"
    assert question.options == (claim, "Вносить фиктивные сведения о принятии всех 12 коробок при наличии 10 разрешено.")
    assert question.explanation == f"Как действовать: «{claim}»."


@pytest.mark.parametrize("claim", [
    "Вносить сведения в журнал не запрещено.",
    "Вносить сведения разрешено, но выдумывать их запрещено.",
    "Вносить сведения можно и выдумывать их запрещено.",
    "Вносить слово «запрещено» в журнал запрещено.",
])
def test_non_categorical_and_quoted_prohibitions_are_not_blindly_inverted(claim: str) -> None:
    fact = SourceFact("mixed", "Журнал", "положение", claim, "doc_id=synthetic;part=1")
    lesson = LessonDraft("mixed", "Журнал", "Журнал", "Понимать правило", "", (fact.fact_id,), (), 1)
    axis = derive_assessment_axes(lesson, [fact], block_id="mixed")[0]
    question = materialize_assessment(axis, AuthoredAssessment(
        axis_id=axis.axis_id, prompt="Какое правило действует для журнала?",
        distractors=("Журнал следует уничтожить.", "Сведения нужно передать покупателю."),
    ))
    assert question is not None
    assert question.kind == "single_choice"
    assert question.correct_answer == claim


class UnavailableProvider:
    async def ainvoke_validated(self, *_args, **_kwargs):
        raise AllProvidersFailedError("offline provider unavailable")

    async def embed_documents_with_provenance(self, *_args, **_kwargs):
        raise AllProvidersFailedError("offline embedding unavailable")


class LeakingWriter(UnavailableProvider):
    """Adversarial transport fixture, never an assessment or semantic oracle."""

    async def ainvoke_validated(self, messages, parser, **_kwargs):
        request = json.loads(messages[-1]["content"])
        if request.get("task", "").startswith("assessment_"):
            raise AllProvidersFailedError("no synthetic semantic approval")
        payload = {
            "title": request["lesson_title"], "objective": request["objective"],
            "blocks": [{
                "heading": fact["subject"],
                "text": f"{fact['subject']} {fact['value']} Урок должен учить порядку действий, а не пересказу заголовков.",
                "fact_ids": [fact["fact_id"]],
            } for fact in request["facts"]],
            "questions": [],
        }
        return ValidatedLLMResult(
            provider="offline-adversarial-writer", model_id="fixture-not-a-model",
            value=parser(json.dumps(payload, ensure_ascii=False)), attempt_count=1, failure_reasons=(),
        )


class UnsupportedWriter(LeakingWriter):
    async def ainvoke_validated(self, messages, parser, **kwargs):
        def omitted_prose(value: str):
            payload = json.loads(value)
            for block in payload.get("blocks", []):
                block["text"] = "Совсем другой документ."
            return parser(json.dumps(payload, ensure_ascii=False))
        return await super().ainvoke_validated(messages, omitted_prose, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("writer", [UnavailableProvider(), LeakingWriter(), UnsupportedWriter()])
async def test_active_application_and_fallback_do_not_restore_source_presentation_defects(writer, tmp_path: Path) -> None:
    generated = await generate_evidence_course(
        orbita_corpus(), intent=CourseIntent(purpose="Обучить сотрудника приёмки"),
        generation_client=writer, embedding_client=UnavailableProvider(),
    )
    artifacts = to_generation_artifacts(generated)
    content = "\n".join(lesson.content for module in artifacts.content.modules for lesson in module.lessons)
    (tmp_path / "candidate.json").write_text(json.dumps({
        "origin": "OFFLINE_APPLICATION_REPLAY_NOT_FRESH_MODEL_GENERATION",
        "writer": type(writer).__name__,
        "source_sha256": "3eda7adafa730ee29460a1e633dbd8f94673b1611b2180aebfe6a169e482c8d6",
        "content": content,
        "publishable": generated.result.publishability.publishable,
        "publishability_reasons": generated.result.publishability.reasons,
        "admitted_facts": [fact.value for fact in generated.result.evidence_result.admitted_facts],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    assert "Урок должен учить" not in content
    assert "документ нужен только для проверки LMS" not in content
    assert "Приёмка поставки Сотрудник" not in content
    assert "Завершение После сверки" not in content
    assert "### запрет" not in content
    for heading in ("Приёмка поставки", "Повреждённая упаковка", "Срок проверки", "Завершение"):
        assert f"### {heading}" in content
    # Source-owned oracle: all operational clusters survive projection. No fake
    # semantic reviewer is allowed to turn unavailable assessment into a PASS.
    for quote in [
        "Принимать груз без накладной нельзя.",
        "накладная ОР-17 содержит 12 коробок, а фактически прибыло 10.",
        "Сотрудник фиксирует недостачу двух коробок в акте и передаёт акт руководителю смены.",
        "Самостоятельно исправлять количество в накладной нельзя.",
        "делают фотографию повреждения и сообщают руководителю смены.",
        "Не допускается смешивать такую коробку с принятыми товарами.",
        "Решение о дальнейшем использовании принимает руководитель смены, а не сотрудник приёмки.",
        "Это срок оформления акта, а не срок устранения недостачи.",
        "отсутствующие сведения не выдумывает.",
        "номер акта и зону изоляции, если они есть.",
        "при наличии 10 запрещено.",
    ]:
        assert quote in content
    assert generated.result.publishability.publishable is False
    assert "assessment_no_valid_questions" in generated.result.publishability.reasons
