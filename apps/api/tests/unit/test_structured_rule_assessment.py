import json
from types import SimpleNamespace

import pytest

from app.modules.ai.direct_source import (
    DirectSourceChunk,
    DirectSourceCorpus,
    DirectSourceDocument,
)
from app.modules.ai.evidence_engine.application import build_evidence_source
from app.modules.ai.evidence_engine.assessment_axes import derive_assessment_axes
from app.modules.ai.evidence_engine.engine import admit_document_facts
from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact
from app.modules.ai.evidence_engine.semantic_assessment import generate_block_assessment
from app.modules.ai.ingestion import DocumentChunker

WAREHOUSE_RULES = """При пожаре сотрудник склада обязан выполнить действия:
1. Остановить конвейер.
2. Отключить питание оборудования.
3. Сообщить руководителю смены.
4. Вызвать пожарную службу.
5. Закрыть противопожарные двери.
6. Организовать эвакуацию сотрудников.
7. Покинуть опасную зону.
8. Дождаться разрешения ответственного лица."""

WAREHOUSE_CLAUSES = (
    "Остановить конвейер",
    "Отключить питание оборудования",
    "Сообщить руководителю смены",
    "Вызвать пожарную службу",
    "Закрыть противопожарные двери",
    "Организовать эвакуацию сотрудников",
    "Покинуть опасную зону",
    "Дождаться разрешения ответственного лица",
)


def _fixture(value: str = WAREHOUSE_RULES) -> tuple[LessonDraft, SourceFact]:
    fact = SourceFact(
        "warehouse-fire-rules",
        "Пожарная безопасность склада",
        "правило",
        value,
        "doc_id=warehouse-safety;source_revision=synthetic-v1;section=fire;part=1",
    )
    lesson = LessonDraft(
        "warehouse-fire",
        "Безопасность",
        "Действия при пожаре",
        "Применять порядок пожарной безопасности",
        value,
        (fact.fact_id,),
        (),
        4,
    )
    return lesson, fact


def _lesson_for_fact(fact: SourceFact) -> LessonDraft:
    return LessonDraft(
        "admitted-fire-list",
        "Безопасность",
        "Действия при пожаре",
        "Выполнить требования пожарной безопасности",
        fact.value,
        (fact.fact_id,),
        (),
        4,
    )


def _roundtrip_fact(source_text: str, *, needle: str = "электроприборы") -> SourceFact:
    rows = DocumentChunker(chunk_size=2000, chunk_overlap=100).chunk_markdown(
        f"# Пожарная безопасность\n\n{source_text}",
        "synthetic-fire-rules",
        "fire-rules.docx",
    )
    chunks = tuple(
        DirectSourceChunk(
            chunk_id=f"synthetic-fire-rules:{index}",
            doc_id="synthetic-fire-rules",
            doc_name="fire-rules.docx",
            title="Пожарная безопасность",
            headings=tuple(json.loads(row["metadata"]["headings"])),
            text=row["text"],
            source_revision="document:synthetic-fire-rules-v1",
            chunk_index=index,
        )
        for index, row in enumerate(rows)
    )
    corpus = DirectSourceCorpus(
        tenant_id="synthetic-only",
        documents=(DirectSourceDocument(
            doc_id="synthetic-fire-rules",
            title="Пожарная безопасность",
            filename="fire-rules.docx",
            category="training_material",
            source_revision="document:synthetic-fire-rules-v1",
            chunks=chunks,
        ),),
        total_chars=len(source_text),
        total_chunks=len(chunks),
    )
    primary, _supporting, _duplicates = admit_document_facts(
        build_evidence_source(corpus).document
    )
    return next(fact for fact in primary if needle in fact.value)


def test_explicit_operational_list_derives_one_source_owned_axis_per_clause() -> None:
    lesson, fact = _fixture()

    axes = derive_assessment_axes(lesson, [fact], block_id="warehouse-fire-block")

    assert tuple(axis.correct_value for axis in axes) == WAREHOUSE_CLAUSES
    assert len({axis.axis_id for axis in axes}) == len(WAREHOUSE_CLAUSES)
    assert {axis.primary_fact_id for axis in axes} == {fact.fact_id}
    assert {axis.evidence_fact_ids for axis in axes} == {(fact.fact_id,)}
    assert len({axis.required_prompt for axis in axes}) == len(WAREHOUSE_CLAUSES)
    assert all(
        "При пожаре сотрудник склада обязан выполнить действия" in axis.required_prompt
        for axis in axes
    )
    assert all("При пожаре сотрудник склада" not in axis.correct_value for axis in axes)

    ordinary = (
        "При пожаре сотрудник склада обязан остановить конвейер. "
        "Затем сотрудник отключает питание оборудования. "
        "После этого сотрудник сообщает руководителю смены."
    )
    ordinary_lesson, ordinary_fact = _fixture(ordinary)
    ordinary_axes = derive_assessment_axes(
        ordinary_lesson,
        [ordinary_fact],
        block_id="ordinary-prose-block",
    )
    assert len(ordinary_axes) == 1


