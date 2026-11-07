import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.ai.direct_source import DirectSourceError, build_direct_source_corpus
from app.modules.ai.managed_luna_client import ManagedLunaCompletedJsonError, ManagedLunaError
from app.modules.ai.router import submit_course_generation
from app.modules.ai.schemas import AIGenerateRequest
from app.modules.source_editorial_review.analysis import (
    _ManagedSourceJsonRecovery,
    analysis_failure_code,
    analyze,
    blocks,
)
from app.modules.source_editorial_review.domain import (
    POLICY,
    ApprovedEditorialDocument,
    ReviewCommand,
    ReviewConflictError,
    ReviewState,
    render_text,
    text_hash,
)
from app.modules.source_editorial_review.service import apply_command, pin_reviews

ORIGINAL = "До 45 МРП действует первый порядок. Свыше 45 МРП действует второй. Документ оформляет операотр."
QUOTE = "До 45 МРП действует первый порядок."
REPLACEMENT = "До 45 МРП включительно действует первый порядок."


@pytest.mark.parametrize(("error", "expected"), [
    (ManagedLunaError("managed_luna_outcome_unknown"), "source_review_provider_outcome_unknown"),
    (ManagedLunaError("managed_luna_response_invalid"), "source_review_invalid_response"),
    (ValueError("managed_qa_luna_unavailable"), "source_review_provider_unavailable"),
    (ValueError("source_editorial_author_inventory"), "source_review_invalid_response"),
    (RuntimeError("Untrusted diagnostic content"), "source_review_analysis_failed"),
])
def test_source_review_reports_provider_failure_without_leaking_details(error, expected):
    assert analysis_failure_code(error) == expected


@pytest.mark.asyncio
async def test_invalid_json_recovery_keeps_original_and_reuses_existing_review():
    calls = []

    async def request(messages):
        calls.append(messages)
        incoming = json.loads(messages[1]["content"])
        if "proposal_sha256" in incoming:
            return {"proposal_sha256": incoming["proposal_sha256"], "rows": [],
                    "source_questions": [{"excerpt": QUOTE, "category": "boundary", "reason": "Какой порядок при 45 МРП?"}]}
        if len(calls) == 1:
            raise ManagedLunaCompletedJsonError("managed_luna_response_invalid")
        return {"patches": [], "unresolved": []}

    recovery = _ManagedSourceJsonRecovery()
    result = await analyze(ORIGINAL, source_id="document:" + "a" * 64, document_id=str(uuid4()),
                           complete_json=lambda messages: recovery.complete(messages, request))
    assert len(calls) == 3 and recovery.used
    assert calls[0][1:] == calls[1][1:] and calls[1][0]["content"].startswith(calls[0][0]["content"])
    assert "not a valid JSON object" in calls[1][0]["content"]
    assert result["original"] == ORIGINAL and [issue["quote"] for issue in result["issues"]] == [QUOTE]


@pytest.mark.asyncio
async def test_invalid_json_recovery_attempts_only_one_extra_request_per_document():
    messages = [{"role": "system", "content": "Write one JSON object."}, {"role": "user", "content": "Synthetic"}]
    invalid = ManagedLunaCompletedJsonError("managed_luna_response_invalid")
    request = AsyncMock(side_effect=[invalid, {}, invalid])
    recovery = _ManagedSourceJsonRecovery()
    assert await recovery.complete(messages, request) == {}
    with pytest.raises(ManagedLunaCompletedJsonError):
        await recovery.complete(messages, request)
    assert request.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["managed_luna_outcome_unknown", "managed_luna_response_invalid"])
async def test_invalid_json_recovery_does_not_repeat_an_unclassified_failure(code):
    request = AsyncMock(side_effect=ManagedLunaError(code))
    recovery = _ManagedSourceJsonRecovery()
    with pytest.raises(ManagedLunaError, match=code):
        await recovery.complete([], request)
    assert request.await_count == 1 and not recovery.used


def prepared() -> ReviewState:
    state = ReviewState()
    state.apply(1, "queued", {})
    state.apply(2, "running", {})
    start = ORIGINAL.index("операотр")
    state.apply(3, "analyzed", {"policy": POLICY, "original": ORIGINAL,
        "issues": [{"id": "boundary", "start": 0, "end": len(QUOTE), "quote": QUOTE,
                    "reason": "Какой порядок при 45 МРП?"}],
        "automatic": [{"id": "typo", "start": start, "end": start + len("операотр"),
                       "before": "операотр", "after": "оператор", "reason": "Опечатка."}]})
    return state


