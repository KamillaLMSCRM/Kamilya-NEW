"""Deterministic Gate 1 replay tests for standards-native-r1 bottlenecks and P1-P8 fixes."""

from __future__ import annotations

import hashlib
from dataclasses import asdict

import pytest

from app.modules.ai.assessment_components import ComponentRequirement, OwnedComponent
from app.modules.ai.component_surface_comparison import bind_whole_component_comparison
from app.modules.ai.conditional_connective import (
    conditional_connective_receipt,
    conditional_connective_receipt_valid,
)
from app.modules.ai.evidence_engine.application import _surface_second_repair_actionable
from app.modules.ai.evidence_engine.models import SourceFact
from app.modules.ai.evidence_engine.provider_engine import _is_covered_sentence, _redundancy_tokens
from app.modules.ai.final_teaching_eligibility import (
    FINAL_TEACHING_ELIGIBILITY_POLICY,
    FinalTeachingCatalog,
    TeachingBlockRef,
    TeachingCandidateIdentity,
    TeachingRequirement,
    TeachingSourceBinding,
    TeachingSourceContext,
    _digest,
    bind_final_teaching_role,
)
from app.modules.ai.lesson_cycle import (
    Candidate,
    LearningTarget,
    LessonPacket,
    SourceExcerpt,
    _component_validation,
    prepare_component_construction,
)
from app.modules.ai.lesson_surface_grammar import (
    normalize_authored_prose,
    normalize_lesson_surface_grammar,
    prose_grammar_comparison_view,
)
from app.modules.ai.llm_client import ValidatedLLMResult
from app.modules.ai.source_assessment_plan import _plan_primary_groups
from app.modules.ai.worker_lesson_cycle import _MeasuredClient


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_conditional_connective_receipt_handles_trailing_punctuation_correlative_to_and_asterisk() -> None:
    # T2:T1 from standards-native-r1: trailing period on source clause
    t2_src = "в случае если микрокредит не согласован АУП РД."
    t2_lrn = "Если микрокредит не согласован АУП РД"
    r_t2 = conditional_connective_receipt(t2_src, t2_lrn)
    assert r_t2 is not None
    assert conditional_connective_receipt_valid(r_t2, source_component=t2_src, learner_quote=t2_lrn)

    # T3:T1 from standards-native-r1: trailing correlative ", то" on source clause
    t3_src = (
        "В случае если на момент согласования микрокредит погашен "
        "и залоговое имущество возвращено заёмщику, то"
    )
    t3_lrn = "Если на момент согласования микрокредит погашен и залоговое имущество возвращено заёмщику"
    r_t3 = conditional_connective_receipt(t3_src, t3_lrn)
    assert r_t3 is not None
    assert conditional_connective_receipt_valid(r_t3, source_component=t3_src, learner_quote=t3_lrn)

    # Footnote-asterisk prefix on source "в случае если" clause
    t1_src = "*В случае если общая сумма микрокредитов составляет 2 000 000 тенге и более;"
    t1_lrn = "Если общая сумма микрокредитов составляет 2 000 000 тенге и более"
    r_t1 = conditional_connective_receipt(t1_src, t1_lrn)
    assert r_t1 is not None
    assert conditional_connective_receipt_valid(r_t1, source_component=t1_src, learner_quote=t1_lrn)

    # Negative controls: dropped negation "не" or nested "если" must fail closed
    assert conditional_connective_receipt(
        "в случае если микрокредит не согласован АУП РД.",
        "Если микрокредит согласован АУП РД",
    ) is None
    assert conditional_connective_receipt(
        "в случае если микрокредит не согласован, если заёмщик отказался",
        "Если микрокредит не согласован, если заёмщик отказался",
    ) is None