def test_duty_with_embedded_prohibition_keeps_neutral_whole_rule_question() -> None:
    value = (
        "Работникам склада следует: "
        "1) содержать в исправном состоянии системы пожаротушения, "
        "не допускать их использования не по назначению; "
        "2) сообщать руководителю о неисправностях."
    )
    lesson, fact = _fixture(value)
    axes = derive_assessment_axes(lesson, [fact], block_id="mixed-duty-ban")
    mixed = next(axis for axis in axes if "содержать" in axis.correct_value)
    assert mixed.correct_value == (
        "содержать в исправном состоянии системы пожаротушения, "
        "не допускать их использования не по назначению"
    )
    assert "запрещено" not in mixed.required_prompt
    assert "Какое полное правило" in mixed.required_prompt
    assert "Работникам склада следует" in mixed.required_prompt


def test_explicit_prohibition_list_keeps_prohibition_question() -> None:
    lesson, fact = _fixture(
        "Работникам склада запрещается: "
        "1) использовать поврежденные кабели; "
        "2) закрывать проходы к выходам."
    )
    axes = derive_assessment_axes(lesson, [fact], block_id="explicit-ban")
    assert len(axes) == 2
    assert all(axis.correct_value == "запрещается" for axis in axes)
    assert all("Допустимо ли" in axis.required_prompt for axis in axes)


@pytest.mark.parametrize("duty", [
    "не допускать использования оборудования не по назначению",
    "запрещать доступ посторонних к опасному оборудованию",
])
def test_active_preventive_duty_is_not_a_prohibitive_modal(duty: str) -> None:
    lesson, fact = _fixture(
        f"Работник склада обязан: 1) {duty}; "
        "2) сообщать руководителю о неисправностях."
    )
    axes = derive_assessment_axes(lesson, [fact], block_id="active-preventive-duty")
    item = next(axis for axis in axes if axis.correct_value == duty)
    assert "Какое полное правило" in item.required_prompt
    assert "запрещено требованием" not in item.required_prompt


def test_embedded_preventive_preamble_does_not_invert_positive_list_actions() -> None:
    lesson, fact = _fixture(
        "Работник, обязанный не допускать посторонних, выполняет действия: "
        "1) проверить ограждение; 2) сообщить руководителю."
    )
    axes = derive_assessment_axes(lesson, [fact], block_id="preventive-preamble")
    assert len(axes) == 2
    assert all("Какое полное правило" in axis.required_prompt for axis in axes)
    assert all("запрещено требованием" not in axis.required_prompt for axis in axes)


def test_bullet_list_skips_heading_and_exception_without_relaxing_source_truth() -> None:
    value = """При тревоге оператор обязан выполнить действия:
- Порядок эвакуации:
- Проверить свободный проход к выходу.
- Кроме случаев учебной тревоги покинуть рабочее место.
- Остановить погрузочную линию."""
    lesson, fact = _fixture(value)

    axes = derive_assessment_axes(lesson, [fact], block_id="bounded-bullets")

    assert tuple(axis.correct_value for axis in axes) == (
        "Проверить свободный проход к выходу",
        "Остановить погрузочную линию",
    )
    assert all(axis.correct_value in value for axis in axes)
    assert all("Порядок эвакуации" not in axis.correct_value for axis in axes)
    assert all("Кроме случаев" not in axis.correct_value for axis in axes)