def command(state: ReviewState, action: str, **kwargs):
    return ReviewCommand(expected_revision=state.revision, request_id=uuid4(), action=action, **kwargs)


def enact(state: ReviewState, action: str, **kwargs):
    kind, payload = state.plan(command(state, action, **kwargs))
    state.apply(state.revision + 1, kind, payload)
    return payload


def test_selected_pdf_pages_remain_part_of_the_approved_edition():
    state = ReviewState()
    chosen = {"first_page": 3, "last_page": 9}
    assert enact(state, "start", pages=chosen) == {"pages": chosen}
    state.apply(2, "running", {})
    state.apply(3, "analyzed", {"original": ORIGINAL, "issues": [], "automatic": []})
    approved = enact(state, "approve")
    assert approved["pages"] == chosen
    assert approved["working_sha256"] == text_hash(ORIGINAL)


def test_boundary_human_decision_automatic_undo_and_historical_snapshot():
    state = prepared()
    with pytest.raises(ReviewConflictError, match="questions_open"):
        enact(state, "approve")
    assert "оператор" in state.working()[0]
    stale = command(state, "undo_auto", item_id="typo", reason="Сверено с регламентом")
    resolved = enact(state, "resolve", item_id="boundary", decision="replace",
                     replacement=REPLACEMENT, reason="Владелец подтвердил включение 45 МРП")
    assert (resolved["before"], resolved["after"]) == (QUOTE, REPLACEMENT)
    with pytest.raises(ReviewConflictError, match="revision_conflict"):
        state.plan(stale)
    undo = enact(state, "undo_auto", item_id="typo", reason="Проверка отмены")
    assert (undo["before"], undo["after"]) == ("оператор", "операотр")
    approved = enact(state, "approve")
    assert approved["working"] == ORIGINAL.replace(QUOTE, REPLACEMENT)
    assert approved["working_sha256"] == text_hash(approved["working"])
    enact(state, "reopen")
    enact(state, "reopen_issue", item_id="boundary", reason="Получен уточнённый ответ")
    assert state.approval is None and state.working()[0] == ORIGINAL
    assert approved["working"].startswith(REPLACEMENT)


def test_unbound_finding_requires_unique_original_quote_to_replace():
    state = prepared()
    state.issues["boundary"] = {"id": "boundary", "start": None, "end": None, "quote": "подозрение"}
    with pytest.raises(ReviewConflictError, match="quote_not_unique"):
        enact(state, "resolve", item_id="boundary", decision="replace", replacement=REPLACEMENT,
              reason="Сверено с оригиналом", quote="несуществующая цитата")
    with pytest.raises(ReviewConflictError, match="requires_exact_change"):
        enact(state, "resolve", item_id="boundary", decision="replace", replacement=REPLACEMENT,
              reason="Сверено с оригиналом")
    enact(state, "resolve", item_id="boundary", decision="replace", replacement=REPLACEMENT,
          reason="Сверено с оригиналом", quote=QUOTE)
    assert enact(state, "approve")["working"].startswith(REPLACEMENT)


@pytest.mark.asyncio
async def test_source_model_flags_numeric_gap_with_original_quote_and_no_invented_rewrite():
    # Actual DEV failure: the first editor returned no ambiguity. The independent
    # check is mandatory even when a document has no proposed text corrections.
    async def answer(messages):
        incoming = json.loads(messages[1]["content"])
        if "proposal_sha256" not in incoming:
            return {"patches": [], "unresolved": []}
        assert "Test each boundary at the exact value" in messages[0]["content"]
        return {"proposal_sha256": incoming["proposal_sha256"], "rows": [], "source_questions": [
            {"excerpt": QUOTE, "category": "boundary", "reason": "Какой порядок при 45 МРП?"},
            {"excerpt": "Несуществующая цитата", "category": "reference", "reason": "Какой пункт имеется в виду?"},
        ]}

    complete = AsyncMock(side_effect=answer)
    result = await analyze(ORIGINAL, source_id="document:" + "b" * 64, document_id=str(uuid4()),
                           complete_json=complete)
    assert complete.await_count == result["model_calls"] == 2
    assert result["issues"][0]["quote"] == QUOTE and result["issues"][0]["start"] == 0
    assert result["issues"][1]["start"] is None
    assert not result["automatic"] and result["original"] == ORIGINAL