def test_soglasno_dative_government_normalizer_and_component_comparison() -> None:
    # Rule 5 ("согласно «Положении...") deterministic surface normalization
    blocks = [
        {
            "heading": "Дисциплинарная ответственность",
            "text": (
                "За неисполнение настоящих Стандартов предусмотрена ответственность "
                "согласно «Положении о категориях нарушений»."
            ),
            "fact_ids": ["fact-1"],
        }
    ]
    res = normalize_lesson_surface_grammar(blocks)
    assert "согласно «Положению о категориях нарушений»" in res.block_texts[0]
    assert any(op.code == "preposition_soglasno_dative_government" for op in res.operations)

    # T4:T3 ("Согласно договора...") deterministic prose normalization & comparison proof
    src = "Согласно договора о полной коллективной (солидарной) материальной ответственности сотрудников"
    lrn = "Согласно договору о полной коллективной (солидарной) материальной ответственности сотрудников"
    assert normalize_authored_prose(src) == lrn
    norm = prose_grammar_comparison_view(src)
    assert norm.text == lrn
    assert any(op.code == "preposition_soglasno_dative_government" for op in norm.operations)

    comp = bind_whole_component_comparison(
        src,
        lrn,
        source_context=src + ", работники несут ответственность.",
        source_id="src-1",
        verified_governing_bindings=(),
        candidate_container=lrn,
        candidate_start=0,
        candidate_end=len(lrn),
    )
    assert comp is not None
    assert comp.family == "prose_grammar"