@pytest.mark.parametrize(
    ("source_text", "admitted_value"),
    [
        (
            "После работы сотрудник обязан:\n"
            "- отключить электроприборы;\n"
            "- проверить сигнализацию;\n"
            "- закрыть окна.",
            "После работы сотрудник обязан: - отключить электроприборы; "
            "- проверить сигнализацию; - закрыть окна.",
        ),
        (
            "После работы сотрудник обязан:\n"
            "- 1) отключить электроприборы;\n"
            "- 2) проверить сигнализацию;\n"
            "- 3) закрыть окна.",
            "После работы сотрудник обязан: - 1) отключить электроприборы; "
            "- 2) проверить сигнализацию; - 3) закрыть окна.",
        ),
    ],
)
def test_admitted_inline_lists_keep_distinct_action_axes_without_ordinal_prompts(
    source_text: str,
    admitted_value: str,
) -> None:
    fact = _roundtrip_fact(source_text)
    assert fact.value == admitted_value
    lesson = LessonDraft(
        "admitted-fire-list",
        "Безопасность",
        "Завершение работы",
        "Выполнить действия после работы",
        fact.value,
        (fact.fact_id,),
        (),
        3,
    )

    axes = derive_assessment_axes(lesson, [fact], block_id="admitted-inline-list")

    assert tuple(axis.correct_value for axis in axes) == (
        "отключить электроприборы",
        "проверить сигнализацию",
        "закрыть окна",
    )
    assert all("После работы сотрудник обязан" in axis.required_prompt for axis in axes)
    assert all("пункт" not in axis.required_prompt.casefold() for axis in axes)
    assert "электроприборы" in axes[0].required_prompt
    assert "сигнализацию" in axes[1].required_prompt
    assert "окна" in axes[2].required_prompt


def test_admitted_conditional_list_keeps_each_condition_and_action_target() -> None:
    source_text = (
        "При аварии оператор обязан:\n"
        "- Если обнаружен дым, остановить насос;\n"
        "- Если слышен сигнал, отключить питание;\n"
        "- Если перекрыт выход, сообщить руководителю."
    )
    fact = _roundtrip_fact(source_text, needle="остановить насос")
    assert fact.value == (
        "При аварии оператор обязан: - Если обнаружен дым, остановить насос; "
        "- Если слышен сигнал, отключить питание; "
        "- Если перекрыт выход, сообщить руководителю."
    )
    lesson = _lesson_for_fact(fact)

    axes = derive_assessment_axes(lesson, [fact], block_id="conditional-list")

    assert tuple(axis.correct_value for axis in axes) == (
        "Если обнаружен дым, остановить насос",
        "Если слышен сигнал, отключить питание",
        "Если перекрыт выход, сообщить руководителю",
    )
    assert all(axis.correct_value in fact.value for axis in axes)
    assert "дым" in axes[0].required_prompt and "насос" in axes[0].required_prompt
    assert "сигнал" in axes[1].required_prompt and "питание" in axes[1].required_prompt
    assert "выход" in axes[2].required_prompt and "руководителю" in axes[2].required_prompt
    assert all("пункт" not in axis.required_prompt.casefold() for axis in axes)


def test_admitted_clause_local_prohibitions_get_distinct_prohibition_prompts() -> None:
    source_text = (
        "При пожаре сотрудник соблюдает правила:\n"
        "- Запрещено использовать лифт;\n"
        "- Не допускается продолжать работу;\n"
        "- Запрещено блокировать выход."
    )
    fact = _roundtrip_fact(source_text, needle="использовать лифт")
    lesson = _lesson_for_fact(fact)

    axes = derive_assessment_axes(lesson, [fact], block_id="clause-prohibitions")

    assert tuple(axis.correct_value for axis in axes) == (
        "Запрещено использовать лифт",
        "Не допускается продолжать работу",
        "Запрещено блокировать выход",
    )
    assert "лифт" in axes[0].required_prompt
    assert "работу" in axes[1].required_prompt
    assert "выход" in axes[2].required_prompt
    assert all("запрещено" in axis.required_prompt for axis in axes)
    assert all("пункт" not in axis.required_prompt.casefold() for axis in axes)


def test_actionable_exception_is_kept_but_pure_exception_fragment_is_not_an_axis() -> None:
    source_text = (
        "При тревоге сотрудник обязан:\n"
        "- Покинуть зону, кроме случаев учебной тревоги;\n"
        "- Сообщить руководителю;\n"
        "- Остановить оборудование;\n"
        "- Исключение: при учебной тревоге действует план наблюдения."
    )
    fact = _roundtrip_fact(source_text, needle="Покинуть зону")
    lesson = _lesson_for_fact(fact)

    axes = derive_assessment_axes(lesson, [fact], block_id="action-exception")

    assert tuple(axis.correct_value for axis in axes) == (
        "Покинуть зону, кроме случаев учебной тревоги",
        "Сообщить руководителю",
        "Остановить оборудование",
    )
    assert "зону" in axes[0].required_prompt
    assert "кроме случаев учебной тревоги" in axes[0].required_prompt
    assert all("Исключение:" not in axis.correct_value for axis in axes)
    assert all(axis.correct_value in fact.value for axis in axes)


