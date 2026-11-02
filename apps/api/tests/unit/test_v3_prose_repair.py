import socket

import pytest

from app.modules.ai.v3.prose_repair import apply_prose_repairs, unchanged_context


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("network denied")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)


def test_only_exact_unsupported_span_changes_and_sibling_preserved():
    original = "## A\nИсточник не устанавливает срок.\n## B\nСохранённый факт.\n"
    part = "## A\nИсточник не устанавливает срок.\n"
    result, changed = apply_prose_repairs(original, {"1:1:1": part}, {"repairs": [
        {"id": "1:1:1", "old": "Источник не устанавливает срок.",
         "new": "В этих фрагментах срок не указан."}]})
    assert result == "## A\nВ этих фрагментах срок не указан.\n## B\nСохранённый факт.\n"
    assert changed["1:1:1"] == "## A\nВ этих фрагментах срок не указан.\n"


@pytest.mark.parametrize("repairs", [[], [{"id": "wrong", "old": "bad", "new": "ok"}],
    [{"id": "a", "old": "bad", "new": ""}],
    [{"id": "a", "old": "bad", "new": "ok", "extra": True}],
    [{"id": "a", "old": "bad", "new": "ok"}, {"id": "a", "old": "bad", "new": "other"}]])
def test_invalid_ids_or_changes_rejected(repairs):
    with pytest.raises(ValueError):
        apply_prose_repairs("bad sibling", {"a": "bad"}, {"repairs": repairs})


def test_repeated_or_cross_part_span_rejected():
    with pytest.raises(ValueError):
        apply_prose_repairs("bad / bad", {"a": "bad"}, {"repairs": [{"id": "a", "old": "bad", "new": "ok"}]})