def test_bind_final_teaching_role_proves_t1_t2_t3_t4_shapes_from_standards_native_r1() -> None:
    lesson_id = "lesson-91ac6a7a0c98dcf4"
    src_t1_text = (
        "*Если общая сумма микрокредитов, оформленных на одного заёмщика, "
        "по одному залоговому билету и/или по нескольким залоговым билетам в один день "
        "и на одном филиале, составляет 2 000 000 тенге и более, "
        "требуется согласование с Директором РД."
    )
    src_t2_text = (
        "Эксперт-оценщикам категорически запрещается выдавать микрокредиты "
        "в случае если микрокредит не согласован АУП РД."
    )
    src_t3_text = (
        "В случае если на момент согласования микрокредит погашен и залоговое имущество "
        "возвращено заёмщику, то согласование не производится."
    )
    src_t4_cond = (
        "за осуществление неверной оценки (нарушение внутренних инструкций; "
        "неверно применённая проба и/или категория, и/или неверно определённый общий "
        "и чистый вес изделия; подделка из недрагоценного металла) залогового имущества "
        "при приёме и ревизии, причинившей Работодателю прямой действительный ущерб"
    )
    src_t4_scope = "Согласно договора о полной коллективной (солидарной) материальной ответственности сотрудников"
    src_t4_act = "несут солидарную материальную ответственность"
    src_t4_text = f"{src_t4_scope}, работники {src_t4_act} {src_t4_cond}."

    body_t1 = (
        "Если общая сумма микрокредитов, оформленных на одного заёмщика, "
        "по одному залоговому билету и/или по нескольким залоговым билетам в один день "
        "и в одном филиале, составляет 2 000 000 тенге и более, "
        "требуется согласование с Директором РД."
    )
    body_t2 = (
        "Если микрокредит не согласован АУП РД, эксперт-оценщикам "
        "категорически запрещается выдавать микрокредиты."
    )
    body_t3 = (
        "Если на момент согласования микрокредит погашен и залоговое имущество "
        "возвращено заёмщику, согласование не производится."
    )
    body_t4 = (
        "Согласно договору о полной коллективной (солидарной) материальной ответственности сотрудников, "
        "работники несут солидарную материальную ответственность за неверную оценку "
        "залогового имущества при приёме и ревизии, причинившую Работодателю прямой действительный ущерб.\n"
        "К указанной оценке относятся случаи:\n"
        "- нарушение внутренних инструкций;\n"
        "- неверно применённая проба и/или категория, и/или неверно определённый общий и чистый вес изделия;\n"
        "- подделка из недрагоценного металла."
    )
    full_content = "\n\n".join((body_t1, body_t2, body_t3, body_t4))

    def make_ref(ref_id: str, idx: int, fact_id: str, body: str) -> TeachingBlockRef:
        start = full_content.index(body)
        return TeachingBlockRef(
            ref_id=ref_id,
            lesson_id=lesson_id,
            block_id=f"B{idx}",
            block_index=idx,
            fact_ids=(fact_id,),
            heading=f"Раздел {idx}",
            body=body,
            body_start=start,
            body_end=start + len(body),
            body_sha256=_sha256(body),
            dependency_refs=(),
        )

    entries = (
        make_ref("R1", 0, "f1", body_t1),
        make_ref("R2", 1, "f2", body_t2),
        make_ref("R3", 2, "f3", body_t3),
        make_ref("R4", 3, "f4", body_t4),
    )
    lesson_sha = _sha256(lesson_id)
    content_sha = _sha256(full_content)
    custody_sha = _sha256("custody")
    binding_body = {
        "policy": FINAL_TEACHING_ELIGIBILITY_POLICY,
        "lesson_id": lesson_id,
        "lesson_sha256": lesson_sha,
        "content_sha256": content_sha,
        "custody_sha256": custody_sha,
        "entries": [asdict(row) for row in entries],
        "gaps": [],
    }
    catalog = FinalTeachingCatalog(
        policy=FINAL_TEACHING_ELIGIBILITY_POLICY,
        lesson_id=lesson_id,
        lesson_sha256=lesson_sha,
        content_sha256=content_sha,
        custody_sha256=custody_sha,
        surface_binding_sha256=_digest(binding_body),
        entries=entries,
        gaps=(),
    )

    contexts = (
        TeachingSourceContext(
            source_id="s1",
            source_ref="s1",
            text=src_t1_text,
            governing_bindings=(
                TeachingSourceBinding(
                    facet_id="F1",
                    source_id="s1",
                    quote="*Если общая сумма микрокредитов, оформленных на одного заёмщика, по одному залоговому билету и/или по нескольким залоговым билетам в один день и на одном филиале, составляет 2 000 000 тенге и более",
                    role="condition",
                    branch_effect="changes_outcome",
                    quote_start=0,
                    quote_end=src_t1_text.index(", требуется"),
                ),
            ),
        ),
        TeachingSourceContext(
            source_id="s2",
            source_ref="s2",
            text=src_t2_text,
            governing_bindings=(
                TeachingSourceBinding(
                    facet_id="F2",
                    source_id="s2",
                    quote="в случае если микрокредит не согласован АУП РД.",
                    role="condition",
                    branch_effect="changes_outcome",
                    quote_start=src_t2_text.index("в случае если"),
                    quote_end=len(src_t2_text),
                ),
            ),
        ),
        TeachingSourceContext(
            source_id="s3",
            source_ref="s3",
            text=src_t3_text,
            governing_bindings=(
                TeachingSourceBinding(
                    facet_id="F3",
                    source_id="s3",
                    quote="В случае если на момент согласования микрокредит погашен и залоговое имущество возвращено заёмщику, то",
                    role="condition",
                    branch_effect="changes_outcome",
                    quote_start=0,
                    quote_end=src_t3_text.index(" согласование"),
                ),
            ),
        ),
        TeachingSourceContext(
            source_id="s4",
            source_ref="s4",
            text=src_t4_text,
            governing_bindings=(
                TeachingSourceBinding(
                    facet_id="F4_scope",
                    source_id="s4",
                    quote=src_t4_scope,
                    role="scope",
                    branch_effect="scopes_action",
                    quote_start=0,
                    quote_end=len(src_t4_scope),
                ),
                TeachingSourceBinding(
                    facet_id="F4_cond",
                    source_id="s4",
                    quote=src_t4_cond,
                    role="condition",
                    branch_effect="changes_outcome",
                    quote_start=src_t4_text.index(src_t4_cond),
                    quote_end=src_t4_text.index(src_t4_cond) + len(src_t4_cond),
                ),
            ),
        ),
    )

    # Verify T1 (with critic quote omitting leading "Если ")
    t1_quote_without_esli = body_t1[len("Если "):body_t1.index(", требуется")]
    res_t1 = bind_final_teaching_role(
        (catalog,),
        (
            TeachingRequirement(
                ComponentRequirement("T1", "T1:T1", (OwnedComponent("s1", contexts[0].governing_bindings[0].quote),), False),
                "condition",
                ("f1",),
            ),
        ),
        [
            {
                "requirement_id": "T1:T1",
                "relation": "preserved",
                "teaching_refs": ["R1"],
                "teaching_quotes": {"R1": t1_quote_without_esli},
                "reason": "Condition preserved in R1.",
            }
        ],
        role="review",
        candidate=TeachingCandidateIdentity(lesson_id, "q1", ("T1",), "Вопрос 1?", ("А", "Б"), 0),
        source_contexts=contexts,
    )
    assert res_t1.failures == ()
    assert res_t1.negative_requirement_ids == ()

    # Verify T2 (trailing period + leading "Если " omitted by critic quote)
    res_t2 = bind_final_teaching_role(
        (catalog,),
        (
            TeachingRequirement(
                ComponentRequirement("T2", "T2:T1", (OwnedComponent("s2", contexts[1].governing_bindings[0].quote),), False),
                "condition",
                ("f2",),
            ),
        ),
        [
            {
                "requirement_id": "T2:T1",
                "relation": "preserved",
                "teaching_refs": ["R2"],
                "teaching_quotes": {"R2": "микрокредит не согласован АУП РД"},
                "reason": "Condition preserved in R2.",
            }
        ],
        role="review",
        candidate=TeachingCandidateIdentity(lesson_id, "q2", ("T2",), "Вопрос 2?", ("А", "Б"), 0),
        source_contexts=contexts,
    )
    assert res_t2.failures == ()
    assert res_t2.negative_requirement_ids == ()

    # Verify T3 ("В случае если ..., то" -> "Если ...")
    res_t3 = bind_final_teaching_role(
        (catalog,),
        (
            TeachingRequirement(
                ComponentRequirement("T3", "T3:T1", (OwnedComponent("s3", contexts[2].governing_bindings[0].quote),), False),
                "condition",
                ("f3",),
            ),
        ),
        [
            {
                "requirement_id": "T3:T1",
                "relation": "preserved",
                "teaching_refs": ["R3"],
                "teaching_quotes": {
                    "R3": "Если на момент согласования микрокредит погашен и залоговое имущество возвращено заёмщику"
                },
                "reason": "Condition preserved in R3.",
            }
        ],
        role="review",
        candidate=TeachingCandidateIdentity(lesson_id, "q3", ("T3",), "Вопрос 3?", ("А", "Б"), 0),
        source_contexts=contexts,
    )
    assert res_t3.failures == ()
    assert res_t3.negative_requirement_ids == ()

    # Verify T4 (unpacked parenthetical bullet list + "Согласно договору...")
    t4_cond_quote = body_t4[body_t4.index("за неверную оценку"):]
    res_t4 = bind_final_teaching_role(
        (catalog,),
        (
            TeachingRequirement(
                ComponentRequirement("T4", "T4:T2", (OwnedComponent("s4", src_t4_cond),), False),
                "condition",
                ("f4",),
            ),
            TeachingRequirement(
                ComponentRequirement("T4", "T4:T3", (OwnedComponent("s4", src_t4_scope),), False),
                "condition",
                ("f4",),
            ),
        ),
        [
            {
                "requirement_id": "T4:T2",
                "relation": "preserved",
                "teaching_refs": ["R4"],
                "teaching_quotes": {"R4": t4_cond_quote},
                "reason": "Unpacked parenthetical condition preserved in R4.",
            },
            {
                "requirement_id": "T4:T3",
                "relation": "preserved",
                "teaching_refs": ["R4"],
                "teaching_quotes": {
                    "R4": "Согласно договору о полной коллективной (солидарной) материальной ответственности сотрудников"
                },
                "reason": "Contract scope preserved with dative government in R4.",
            },
        ],
        role="review",
        candidate=TeachingCandidateIdentity(lesson_id, "q4", ("T4",), "Вопрос 4?", ("А", "Б"), 0),
        source_contexts=contexts,
    )
    assert res_t4.failures == ()
    assert res_t4.negative_requirement_ids == ()