@pytest.mark.asyncio
async def test_typo_uncertainty_does_not_require_a_human_policy_decision():
    async def answer(messages):
        incoming = json.loads(messages[1]["content"])
        if "proposal_sha256" not in incoming:
            return {"patches": [], "unresolved": [
                {"alias": "Typo", "excerpt": "операотр", "category": "typo", "reason": "Ошибка написания."}]}
        assert incoming["author_candidate_uncertainties"][0]["excerpt"] == "операотр"
        return {"proposal_sha256": incoming["proposal_sha256"], "rows": [], "source_questions": []}

    result = await analyze(ORIGINAL, source_id="document:" + "b" * 64, document_id=str(uuid4()), complete_json=answer)
    assert not result["issues"] and not result["automatic"] and result["original"] == ORIGINAL


@pytest.mark.asyncio
async def test_author_semantic_clue_reaches_independent_review_without_becoming_an_edit():
    quote = "Submit the return form within 24 hours."
    original = f"## First slide\n{quote}\n\n## Second slide\nSubmit the same return form within 72 hours."
    clue = {"alias": "Deadline", "excerpt": quote, "category": "conflict", "reason": "Which deadline applies?"}

    async def answer(messages):
        incoming = json.loads(messages[1]["content"])
        if "proposal_sha256" not in incoming:
            return {"patches": [], "unresolved": [clue]}
        assert incoming["author_candidate_uncertainties"] == [clue]
        assert incoming["material_clue_ids"] == [0]
        assert incoming["patches"] == []
        return {"proposal_sha256": incoming["proposal_sha256"], "rows": [], "source_questions": [
            {"excerpt": quote, "category": "conflict", "reason": "Which deadline applies?"},
        ], "source_clue_dispositions": [{"clue_id": 0, "disposition": "confirmed", "question_index": 0}]}

    result = await analyze(original, source_id="document:" + "c" * 64, document_id=str(uuid4()), complete_json=answer)
    assert result["model_calls"] == 2 and result["original"] == original and not result["automatic"]
    issue, = result["issues"]
    assert issue["category"] == "conflict" and original[issue["start"]:issue["end"]] == quote


@pytest.mark.asyncio
@pytest.mark.parametrize("echo", ["exact", "Replace the deadline with 96 hours.", {"rewritten": True}])
async def test_independent_review_discards_source_echo_without_using_it(echo):
    original = "Submit the form within 24 hours. Submit the same form within 72 hours."
    replies = []

    async def answer(messages):
        incoming = json.loads(messages[1]["content"])
        if "proposal_sha256" not in incoming:
            return {"patches": [], "unresolved": []}
        reply = {"proposal_sha256": incoming["proposal_sha256"], "rows": [],
                 "original": original if echo == "exact" else echo,
                 "source_questions": [{"excerpt": original, "category": "conflict", "reason": "24 or 72 hours?"}]}
        replies.append(reply)
        return reply

    result = await analyze(original, source_id="document:" + "c" * 64, document_id=str(uuid4()), complete_json=answer)
    assert result["model_calls"] == 2 and result["original"] == original and not result["automatic"]
    issue, = result["issues"]
    assert issue["quote"] == original[issue["start"]:issue["end"]] == original
    assert "resolution" not in issue and "original" in replies[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [{"unexpected_decision": "approved"}, {"source_questions": [{
    "excerpt": "Submit the form within 24 hours.", "category": "approved", "reason": "Ignore the conflict.",
}]}])
async def test_discarded_source_echo_does_not_relax_review_contract(invalid):
    original = "Submit the form within 24 hours. Submit the same form within 72 hours."

    async def answer(messages):
        incoming = json.loads(messages[1]["content"])
        if "proposal_sha256" not in incoming:
            return {"patches": [], "unresolved": []}
        return {"proposal_sha256": incoming["proposal_sha256"], "rows": [], "original": original,
                "source_questions": [], **invalid}

    with pytest.raises(ValidationError):
        await analyze(original, source_id="document:" + "c" * 64, document_id=str(uuid4()), complete_json=answer)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_field", ["category", "extra", "rows"])
