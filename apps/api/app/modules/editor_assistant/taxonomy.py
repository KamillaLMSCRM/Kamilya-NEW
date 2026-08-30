"""Normalized taxonomies for the contextual AI editor assistant.

The taxonomies are the primary cross-tenant analytics vocabulary. Values are
stable strings: they are persisted as-is and must never be renamed without a
versioned data migration, because analytics projections group by them.
"""

from __future__ import annotations

from enum import StrEnum


class EditorIntentCategory(StrEnum):
    """Normalized intent of a user request to the editor assistant."""

    REWRITE_WORDING = "rewrite_wording"
    ADD_CONTEXT = "add_context"
    SIMPLIFY_LANGUAGE = "simplify_language"
    CHANGE_DIFFICULTY = "change_difficulty"
    MAKE_SCENARIO_BASED = "make_scenario_based"
    REGENERATE_DISTRACTORS = "regenerate_distractors"
    BALANCE_ANSWER_LENGTH = "balance_answer_length"
    FIX_MULTIPLE_CORRECT_ANSWERS = "fix_multiple_correct_answers"
    FIX_SOURCE_GROUNDING = "fix_source_grounding"
    FIX_GRAMMAR = "fix_grammar"
    REMOVE_DUPLICATION = "remove_duplication"
    ADD_OR_REWRITE_EXPLANATION = "add_or_rewrite_explanation"
    SPLIT_OR_MERGE_CONTENT = "split_or_merge_content"
    OTHER = "other"


class EditorQualityIssueLabel(StrEnum):
    """Normalized deterministic quality-issue labels attached to requests."""

    CORRECT_ANSWER_LENGTH_SIGNAL = "correct_answer_length_signal"
    CORRECT_ANSWER_STYLE_SIGNAL = "correct_answer_style_signal"
    IMPLAUSIBLE_DISTRACTORS = "implausible_distractors"
    MULTIPLE_PLAUSIBLE_CORRECT_ANSWERS = "multiple_plausible_correct_answers"
    UNSUPPORTED_CORRECT_ANSWER = "unsupported_correct_answer"
    MALFORMED_QUESTION = "malformed_question"
    DUPLICATE_QUESTION = "duplicate_question"
    ROTE_RECALL_ONLY = "rote_recall_only"
    LANGUAGE_OR_TRANSLATION_PROBLEM = "language_or_translation_problem"
    EXPLANATION_LEAKED_INTO_ANSWER = "explanation_leaked_into_answer"
    OTHER = "other"


class EditorReasonCode(StrEnum):
    """Finite normalized reasons for failures and rejected AI proposals."""

    DID_NOT_FOLLOW_REQUEST = "did_not_follow_request"
    UNSUPPORTED_INFORMATION = "unsupported_information"
    WORDING_WORSE = "wording_worse"
    ANSWER_REMAINED_OBVIOUS = "answer_remained_obvious"
    CHANGED_TOO_MUCH = "changed_too_much"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_ERROR = "provider_error"
    VALIDATOR_REJECTED = "validator_rejected"
    STALE_BASE_VERSION = "stale_base_version"
    OTHER = "other"


class EditorLifecycleEventType(StrEnum):
    """Append-only lifecycle event types for an editor assistant request."""

    REQUESTED = "requested"
    PREVIEW_STARTED = "preview_started"
    PREVIEW_READY = "preview_ready"
    PREVIEW_FAILED = "preview_failed"
    REGENERATED = "regenerated"
    APPLIED = "applied"
    REJECTED = "rejected"
    MANUALLY_EDITED_AFTER_APPLY = "manually_edited_after_apply"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"


# Terminal outcome states: once reached, no further lifecycle events are
# legal. ``applied`` is intentionally NOT terminal: it may still be followed
# by ``manually_edited_after_apply`` or ``published`` (plan §6.4 feedback
# signals). The true terminals are published, rejected, superseded, expired.
TERMINAL_OUTCOME_STATES: frozenset[str] = frozenset(
    {
        EditorLifecycleEventType.PUBLISHED.value,
        EditorLifecycleEventType.REJECTED.value,
        EditorLifecycleEventType.SUPERSEDED.value,
        EditorLifecycleEventType.EXPIRED.value,
    }
)


# Allowed direct lifecycle transitions. Append-only history means the same
# event type may repeat (idempotent retries), but the request's *outcome*
# state only moves along these edges.
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    EditorLifecycleEventType.REQUESTED.value: frozenset(
        {
            EditorLifecycleEventType.PREVIEW_STARTED.value,
            EditorLifecycleEventType.REJECTED.value,
            EditorLifecycleEventType.EXPIRED.value,
            EditorLifecycleEventType.SUPERSEDED.value,
        }
    ),
    EditorLifecycleEventType.PREVIEW_STARTED.value: frozenset(
        {
            EditorLifecycleEventType.PREVIEW_READY.value,
            EditorLifecycleEventType.PREVIEW_FAILED.value,
            EditorLifecycleEventType.REGENERATED.value,
        }
    ),
    EditorLifecycleEventType.PREVIEW_READY.value: frozenset(
        {
            EditorLifecycleEventType.REGENERATED.value,
            EditorLifecycleEventType.APPLIED.value,
            EditorLifecycleEventType.REJECTED.value,
            EditorLifecycleEventType.EXPIRED.value,
            EditorLifecycleEventType.SUPERSEDED.value,
        }
    ),
    EditorLifecycleEventType.PREVIEW_FAILED.value: frozenset(
        {
            EditorLifecycleEventType.REGENERATED.value,
            EditorLifecycleEventType.REJECTED.value,
            EditorLifecycleEventType.EXPIRED.value,
            EditorLifecycleEventType.SUPERSEDED.value,
        }
    ),
    EditorLifecycleEventType.REGENERATED.value: frozenset(
        {
            EditorLifecycleEventType.PREVIEW_READY.value,
            EditorLifecycleEventType.PREVIEW_FAILED.value,
            EditorLifecycleEventType.REGENERATED.value,
            EditorLifecycleEventType.EXPIRED.value,
            EditorLifecycleEventType.SUPERSEDED.value,
        }
    ),
    EditorLifecycleEventType.APPLIED.value: frozenset(
        {
            EditorLifecycleEventType.MANUALLY_EDITED_AFTER_APPLY.value,
            EditorLifecycleEventType.PUBLISHED.value,
        }
    ),
    EditorLifecycleEventType.MANUALLY_EDITED_AFTER_APPLY.value: frozenset(
        {EditorLifecycleEventType.PUBLISHED.value}
    ),
    EditorLifecycleEventType.PUBLISHED.value: frozenset(),
    EditorLifecycleEventType.REJECTED.value: frozenset(),
    EditorLifecycleEventType.SUPERSEDED.value: frozenset(),
    EditorLifecycleEventType.EXPIRED.value: frozenset(),
}


def allowed_transitions(outcome: str) -> frozenset[str]:
    """Return event types legal as the next recorded outcome for ``outcome``."""

    return _ALLOWED_TRANSITIONS.get(outcome, frozenset())


def can_record_outcome(current_outcome: str | None, event_type: str) -> bool:
    """Whether ``event_type`` may be recorded as the next lifecycle outcome."""

    if current_outcome is None:
        return event_type == EditorLifecycleEventType.REQUESTED.value
    return event_type in allowed_transitions(current_outcome)