def test_normative_sentence_deduplication_preserves_negation_and_numbers() -> None:
    positive = "Согласование микрокредита с директором филиала требуется при выдаче."
    negated = "Согласование микрокредита с директором филиала не требуется при выдаче."
    prev = [_redundancy_tokens(positive)]
    assert _is_covered_sentence(positive, prev) is True
    assert _is_covered_sentence(negated, prev) is False

    limit_2m = "Лимит выдачи микрокредита экспертом составляет 2000000 тенге."
    limit_5m = "Лимит выдачи микрокредита экспертом составляет 5000000 тенге."
    assert _is_covered_sentence(limit_5m, [_redundancy_tokens(limit_2m)]) is False


def test_surface_second_repair_actionable_allows_presentation_axes_with_language_quote() -> None:
    request = {
        "groups": [
            {
                "group_id": "R-1",
                "repair_block_ids": ["B1"],
                "candidate_blocks": [{"block_id": "B1", "block_index": 0}],
                "feedback": {"failed_axes": ["grammatical", "readable"], "reason": "Asyndetic comma."},
                "block_failures": [
                    {
                        "block_id": "B1",
                        "code": "lesson_surface_block_review_rejected",
                        "failed_axes": ["grammatical", "readable"],
                        "reason": "Asyndetic comma.",
                    }
                ],
                "language_target_feedback": [
                    {
                        "block_id": "B1",
                        "block_index": 0,
                        "problem_quote": "эксперт-оценщиком, АУП РД",
                    }
                ],
            }
        ]
    }
    audit = {"status": "complete"}
    assert _surface_second_repair_actionable(request, audit) is True

    # Semantic/completeness failure must NOT trigger a second language-only repair round
    semantic_request = {
        "groups": [
            {
                **request["groups"][0],
                "feedback": {"failed_axes": ["complete"], "reason": "Missing clause."},
            }
        ]
    }
    assert _surface_second_repair_actionable(semantic_request, audit) is False