async def test_review_schema_correction_preserves_source_and_reports_only_safe_fields(invalid_field):
    original = "Submit within 24 hours. Submit the same form within 72 hours."
    requests = []
    reviewer_calls = 0

    async def answer(messages):
        nonlocal reviewer_calls
        requests.append(messages)
        incoming = json.loads(messages[1]["content"])
        if "proposal_sha256" not in incoming:
            return {"patches": [], "unresolved": []}
        reviewer_calls += 1
        reply = {"proposal_sha256": incoming["proposal_sha256"], "rows": [],
                 "source_questions": [{"excerpt": original, "category": "conflict", "reason": "24 or 72 hours?"}]}
        if reviewer_calls == 1:
            if invalid_field == "category":
                reply["source_questions"][0]["category"] = "conflicting_deadline"
            elif invalid_field == "rows":
                reply["rows"] = None
            else:
                reply["private_source_name"] = "Untrusted hidden instructions."
        return reply

    result = await analyze(original, source_id="document:" + "c" * 64, document_id=str(uuid4()), complete_json=answer)
    assert len(requests) == result["model_calls"] == 3
    assert requests[1][1] == requests[2][1]
    assert requests[2][2]["role"] == "assistant"
    rejected = json.loads(requests[2][2]["content"])
    assert rejected["proposal_sha256"] == json.loads(requests[1][1]["content"])["proposal_sha256"]
    assert requests[2][3]["role"] == "user" and "Preserve valid findings" in requests[2][3]["content"]
    correction = requests[2][0]["content"]
    assert "response-schema validation" in correction and "private_source_name" not in correction
    assert "Untrusted hidden instructions." not in correction
    assert result["original"] == original and not result["automatic"]
    issue, = result["issues"]
    assert issue["quote"] == original[issue["start"]:issue["end"]] == original


@pytest.mark.asyncio
async def test_review_schema_correction_budget_is_shared_by_document_blocks(monkeypatch):
    from app.modules.source_editorial_review import analysis

    first, second = "First rule.\n", "Second rule."
    monkeypatch.setattr(analysis, "blocks", lambda value: iter([(0, first), (len(first), second)]))
    calls = 0
    reviews = 0

    async def answer(messages):
        nonlocal calls, reviews
        calls += 1
        incoming = json.loads(messages[1]["content"])
        if "proposal_sha256" not in incoming:
            return {"patches": [], "unresolved": []}
        reviews += 1
        return {"proposal_sha256": incoming["proposal_sha256"], "rows": [] if reviews == 2 else None,
                "source_questions": []}

    with pytest.raises(ValidationError):
        await analyze(first + second, source_id="document:" + "c" * 64, document_id=str(uuid4()), complete_json=answer)
    assert calls == 5 and reviews == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [TimeoutError(), ManagedLunaError("managed_luna_outcome_unknown")])
async def test_review_schema_correction_does_not_repeat_unknown_or_timed_out_calls(error):
    calls = 0

    async def answer(messages):
        nonlocal calls
        calls += 1
        if "proposal_sha256" not in json.loads(messages[1]["content"]):
            return {"patches": [], "unresolved": []}
        raise error

    with pytest.raises(type(error)):
        await analyze("Original rule.", source_id="document:" + "c" * 64, document_id=str(uuid4()), complete_json=answer)
    assert calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicate_rows, different_deadline", [(False, False), (True, False), (False, True)])
async def test_spreadsheet_conflict_quote_recovers_only_unique_literal_table_span(duplicate_rows, different_deadline):
    first = "For a standard return the employee must submit the form within 24 hours."
    second = "| Section 2 | For the same return the employee must submit the form within 72 hours. |"
    quoted_rows = f"| Section 1 | {first} |\n\n{second}"
    original = f"# Return policy\n\n| Section | Rule |\n\n| --- | --- |\n\n{quoted_rows}"
    if duplicate_rows:
        original += f"\n\n{quoted_rows}"
    reviewer_excerpt = f"{first}\n\n{second}"
    if different_deadline:
        reviewer_excerpt = reviewer_excerpt.replace("72 hours", "96 hours")

    async def answer(messages):
        incoming = json.loads(messages[1]["content"])
        if "proposal_sha256" not in incoming:
            return {"patches": [], "unresolved": [{"alias": "Deadline", "excerpt": quoted_rows,
                "category": "conflict", "reason": "Two deadlines for the same return."}]}
        return {"proposal_sha256": incoming["proposal_sha256"], "rows": [], "source_questions": [
            {"excerpt": reviewer_excerpt, "category": "conflict", "reason": "Which deadline applies?"},
        ], "source_clue_dispositions": [{"clue_id": 0, "disposition": "confirmed", "question_index": 0}]}

    result = await analyze(original, source_id="document:" + "c" * 64, document_id=str(uuid4()), complete_json=answer)
    assert result["model_calls"] == 2 and result["original"] == original and not result["automatic"]
    if duplicate_rows or different_deadline:
        assert len(result["issues"]) == 2
        assert any(issue["quote"] == reviewer_excerpt and issue["start"] is None for issue in result["issues"])
    else:
        issue, = result["issues"]
        assert issue["quote"] == original[issue["start"]:issue["end"]] == quoted_rows
        assert issue["needs_source_verification"] is True
        assert "Which deadline applies?" in issue["reason"]