def test_admitted_mixed_inline_markers_do_not_merge_the_final_action() -> None:
    source_text = (
        "После работы сотрудник обязан: - 1) отключить электроприборы; "
        "- 2) проверить сигнализацию; 3) закрыть окна."
    )
    fact = _roundtrip_fact(source_text)
    lesson = _lesson_for_fact(fact)

    axes = derive_assessment_axes(lesson, [fact], block_id="mixed-inline-markers")

    assert tuple(axis.correct_value for axis in axes) == (
        "отключить электроприборы",
        "проверить сигнализацию",
        "закрыть окна",
    )
    assert all("пункт" not in axis.required_prompt.casefold() for axis in axes)


@pytest.mark.parametrize(
    "value",
    [
        "- Остановить насос; - Отключить питание; - Сообщить руководителю.",
        (
            f"{'Очень длинный неподтвержденный контекст ' * 8}: "
            "- Остановить насос; - Отключить питание; - Сообщить руководителю."
        ),
    ],
)
def test_operational_list_without_safe_preamble_is_not_silently_one_axis(
    value: str,
) -> None:
    lesson, fact = _fixture(value)

    assert derive_assessment_axes(lesson, [fact], block_id="unsafe-list-context") == ()


class _UnexpectedAssessmentClient:
    async def ainvoke_validated(self, *_args, **_kwargs):
        raise AssertionError("unsupported structured evidence must not reach a provider")


@pytest.mark.asyncio
async def test_unsupported_structured_context_remains_explicitly_unassessed() -> None:
    value = (
        f"{'Очень длинный неподтвержденный контекст ' * 8}: "
        "- Остановить насос; - Отключить питание; - Сообщить руководителю."
    )
    lesson, fact = _fixture(value)

    result = await generate_block_assessment(
        [lesson],
        {fact.fact_id: fact},
        _UnexpectedAssessmentClient(),
    )

    assert result.questions == ()
    assert result.audit["coverage"]["requires_review"] is True
    assert result.audit["coverage"]["audit_incomplete"] is True
    assert result.audit["unassessed_lesson_ids"] == [lesson.lesson_id]
    assert result.audit["terminal_status"] == "review_required"


@pytest.mark.parametrize(
    "value",
    [
        "Температурный диапазон: - 10 градусов; - 20 градусов; - 30 градусов.",
        (
            "Сотрудник применяет риск-ориентированный подход; затем проверяет документ; "
            "затем сообщает результат руководителю."
        ),
    ],
)
def test_non_list_hyphens_numbers_and_plain_semicolon_prose_stay_single_axis(
    value: str,
) -> None:
    lesson, fact = _fixture(value)
    assert len(derive_assessment_axes(lesson, [fact], block_id="not-a-list")) == 1


class _StructuredRuleClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.rejected_axis_id = ""
        self.repair_seen = False

    async def ainvoke_validated(self, messages, parser, **_kwargs):
        request = json.loads(messages[-1]["content"])
        self.requests.append(request)
        task = request["task"]
        if task == "assessment_generate":
            axes = request["axes"]
            if len(axes) > 1 and not self.rejected_axis_id:
                self.rejected_axis_id = axes[1]["axis_id"]
            payload = {"questions": [
                {
                    "axis_id": axis["axis_id"],
                    "prompt": axis["required_prompt"],
                    "distractors": [
                        f"Пропустить действие {index}.",
                        f"Отложить действие {index}.",
                    ],
                }
                for index, axis in enumerate(axes, start=1)
            ]}
        elif task == "assessment_repair":
            self.repair_seen = True
            axis = request["axes"][0]
            payload = {"questions": [{
                "axis_id": axis["axis_id"],
                "prompt": axis["required_prompt"],
                "distractors": [
                    "Продолжить работу без уведомления.",
                    "Вернуться к обычной работе немедленно.",
                ],
            }]}
        elif task == "assessment_review":
            payload = {"reviews": [
                {
                    "question_id": question["question_id"],
                    "question_supported": not (
                        not self.repair_seen
                        and question["question_id"]
                        == f"semantic-{self.rejected_axis_id.removeprefix('axis-')}"
                    ),
                    "educational": True,
                    "explanation_supported": True,
                    "options_distinct": True,
                    "options": [
                        {
                            "index": index,
                            "answers_question": True,
                            "correct": index == 0,
                            "plausible_error": index > 0,
                            "contradicted_by_source": index > 0,
                            "same_practical_task": True,
                        }
                        for index in range(len(question["options"]))
                    ],
                }
                for question in request["questions"]
            ]}
        else:
            fact = request["facts"][0]
            payload = {
                "rules": [{
                    "fact_id": fact["fact_id"],
                    "quote": fact["value"],
                    "kind": "required",
                }],
                "reviews": [
                    {
                        "question_id": question["question_id"],
                        "reason": "Synthetic source contract.",
                        "distinct_errors": True,
                        "options": [
                            {
                                "index": index,
                                "relation": "entailed" if index == 0 else "contradicted",
                                "invented_constraint": False,
                                "realistic_error": True,
                            }
                            for index in range(len(question["options"]))
                        ],
                    }
                    for question in request["questions"]
                ],
            }
        return SimpleNamespace(
            value=parser(json.dumps(payload, ensure_ascii=False)),
            attempt_count=1,
        )