def test_plan_primary_groups_splits_dense_facts_under_four_items() -> None:
    dense_facts = [
        SourceFact(
            fact_id=f"fact-{i}",
            subject="Порядок оценки",
            attribute="Правило",
            value="А" * 1200,
            source_locator=f"sec:{i}",
            confidence=1.0,
        )
        for i in range(3)
    ]
    groups = _plan_primary_groups(dense_facts)
    assert len(groups) == 3
    assert [ [f.fact_id for f in g] for g in groups ] == [["fact-0"], ["fact-1"], ["fact-2"]]


@pytest.mark.asyncio
async def test_measured_client_accumulates_token_usage_and_attempts() -> None:
    class StubClient:
        async def ainvoke_validated(self, *args: object, **kwargs: object) -> ValidatedLLMResult[dict[str, bool]]:
            return ValidatedLLMResult(
                provider="stub",
                model_id="stub-model",
                value={"ok": True},
                attempt_count=2,
                prompt_tokens=350,
                completion_tokens=125,
            )

    async def noop_checkpoint() -> None:
        return None

    measured = _MeasuredClient(StubClient(), noop_checkpoint)
    res = await measured.ainvoke_validated([{"role": "user", "content": "hi"}], parser=lambda s: {"ok": True})
    assert res.value == {"ok": True}
    assert measured.calls == 1
    assert measured.attempts == 2
    assert measured.prompt_tokens == 350
    assert measured.completion_tokens == 125


def test_surface_negation_accepts_fused_nominalization_of_source_particle_negation() -> None:
    from app.modules.ai.evidence_engine.provider_engine import _changes_source_word_negation

    fact = SourceFact(
        fact_id="fact-neg", subject="Согласование", attribute="Правило",
        value=(
            "Согласование проводит АУП РД. Если АУП РД не согласовывает выданный микрокредит, "
            "проставляется отметка НЕ СОГЛАСОВАН. В этом случае составляется Акт несоответствия стандартам."
        ),
        source_locator="sec:1", confidence=1.0,
    )
    restated = (
        "Согласование проводит АУП РД. В случае несогласования выданного микрокредита "
        "составляется Акт несоответствия стандартам."
    )
    assert _changes_source_word_negation(restated, [fact]) is False
    # Negative control: fused negation without any negated source form of the stem.
    positive_only = SourceFact(
        fact_id="fact-pos", subject="Проверка", attribute="Правило",
        value="Эксперт проводит проверку залога и согласование суммы.",
        source_locator="sec:2", confidence=1.0,
    )
    assert _changes_source_word_negation(
        "Эксперт проводит проверку залога; при несогласовании суммы выдача прекращается.",
        [positive_only],
    ) is True