@pytest.mark.asyncio
async def test_approved_layout_edit_cannot_hide_an_unresolved_source_question():
    quote = "Submit within 24 hours."
    before = "Keep the  receipt."
    after = "Keep the receipt."
    original = f"{quote} Submit the same form within 72 hours. {before}"
    positives = {key: True for key in (
        "digits_preserved", "numeric_values_preserved", "units_preserved", "operators_preserved",
        "negation_modality_preserved", "coordination_logic_preserved", "actors_preserved", "content_complete",
        "no_inferred_list_logic",
    )}

    async def answer(messages):
        incoming = json.loads(messages[1]["content"])
        if "proposal_sha256" not in incoming:
            return {"patches": [{"alias": "Spacing", "before": before, "after": after, "category": "layout",
                "reason": "Remove one repeated space.", "supporting_original_context_quotes": [before]}], "unresolved": []}
        return {"proposal_sha256": incoming["proposal_sha256"], "rows": [
            {"patch_alias": "Spacing", "relation": "preserved", "reason": "The words are unchanged.", **positives}],
            "source_questions": [{"excerpt": quote, "category": "conflict", "reason": "24 or 72 hours?"}]}

    result = await analyze(original, source_id="document:" + "d" * 64, document_id=str(uuid4()), complete_json=answer)
    assert result["issues"][0]["quote"] == quote
    assert render_text(original, result["automatic"])[0].endswith(after)
    with pytest.raises(ReviewConflictError, match="overlapping_or_stale_edit"):
        render_text(original, [{"id": "blank", "start": 0, "end": len(quote), "before": quote, "after": " "}])


@pytest.mark.asyncio
async def test_source_only_review_retains_an_omitted_material_clue_for_human_decision():
    first = "The employee must submit the form within 24 hours."
    second = "The same employee must submit the same form within 72 hours."
    original = f"# First section\n\n{first}\n\n# Second section\n\n{second}"

    async def answer(messages):
        incoming = json.loads(messages[1]["content"])
        if "proposal_sha256" not in incoming:
            return {"patches": [], "unresolved": [{"alias": "Deadline", "excerpt": first,
                "category": "conflict", "reason": "24 and 72 hours for the same action."}]}
        assert "Compare instructions for the same action across headings" in messages[0]["content"]
        assert "For EACH patch" not in messages[0]["content"]
        # Captured DEV shape: analysis completed with no issues despite two
        # competing rules present verbatim in the recognized document.
        return {"proposal_sha256": incoming["proposal_sha256"], "rows": [], "source_questions": []}

    result = await analyze(original, source_id="document:" + "d" * 64, document_id=str(uuid4()), complete_json=answer)
    assert result["model_calls"] == 2
    assert len(result["issues"]) == 1
    issue = result["issues"][0]
    assert issue["needs_source_verification"] and original[issue["start"]:issue["end"]] == first
    state = ReviewState()
    state.apply(1, "queued", {})
    state.apply(2, "running", {})
    state.apply(3, "analyzed", result)
    with pytest.raises(ReviewConflictError, match="source_review_questions_open"):
        enact(state, "approve")