def test_changed_source_or_reference_context_fences_promotion():
    assert unchanged_context(["source"], ("ref",), ("source",), ("ref",))
    assert not unchanged_context(["changed"], ("ref",), ("source",), ("ref",))
    assert not unchanged_context(["source"], ("changed",), ("source",), ("ref",))


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["accept", "reject", "malformed", "unknown", "lesson_scope", "mixed", "general_reject", "general_unknown", "legacy"])
async def test_service_one_repair_rechecks_before_promotion(mode, monkeypatch):
    from app.modules.ai.evidence_engine.models import CourseIntent
    from app.modules.ai.v3 import service
    from app.modules.ai.v3.revision_policy import POLICY
    from app.modules.ai.v3.service import generate_v3_course_from_corpus
    from tests.unit.test_v3_partitioned_extraction import Journal, corpus

    original = "Источник не устанавливает срок."
    replacement = "В переданном фрагменте срок не указан."
    calls = {"repair": 0, "review": 0, "general": 0}
    async def no_case_repair(lesson, *_args, **_kwargs):
        return lesson, False
    monkeypatch.setattr(service, "_repair_reviewed_case", no_case_repair)
    monkeypatch.setattr(service, "_nonliteral_case_citation_ids", lambda *_args: set())
    async def invoke(messages, _response_format):
        system, user = messages[0]["content"], messages[1]["content"]
        if "Карту регламента" in system:
            target = user.split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1].strip()
            return {"rules": [{"rule_id": "r1", "section": "Раздел", "title": "Правило",
                                "statement": target, "source_quote": target}]}
        if "независимый контролер" in system:
            calls["general"] += 1
            if calls["general"] == 2 and mode == "general_unknown":
                raise TimeoutError("synthetic general unknown")
            if calls["general"] == 2 and mode == "general_reject":
                return {"verdict": "NEEDS_REVISION", "factual_score": 4, "alignment_score": 4,
                        "didactic_score": 4, "summary": "Остаётся ошибка текста.",
                        "defects": [{"scope": "lesson", "issue": "ошибка текста"}]}
            if mode in {"lesson_scope", "mixed"} and calls["general"] == 1:
                defects = [{"scope": "lesson", "issue": "ложное отсутствие срока"}]
                if mode == "mixed":
                    defects.append({"scope": "question", "question_id": "v1", "issue": "ошибка вопроса"})
                return {"verdict": "NEEDS_REVISION", "factual_score": 4, "alignment_score": 4,
                        "didactic_score": 4, "summary": "Обнаружены замечания к уроку.", "defects": defects}
            return {"verdict": "PASS", "factual_score": 5, "alignment_score": 5,
                    "didactic_score": 5, "summary": "Проверка выполнена.", "defects": []}
        if "Исправь только неподтверждённые" in system:
            calls["repair"] += 1
            return {"repairs": [{"id": "wrong" if mode == "malformed" else "1:1:1",
                                  "old": original, "new": replacement}]}
        if "Фактические утверждения текста урока" in user:
            calls["review"] += 1
            if mode == "unknown" and replacement in user:
                raise TimeoutError("synthetic unknown")
            status = "SUPPORTED" if replacement in user and mode in {"accept", "lesson_scope", "mixed", "general_reject", "general_unknown"} else "UNCERTAIN"
            return {"verdict": status, "claims": [{"claim": "срок", "status": status, "reason": "проверено"}],
                    "summary": "проверено"}
        return {"lesson_id": "l1", "title": "Урок", "module_title": "Модуль", "content": original,
                "cases": [{"case_id": "c1", "rule_id": "r1", "variants": [{"variant_id": "v1",
                    "prompt": "Вопрос", "correct_option": {"text": "верный 1"},
                    "source_quote": "Правило первое.\n\nПравило второе.",
                    "distractor_pool": [{"text": "ошибка 1"}, {"text": "ошибка 2"}, {"text": "ошибка 3"}]}]}]}

    journal = Journal()
    if mode in {"unknown", "general_unknown"}:
        from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
        with pytest.raises(TimeoutError):
            await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
                                                 extraction_journal=journal, route_fingerprint="a" * 64, revision_policy=POLICY)
        with pytest.raises(ExtractionOutcomeUnknownError):
            await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
                                                 extraction_journal=journal, route_fingerprint="a" * 64, revision_policy=POLICY)
        partial = await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
            extraction_journal=journal, route_fingerprint="a" * 64, revision_policy=POLICY, allow_unreviewed_on_unknown=True)
        assert partial.content.modules[0].lessons[0].content == original
        assert partial.diagnostics["requires_source_review"]
        assert calls["repair"] == 1 and calls["review"] == 2
        return
    result = await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
                                                extraction_journal=journal, route_fingerprint="a" * 64,
                                                revision_policy=None if mode == "legacy" else POLICY)
    assert calls["repair"] == (0 if mode == "legacy" else 1)
    assert calls["review"] == (1 if mode in {"malformed", "legacy"} else 2)
    lesson = result.content.modules[0].lessons[0]
    assert lesson.content == (replacement if mode in {"accept", "lesson_scope", "mixed"} else original)
    assert lesson.title == "Урок"
    assert len(result.assessment.assessments[0].mcq) == 1
    assert result.assessment.assessments[0].mcq[0].source_quote == "Правило первое.\n\nПравило второе."
    if mode in {"reject", "malformed", "mixed", "general_reject", "legacy"}:
        assert result.diagnostics["requires_source_review"]
    if mode in {"lesson_scope", "mixed"}:
        assert calls["general"] == 2
        violations = str(result.diagnostics["violations"])
        assert "ложное отсутствие срока" not in violations
        assert ("ошибка вопроса" in violations) == (mode == "mixed")
        evidence = result.diagnostics["validation_report"]["semantic_reviews"]["l1"]
        assert evidence["parts"][0]["verdict"] == "NEEDS_REVISION"
        repair = next(item for item in evidence["lesson_claim_reviews"] if "prose_repair" in item)
        assert repair["general_recheck"]["verdict"] == "PASS" and repair["lesson_scope_resolved"] is True


@pytest.mark.asyncio
async def test_unknown_revision_fails_before_model_call():
    from app.modules.ai.evidence_engine.models import CourseIntent
    from app.modules.ai.v3.service import generate_v3_course_from_corpus
    from tests.unit.test_v3_partitioned_extraction import corpus
    calls = []
    async def invoke(*_args):
        calls.append(True)
        raise AssertionError("must not invoke")
    with pytest.raises(ValueError, match="v3_revision_policy_invalid"):
        await generate_v3_course_from_corpus(corpus(), intent=CourseIntent(), generation_client=invoke,
                                             revision_policy="unknown")
    assert not calls


@pytest.mark.asyncio
async def test_legacy_review_prompt_has_no_new_partial_source_suffix():
    from app.modules.ai.v3.engine import V3GenerationPipeline
    from app.modules.ai.v3.prompts import PARTIAL_SOURCE_REVIEW_SUFFIX
    captured = []
    async def invoke(messages, _response_format):
        captured.append(messages[0]["content"])
        return {"verdict": "UNCERTAIN", "claims": [], "summary": "unknown"}
    await V3GenerationPipeline(invoke).review_answer("scenario", "question", "answer", ["source"], source_prose=True)
    assert PARTIAL_SOURCE_REVIEW_SUFFIX not in captured[0]
    await V3GenerationPipeline(invoke, scoped_revision=True).review_answer("scenario", "question", "answer", ["source"], source_prose=True)
    assert PARTIAL_SOURCE_REVIEW_SUFFIX in captured[1]