def test_bind_final_teaching_role_proves_bullet_list_table_component_with_partial_quote() -> None:
    lesson_id = "lesson-8f29851764543c36"
    alt_text = (
        "От 700\xa0100 до 1 100\xa0000 тенге для РД г. Усть-Каменогорск, "
        "г. Павлодар, г. Петропавловск, г. Актобе, г. Атырау, г. Караганда, г. Уральск"
    )
    src_text = (
        alt_text
        + "\nот 700\xa0100 до 1 400 000 тенге РД г. Алматы, г. Тараз, г. Шымкент, "
        "г. Астана, г. Актау, г. Жезказган, г.Кызылорда, г. Экибастуз, г. Семей"
    )
    sf = SourceFact(
        fact_id="fact-dba782fe5d37a895",
        subject="I категория",
        attribute="Лимит на выдачу микрокредитов, тенге",
        value=src_text,
        source_locator="doc_id=d1;source_revision=r1;table=1;row=1;column=2",
        confidence=1.0,
    )
    src_id = hashlib.sha256(
        __import__("json").dumps(asdict(sf), ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    body = (
        "Для I категории лимит на выдачу микрокредитов в следующих РД — от 700 100 до 1 100 000 тенге:\n"
        "- г. Усть-Каменогорск\n"
        "- г. Павлодар\n"
        "- г. Петропавловск\n"
        "- г. Актобе\n"
        "- г. Атырау\n"
        "- г. Караганда\n"
        "- г. Уральск"
    )
    heading = "I категория: первая группа РД"
    content = f"### {heading}\n\n{body}"
    body_start = len(f"### {heading}\n\n")
    entry = TeachingBlockRef(
        ref_id="Te0e5fed04faf",
        lesson_id=lesson_id,
        block_id="B1",
        block_index=0,
        fact_ids=(sf.fact_id,),
        heading=heading,
        body=body,
        body_start=body_start,
        body_end=body_start + len(body),
        body_sha256=_sha256(body),
        dependency_refs=(),
    )
    cat_body = {
        "policy": FINAL_TEACHING_ELIGIBILITY_POLICY,
        "lesson_id": lesson_id,
        "lesson_sha256": _sha256(lesson_id),
        "content_sha256": _sha256(content),
        "custody_sha256": _sha256("custody"),
        "entries": [asdict(entry)],
        "gaps": [],
    }
    catalog = FinalTeachingCatalog(
        policy=FINAL_TEACHING_ELIGIBILITY_POLICY,
        lesson_id=lesson_id,
        lesson_sha256=_sha256(lesson_id),
        content_sha256=_sha256(content),
        custody_sha256=_sha256("custody"),
        surface_binding_sha256=_digest(cat_body),
        entries=(entry,),
        gaps=(),
    )
    req = TeachingRequirement(
        component=ComponentRequirement(
            target_id="f1-first-region-group",
            component_id="f1-first-region-group:C1",
            alternatives=(OwnedComponent(source_id=src_id, text=alt_text),),
            full_set=False,
        ),
        kind="action",
        eligible_fact_ids=(sf.fact_id,),
        owner_fact_ids=(sf.fact_id,),
    )
    partial_quote = (
        "Для I категории лимит на выдачу микрокредитов в следующих РД — от 700 100 до 1 100 000 тенге:\n"
        "- г. Усть-Каменогорск\n"
        "- г. Павлодар"
    )
    res = bind_final_teaching_role(
        (catalog,),
        (req,),
        [
            {
                "requirement_id": "f1-first-region-group:C1",
                "relation": "preserved",
                "teaching_refs": ["Te0e5fed04faf"],
                "teaching_quotes": {"Te0e5fed04faf": partial_quote},
                "reason": "The passage teaches the I-category limit and lists Pavlodar.",
            }
        ],
        role="review",
        candidate=TeachingCandidateIdentity(
            lesson_id=lesson_id,
            question_id="q1",
            target_ids=("f1-first-region-group",),
            stem="В рабочей ситуации оформляют микрокредит I категории в отделении г. Павлодар. Какой лимит применить?",
            options=("От 700 100 до 1 100 000 тенге", "От 700 100 до 1 400 000 тенге"),
            selected_index=0,
        ),
        source_contexts=(
            TeachingSourceContext(
                source_id=src_id,
                source_ref="S1P1",
                text=src_text,
                governing_bindings=(),
                source_fact=sf,
            ),
        ),
    )
    assert res.failures == ()
    assert res.evidence[0].native_proof is not None
    assert res.evidence[0].native_proof.mode == "strict_component_restatement"


def test_component_validation_supports_answer_only_view_and_scenario_city_inventory() -> None:
    # 1. Answer-only candidate view when critic also maps fixed_context stem with "все"
    src2_text = (
        "2. Если общая сумма микрокредитов всех залоговых билетов, оформленных на одного клиента "
        "за один день и на одном филиале (приемном пункте) попадает под 1-ю и 2-ю категорию, "
        "необходимо проводить согласование в соответствии с действующими стандартами."
    )
    alt2 = "необходимо проводить согласование в соответствии с действующими стандартами."
    pkt2 = prepare_component_construction(
        LessonPacket(
            tenant_id="t1",
            lesson_id="l2",
            title="Порядок согласования",
            content="Текст",
            sources=(SourceExcerpt(source_id="s2", text=src2_text),),
            targets=(
                LearningTarget(
                    target_id="t-approval",
                    description="Согласование",
                    source_ids=("s2",),
                    answer_requirements=((alt2,),),
                    component_source_ids=(("s2",),),
                ),
            ),
            policy_revision="v1",
            learner_language_gate=True,
        )
    )
    q2 = Candidate(
        question_id="q2",
        target_ids=("t-approval",),
        text=(
            "За один день в одном филиале (приемном пункте) на одного клиента оформлены все залоговые билеты; "
            "общая сумма микрокредитов по ним попадает под I и II категории. Какое решение следует принять?"
        ),
        options=(
            "Необходимо проводить согласование в соответствии с действующими стандартами.",
            "Согласование проводить не требуется.",
        ),
        intent="scenario",
    )
    val2 = _component_validation(
        pkt2,
        q2,
        0,
        ("t-approval",),
        {"s2"},
        [
            {
                "target_id": "t-approval",
                "component_id": "t-approval:C1",
                "source_ref": "S1P1",
                "realizations": [
                    {
                        "part": "stem",
                        "role": "fixed_context",
                        "quote": (
                            "За один день в одном филиале (приемном пункте) на одного клиента оформлены все "
                            "залоговые билеты; общая сумма микрокредитов по ним попадает под I и II категории."
                        ),
                    },
                    {
                        "part": "answer",
                        "role": "discriminating_answer",
                        "quote": "Необходимо проводить согласование в соответствии с действующими стандартами.",
                    },
                ],
            }
        ],
        allow_grammar_realization=True,
    )
    assert val2.failures == ()

    # 2. Scenario city-inventory limit prefix when stem names one city from the inventory
    alt1 = (
        "От 700\xa0100 до 1 100\xa0000 тенге для РД г. Усть-Каменогорск, "
        "г. Павлодар, г. Петропавловск, г. Актобе, г. Атырау, г. Караганда, г. Уральск"
    )
    pkt1 = prepare_component_construction(
        LessonPacket(
            tenant_id="t1",
            lesson_id="l1",
            title="Лимиты",
            content="Текст",
            sources=(SourceExcerpt(source_id="s1", text=alt1),),
            targets=(
                LearningTarget(
                    target_id="f1-first-region-group",
                    description="Лимит I категории",
                    source_ids=("s1",),
                    answer_requirements=((alt1,),),
                    component_source_ids=(("s1",),),
                ),
            ),
            policy_revision="v1",
            learner_language_gate=True,
        )
    )
    q1 = Candidate(
        question_id="q1",
        target_ids=("f1-first-region-group",),
        text="В рабочей ситуации оформляют микрокредит I категории в отделении г. Павлодар. Какой лимит на выдачу применить?",
        options=("От 700 100 до 1 100 000 тенге", "От 700 100 до 1 400 000 тенге"),
        intent="scenario",
    )
    val1 = _component_validation(
        pkt1,
        q1,
        0,
        ("f1-first-region-group",),
        {"s1"},
        [
            {
                "target_id": "f1-first-region-group",
                "component_id": "f1-first-region-group:C1",
                "source_ref": "S1P1",
                "realizations": [
                    {
                        "part": "stem",
                        "role": "fixed_context",
                        "quote": "В рабочей ситуации оформляют микрокредит I категории в отделении г. Павлодар.",
                    },
                    {
                        "part": "answer",
                        "role": "discriminating_answer",
                        "quote": "От 700 100 до 1 100 000 тенге",
                    },
                ],
            }
        ],
        allow_grammar_realization=True,
    )
    assert val1.failures == ()