@pytest.mark.asyncio
async def test_bad_clue_disposition_does_not_erase_an_independent_question():
    conflict = "For every return submit the receipt within 24 hours. For every return submit it within 72 hours."
    owner = "The approved officer signs the receipt."
    original = f"{conflict}\n\n{owner}"

    async def answer(messages):
        incoming = json.loads(messages[1]["content"])
        if "proposal_sha256" not in incoming:
            return {"patches": [], "unresolved": [
                {"alias": "Responsible", "excerpt": owner, "category": "responsibility", "reason": "Which officer?"},
            ]}
        return {"proposal_sha256": incoming["proposal_sha256"], "rows": [],
                "source_questions": [{"excerpt": conflict, "category": "conflict", "reason": "Which deadline applies?"}],
                "source_clue_dispositions": [{"clue_id": 0, "disposition": "confirmed", "question_index": 0}]}

    result = await analyze(original, source_id="document:" + "d" * 64, document_id=str(uuid4()), complete_json=answer)
    confirmed, unresolved = result["issues"]
    assert confirmed["quote"] == conflict and not confirmed.get("needs_source_verification")
    assert unresolved["quote"] == owner and unresolved["needs_source_verification"]
    assert result["original"] == original and result["automatic"] == []


@pytest.mark.asyncio
async def test_source_clue_can_be_dismissed_only_with_original_evidence():
    quote = "The routine return form is due the same day."
    exception = "The longer deadline applies only to emergency shutdowns."
    original = f"{quote} {exception}"

    async def answer(messages):
        incoming = json.loads(messages[1]["content"])
        if "proposal_sha256" not in incoming:
            return {"patches": [], "unresolved": [{"alias": "Timing", "excerpt": quote,
                "category": "conflict", "reason": "The form has two deadlines."}]}
        return {"proposal_sha256": incoming["proposal_sha256"], "rows": [], "source_questions": [],
                "source_clue_dispositions": [{"clue_id": 0, "disposition": "dismissed",
                    "evidence_excerpt": exception, "reason": "The source explicitly defines a different scope."}]}

    result = await analyze(original, source_id="document:" + "e" * 64, document_id=str(uuid4()), complete_json=answer)
    assert result["issues"] == [] and result["automatic"] == [] and result["original"] == original


def test_manual_edit_uses_same_history_and_cannot_override_existing_question():
    state = prepared()
    with pytest.raises(ReviewConflictError, match="overlapping_or_stale_edit"):
        enact(state, "add_edit", quote=QUOTE, replacement=REPLACEMENT, reason="Ответ владельца")
    with pytest.raises(ReviewConflictError, match="quote_not_unique"):
        enact(state, "add_edit", quote="Неверная цитата", replacement=REPLACEMENT, reason="Ответ владельца")
    quote = "Свыше 45 МРП действует второй."
    edit = enact(state, "add_edit", quote=quote, replacement="При сумме свыше 45 МРП применяется второй порядок.",
                 reason="Владелец подтвердил название порядка")
    assert state.issues[edit["id"]]["category"] == "manual" and state.decisions[edit["id"]] == edit
    enact(state, "resolve", item_id="boundary", decision="keep", reason="Владелец оставил текст")
    approved = enact(state, "approve")
    assert "применяется второй порядок" in approved["working"] and state.original == ORIGINAL
    enact(state, "reopen")
    enact(state, "reopen_issue", item_id=edit["id"], reason="Уточнён ответ владельца")
    assert quote in state.working()[0] and "применяется второй порядок" in approved["working"]


def test_long_source_blocks_preserve_tail_and_all_original_coordinates():
    source = "Порядок проверки.\n\n" * 7000 + "Последнее исключение."
    parts = list(blocks(source))
    assert len(parts) > 1
    assert "".join(body for _, body in parts) == source
    assert all(source[offset:offset + len(body)] == body for offset, body in parts)


@pytest.mark.asyncio
async def test_retry_reuses_exact_completed_source_block(monkeypatch):
    monkeypatch.setattr("app.modules.source_editorial_review.analysis._BLOCK_CHARS", 80)
    original = "Первый раздел с порядком проверки.\n\n" * 4 + "Последнее исключение."
    completed: dict = {}
    async def answer(messages):
        incoming = json.loads(messages[1]["content"])
        if "proposal_sha256" in incoming:
            return {"proposal_sha256": incoming["proposal_sha256"], "rows": [], "source_questions": []}
        return {"patches": [], "unresolved": []}

    async def first_attempt(messages):
        if completed:
            raise TimeoutError()
        return await answer(messages)

    async def record(key, result):
        completed[key] = result

    args = {"source_id": "document:" + "d" * 64, "document_id": str(uuid4())}
    with pytest.raises(TimeoutError):
        await analyze(original, complete_json=first_attempt, checkpoint=record, **args)
    assert len(completed) == 1
    retry = AsyncMock(side_effect=answer)
    result = await analyze(original, complete_json=retry, retained=completed, **args)
    assert result["original"] == original
    assert retry.await_count == 2 * (len(list(blocks(original))) - 1)