class _PartialStructuredRuleClient(_StructuredRuleClient):
    async def ainvoke_validated(self, messages, parser, **kwargs):
        request = json.loads(messages[-1]["content"])
        if request["task"] == "assessment_generate" and len(request["axes"]) > 1:
            self.requests.append(request)
            axis = request["axes"][0]
            payload = {"questions": [{
                "axis_id": axis["axis_id"],
                "prompt": axis["required_prompt"],
                "distractors": ["Пропустить действие.", "Отложить действие."],
            }]}
            return SimpleNamespace(
                value=parser(json.dumps(payload, ensure_ascii=False)),
                attempt_count=1,
            )
        return await super().ainvoke_validated(messages, parser, **kwargs)


@pytest.mark.asyncio
async def test_rejected_second_clause_repairs_its_exact_axis_not_the_parent_first_axis() -> None:
    lesson, fact = _fixture()
    client = _StructuredRuleClient()

    result = await generate_block_assessment([lesson], {fact.fact_id: fact}, client)

    author_request = next(
        request for request in client.requests if request["task"] == "assessment_generate"
    )
    expected_axis = author_request["axes"][1]
    repair_request = next(
        request for request in client.requests if request["task"] == "assessment_repair"
    )
    assert repair_request["axes"] == [expected_axis]
    assert repair_request["rejected"][0]["question_id"] == (
        f"semantic-{expected_axis['axis_id'].removeprefix('axis-')}"
    )
    assert any(
        question.correct_answer == WAREHOUSE_CLAUSES[1]
        for question in result.questions
    )


@pytest.mark.asyncio
async def test_partial_author_response_recovers_each_missing_clause_axis() -> None:
    lesson, fact = _fixture()
    client = _PartialStructuredRuleClient()
    client.repair_seen = True

    result = await generate_block_assessment([lesson], {fact.fact_id: fact}, client)

    author_requests = [
        request for request in client.requests if request["task"] == "assessment_generate"
    ]
    assert [len(request["axes"]) for request in author_requests] == [8, *([1] * 7)]
    requested_axis_ids = [
        axis["axis_id"] for axis in author_requests[0]["axes"]
    ]
    recovered_axis_ids = [
        request["axes"][0]["axis_id"] for request in author_requests[1:]
    ]
    assert recovered_axis_ids == requested_axis_ids[1:]
    assert {question.correct_answer for question in result.questions} == set(
        WAREHOUSE_CLAUSES
    )


@pytest.mark.asyncio
async def test_unselected_operational_siblings_remain_explicit_critical_omissions(monkeypatch) -> None:
    # Exercise ceiling exhaustion with a small fixture, not a three-question
    # product policy. The production budget follows independent source targets.
    monkeypatch.setattr(
        "app.modules.ai.evidence_engine.semantic_assessment._MAX_ASSESSMENT_TARGETS_PER_LESSON", 3,
    )
    lesson, fact = _fixture()
    client = _StructuredRuleClient()
    client.repair_seen = True

    result = await generate_block_assessment([lesson], {fact.fact_id: fact}, client)

    author_request = next(
        request for request in client.requests if request["task"] == "assessment_generate"
    )
    requested_axis_ids = [axis["axis_id"] for axis in author_request["axes"]]
    assert len(requested_axis_ids) == 3
    coverage = result.audit["structured_list_axis_coverage"][0]
    assert coverage["primary_fact_id"] == fact.fact_id
    assert coverage["retained_axis_ids"] == requested_axis_ids
    assert len(coverage["omitted_axis_ids"]) == 5
    assert coverage["critical_missing_axis_ids"] == coverage["omitted_axis_ids"]
    assert coverage["complete"] is False
    assert result.audit["coverage"]["requires_review"] is True
    assert result.audit["terminal_status"] == "review_required"