@pytest.mark.asyncio
async def test_generation_gate_runs_before_quota_and_dispatch(monkeypatch):
    doc, tenant, actor = uuid4(), uuid4(), uuid4()
    monkeypatch.setattr("app.modules.source_editorial_review.service.review_enabled", lambda: True)
    monkeypatch.setattr("app.modules.ai.source_analysis.analyze_document_set", AsyncMock())
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[None, SimpleNamespace(content_sha256="a" * 64)]))
    quota, submit = AsyncMock(), AsyncMock()
    monkeypatch.setattr("app.core.demo_limits.check_ai_generation_quota", quota)
    monkeypatch.setattr("app.modules.ai.router.submit_ai_job", submit)
    with pytest.raises(HTTPException) as blocked:
        await submit_course_generation(AIGenerateRequest(documents=[doc]), db, SimpleNamespace(id=actor, tenant_id=tenant))
    assert blocked.value.status_code == 409
    assert blocked.value.detail == {"code": "source_editorial_review_required", "document_ids": [str(doc)]}
    quota.assert_not_awaited()
    submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_only_current_approval_is_admitted_even_if_previous_snapshot_exists():
    doc, tenant = uuid4(), uuid4()
    row = SimpleNamespace(kind="reopened", original_blob_sha256="a" * 64)
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[row, SimpleNamespace(content_sha256="a" * 64)]))
    with pytest.raises(HTTPException) as blocked:
        await pin_reviews(db, tenant, [doc])
    assert blocked.value.status_code == 409


@pytest.mark.asyncio
async def test_idempotency_preserves_receipt_and_rejects_key_reuse(monkeypatch):
    doc = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), content_sha256="a" * 64)
    actor = uuid4()
    submitted = command(ReviewState(), "start")
    stored = SimpleNamespace(kind="queued", sequence=1, original_blob_sha256=doc.content_sha256,
                             payload={}, request_id=submitted.request_id, actor_id=actor,
                             command_sha256=text_hash(submitted.model_dump_json(exclude={"pages"})))
    monkeypatch.setattr("app.modules.source_editorial_review.service.history", AsyncMock(return_value=[stored]))
    db = SimpleNamespace(add=Mock(), flush=AsyncMock())
    _, _, receipt, _ = await apply_command(db, doc, actor, submitted)
    assert receipt is stored
    db.add.assert_not_called()
    with pytest.raises(ReviewConflictError, match="request_id_conflict"):
        await apply_command(db, doc, actor, submitted.model_copy(update={"expected_revision": 1}))
    with pytest.raises(ReviewConflictError, match="request_id_conflict"):
        await apply_command(db, doc, actor, ReviewCommand(
            expected_revision=0, action="start", request_id=submitted.request_id,
            pages={"first_page": 3, "last_page": 9},
        ))


@pytest.mark.asyncio
async def test_worker_uses_pinned_working_text_without_reconverting_original():
    state = prepared()
    enact(state, "resolve", item_id="boundary", decision="replace", replacement=REPLACEMENT,
          reason="Владелец документа подтвердил")
    saved = enact(state, "approve")
    doc = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), title="Source", filename="test.txt", category="general",
                          lifecycle_status="active", content_sha256="a" * 64)
    approved = ApprovedEditorialDocument(str(doc.id), "document:" + doc.content_sha256, str(uuid4()),
        ORIGINAL, saved["working"], saved["working_sha256"], tuple(saved["spans"]), {})
    storage = Mock()
    corpus = await build_direct_source_corpus([doc], tenant_id=doc.tenant_id, storage=storage,
                                              approved_documents={str(doc.id): approved})
    assert corpus.documents[0].source_text == saved["working"]
    assert "включительно" in corpus.documents[0].chunks[0].text
    storage.get_bytes.assert_not_called()
    doc.content_sha256 = "b" * 64
    with pytest.raises(DirectSourceError, match="editorial_unproved"):
        await build_direct_source_corpus([doc], tenant_id=doc.tenant_id, storage=storage,
                                         approved_documents={str(doc.id): approved})
