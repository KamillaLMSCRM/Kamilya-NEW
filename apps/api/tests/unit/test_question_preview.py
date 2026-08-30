"""Synthetic pure tests for the Step 4 single-question preview adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.ai.llm_client import (
    AllProvidersFailedError,
    LLMProviderConfig,
    ResilientLLMClient,
    ValidatedCallFailureReason,
    _LLMResponse,
)
from app.modules.ai.question_preview import (
    PreviewIntent,
    QuestionPreviewContext,
    QuestionPreviewError,
    SourceEvidenceExcerpt,
    UnsupportedPreviewIntent,
    preview_question,
    preview_question_with_validation,
    project_question_preview_analytics,
)
from app.modules.editor_assistant.patch_contract import (
    ContentLifecycle,
    ContentVersionSnapshot,
    EditorTarget,
    EditorTargetEntityType,
    OperationConstraints,
    SourceEvidenceReference,
    StaleBaseVersionError,
    StructuredEditCommand,
    ValidationStatus,
    preview_edit,
)
from app.modules.editor_assistant.question_validator import (
    AnswerOption,
    Question,
    QuestionSignals,
    SourceSupportSignal,
)


def _question(*, signals: QuestionSignals | None = None) -> Question:
    return Question(
        question_id="question-1",
        prompt="What is the approved access route?",
        options=(
            AnswerOption("Use the documented route", True),
            AnswerOption("Ask a colleague", False),
            AnswerOption("Use an unknown route", False),
        ),
        explanation="The documented route is the controlled path.",
        signals=signals or QuestionSignals(),
    )


def _context(
    *,
    intent: PreviewIntent | str = PreviewIntent.WORDING,
    scope: str = "question.text",
    question: Question | None = None,
) -> QuestionPreviewContext:
    target = EditorTarget(EditorTargetEntityType.QUESTION, "question-1", scope)
    snapshot = ContentVersionSnapshot(target, "v1", "a" * 64, ContentLifecycle.DRAFT)
    command = StructuredEditCommand(
        request_key="request-1",
        preview_key="preview-1",
        target=target,
        base_snapshot=snapshot,
        operation_constraints=OperationConstraints(
            allowed_field_paths=("question.text", "question.answer_options", "question.explanation"),
        ),
        instruction_text="Improve this question",
        locale="ru-RU",
    )
    reference = SourceEvidenceReference("source-1", "page-1", "b" * 64)
    return QuestionPreviewContext(
        command=command,
        question=question or _question(),
        intent=intent,
        evidence=(SourceEvidenceExcerpt(reference, "The documented route is the controlled path."),),
    )


def _candidate(context: QuestionPreviewContext, **changes: object) -> str:
    question = context.question
    payload = {
        "prompt": changes.get("prompt", question.prompt),
        "options": changes.get(
            "options",
            [{"text": option.text, "is_correct": option.is_correct} for option in question.options],
        ),
        "explanation": changes.get("explanation", question.explanation),
        "correct_option_index": changes.get(
            "correct_option_index",
            next(index for index, option in enumerate(question.options) if option.is_correct),
        ),
        "source_reference_ids": changes.get("source_reference_ids", ["source-1"]),
        "source_supported": changes.get("source_supported", True),
    }
    return json.dumps(payload, ensure_ascii=False)


def _chain(*responses: str) -> ResilientLLMClient:
    configs = [
        LLMProviderConfig(name=f"provider-{index}", base_url="x", api_key="y", model=f"model-{index}")
        for index in range(len(responses))
    ]
    chain = ResilientLLMClient(configs)
    for client, response in zip(chain._clients, responses, strict=True):
        async def invoke(messages, config=None, response_format=None, *, content=response):
            return _LLMResponse(content)

        client.ainvoke = invoke  # type: ignore[assignment]
    return chain


@pytest.mark.asyncio
async def test_valid_single_question_preview_has_provenance_and_bounded_prompt():
    context = _context()
    llm = _chain(_candidate(context, prompt="Explain the approved access route."))

    patch = await preview_question(context, llm, context.command.base_snapshot)

    assert patch.provider_provenance.provider == "provider-0"
    assert patch.provider_provenance.model_id == "model-0"
    assert patch.provider_provenance.prompt_version == "question-preview-v1"
    assert patch.provider_provenance.generator_version == "editor-assistant-step4-v1"
    assert patch.applicability_status.value == "applicable"
    assert len(patch.operations) == 1
    assert patch.operations[0].field_path == "question.text"
    analytics = project_question_preview_analytics(patch)
    assert "instruction" not in analytics
    assert "The documented route" not in json.dumps(analytics)


@pytest.mark.asyncio
async def test_rejected_primary_falls_back_to_candidate_with_identical_checks():
    context = _context()
    invalid = _candidate(context, correct_option_index=1)
    valid = _candidate(context, prompt="Explain the approved access route.")
    patch = await preview_question(context, _chain(invalid, valid), context.command.base_snapshot)

    assert patch.provider_provenance.provider == "provider-1"
    assert patch.operations[0].after_value == "Explain the approved access route."


@pytest.mark.asyncio
async def test_preserve_correct_answer_violation_fails_closed():
    context = _context()
    options = [
        {"text": "A different keyed answer", "is_correct": True},
        {"text": "Ask a colleague", "is_correct": False},
        {"text": "Use an unknown route", "is_correct": False},
    ]

    with pytest.raises(AllProvidersFailedError) as excinfo:
        await preview_question(context, _chain(_candidate(context, options=options)), context.command.base_snapshot)

    assert "A different keyed answer" not in str(excinfo.value)
    assert excinfo.value.reasons == (ValidatedCallFailureReason.CONTRACT_VIOLATION,)


@pytest.mark.asyncio
async def test_malformed_json_fails_closed_without_raw_content():
    context = _context()
    raw = "not-json-sensitive-question"
    with pytest.raises(AllProvidersFailedError) as excinfo:
        await preview_question(context, _chain(raw, raw), context.command.base_snapshot)
    assert raw not in str(excinfo.value)
    assert excinfo.value.reasons == (ValidatedCallFailureReason.PROVIDER_OUTPUT_UNPARSEABLE,) * 2


@pytest.mark.asyncio
async def test_scope_escape_is_rejected_and_can_fall_back():
    context = _context(scope="question.text", intent=PreviewIntent.WORDING)
    options = [
        {"text": option.text if option.is_correct else option.text + " changed", "is_correct": option.is_correct}
        for option in context.question.options
    ]
    with pytest.raises(AllProvidersFailedError) as excinfo:
        await preview_question(context, _chain(_candidate(context, options=options)), context.command.base_snapshot)
    assert excinfo.value.reasons == (ValidatedCallFailureReason.REJECTED_OUT_OF_SCOPE,)


@pytest.mark.asyncio
async def test_source_rejection_exposes_source_reason_without_source_text():
    context = _context()
    with pytest.raises(AllProvidersFailedError) as excinfo:
        await preview_question(
            context,
            _chain(
                _candidate(
                    context,
                    prompt="Explain the approved access route in detail.",
                    source_reference_ids=["unapproved-source"],
                )
            ),
            context.command.base_snapshot,
        )

    assert excinfo.value.reasons == (ValidatedCallFailureReason.SOURCE_EVIDENCE_UNAVAILABLE,)
    assert "unapproved-source" not in str(excinfo.value)


def test_missing_invalid_evidence_and_unsupported_intent_are_rejected():
    with pytest.raises(QuestionPreviewError):
        QuestionPreviewContext(
            command=_context().command,
            question=_question(),
            intent=PreviewIntent.WORDING,
            evidence=(),
        )
    reference = SourceEvidenceReference("source-1", "page-1")
    with pytest.raises(QuestionPreviewError):
        SourceEvidenceExcerpt(reference, "")
    with pytest.raises(UnsupportedPreviewIntent):
        _context(intent="unsupported-intent")


@pytest.mark.asyncio
async def test_stale_snapshot_is_rejected_before_provider_call():
    context = _context()
    stale_target = context.command.target
    stale = ContentVersionSnapshot(stale_target, "v0", "c" * 64, ContentLifecycle.DRAFT)
    with pytest.raises(StaleBaseVersionError):
        await preview_question(context, _chain(_candidate(context)), stale)


@pytest.mark.asyncio
async def test_validator_blocking_result_is_rejected_and_fallback_must_pass():
    context = _context(question=_question(signals=QuestionSignals(source_support=SourceSupportSignal.UNSUPPORTED)))
    valid = _candidate(context, prompt="Explain the approved access route.")
    with pytest.raises(AllProvidersFailedError) as excinfo:
        await preview_question(context, _chain(valid), context.command.base_snapshot)
    assert excinfo.value.reasons == (ValidatedCallFailureReason.VALIDATION_BLOCKED,)


@pytest.mark.asyncio
async def test_published_preview_requires_new_draft_revision():
    draft_context = _context()
    target = draft_context.command.target
    published_snapshot = ContentVersionSnapshot(target, "v2", "d" * 64, ContentLifecycle.PUBLISHED)
    command = StructuredEditCommand(
        request_key="request-2",
        preview_key="preview-2",
        target=target,
        base_snapshot=published_snapshot,
        operation_constraints=draft_context.command.operation_constraints,
        instruction_text="Improve this question",
        locale="ru-RU",
    )
    context = QuestionPreviewContext(command, draft_context.question, PreviewIntent.WORDING, draft_context.evidence)
    patch = await preview_question(context, _chain(_candidate(context, prompt="Explain the approved access route.")), published_snapshot)
    assert patch.applicability_status.value == "requires_new_draft_revision"


def test_generation_paths_do_not_import_preview_adapter():
    root = Path(__file__).parents[2] / "app" / "modules" / "ai"
    assert "question_preview" not in (root / "assessment.py").read_text(encoding="utf-8")
    assert "question_preview" not in (root / "pipeline.py").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_raw_instruction_and_preservation_rules_are_provider_only(caplog):
    secret_instruction = "SECRET-INSTRUCTION-ONLY-IN-PROVIDER-PROMPT"
    base = _context()
    command = StructuredEditCommand(
        request_key=base.command.request_key,
        preview_key=base.command.preview_key,
        target=base.command.target,
        base_snapshot=base.command.base_snapshot,
        operation_constraints=base.command.operation_constraints,
        instruction_text=secret_instruction,
        locale=base.command.locale,
    )
    context = QuestionPreviewContext(command, base.question, base.intent, base.evidence)
    captured: list[str] = []
    formats: list[dict[str, object] | None] = []
    chain = _chain(_candidate(context, prompt="Explain the approved access route."))
    original = chain._clients[0].ainvoke

    async def capture(messages, config=None, response_format=None):
        captured.append(messages)
        formats.append(response_format)
        return await original(messages, config=config, response_format=response_format)

    chain._clients[0].ainvoke = capture  # type: ignore[assignment]
    with caplog.at_level("WARNING"):
        patch = await preview_question(context, chain, context.command.base_snapshot)

    assert secret_instruction in captured[0]
    assert formats == [{"type": "json_object"}]
    assert '"raw_instruction":"' + secret_instruction + '"' in captured[0]
    assert '"current_correct_option_index":0' in captured[0]
    assert '"current_correct_answer_text":"Use the documented route"' in captured[0]
    assert '"preserve_exact_correct_answer_text":"Use the documented route"' in captured[0]
    assert '"preserve_correct_answer_index":0' in captured[0]
    assert '"preserve_option_count":3' in captured[0]
    assert '"selected_scope":"question.text"' in captured[0]
    assert secret_instruction not in caplog.text
    assert secret_instruction not in json.dumps(project_question_preview_analytics(patch))
    with pytest.raises(AllProvidersFailedError) as excinfo:
        await preview_question(context, _chain("malformed-output"), context.command.base_snapshot)
    assert secret_instruction not in str(excinfo.value)


@pytest.mark.asyncio
async def test_warning_candidate_is_accepted_without_fallback():
    context = _context(intent=PreviewIntent.ANSWER_BALANCE, scope="question.answer_options")
    options = [
        {"text": context.question.options[0].text, "is_correct": True},
        {"text": "Ask a colleague about the documented route and wait for a response", "is_correct": False},
        {"text": "Use an unknown route and ignore the documented controlled path", "is_correct": False},
    ]
    patch = await preview_question(
        context,
        _chain(_candidate(context, options=options), _candidate(context, prompt="fallback")),
        context.command.base_snapshot,
    )

    assert patch.provider_provenance.provider == "provider-0"
    assert patch.validation_report.status is ValidationStatus.WARN


@pytest.mark.asyncio
async def test_preview_outcome_preserves_quality_label_blocking_and_path():
    context = _context(
        question=_question(
            signals=QuestionSignals(explicit_implausible_distractor_indices=(1,)),
        ),
    )
    outcome = await preview_question_with_validation(
        context,
        _chain(_candidate(context, prompt="Explain the approved access route.")),
        context.command.base_snapshot,
    )

    assert outcome.patch.validation_report.status is ValidationStatus.WARN
    assert [
        (finding.code.value, finding.blocking, finding.field_path)
        for finding in outcome.validation_result.findings
    ] == [("implausible_distractors", False, "questions[0].options")]


@pytest.mark.asyncio
async def test_fallback_outcome_contains_fallback_validation_only():
    context = _context(
        intent=PreviewIntent.ANSWER_BALANCE,
        scope="question.answer_options",
        question=_question(
            signals=QuestionSignals(explicit_implausible_distractor_indices=(1,)),
        ),
    )
    rejected_options = [
        {"text": context.question.options[0].text, "is_correct": True},
        {"text": "Ask a colleague", "is_correct": False},
        {"text": "Ask a colleague", "is_correct": False},
    ]
    fallback_options = [
        {"text": context.question.options[0].text, "is_correct": True},
        {"text": "Ask a colleague about the documented route", "is_correct": False},
        {"text": "Use an unknown route in an emergency", "is_correct": False},
    ]
    outcome = await preview_question_with_validation(
        context,
        _chain(
            _candidate(context, options=rejected_options),
            _candidate(context, options=fallback_options),
        ),
        context.command.base_snapshot,
    )

    assert any(
        finding.code.value == "implausible_distractors"
        and finding.blocking is False
        and finding.field_path == "questions[0].options"
        for finding in outcome.validation_result.findings
    )
    assert all(finding.code.value != "malformed_question" for finding in outcome.validation_result.findings)


@pytest.mark.asyncio
async def test_legacy_preview_returns_the_new_outcome_patch_unchanged():
    context = _context()
    response = _candidate(context, prompt="Explain the approved access route.")

    legacy_patch = await preview_question(context, _chain(response), context.command.base_snapshot)
    outcome = await preview_question_with_validation(
        context,
        _chain(response),
        context.command.base_snapshot,
    )

    assert legacy_patch == outcome.patch


@pytest.mark.asyncio
async def test_target_id_mismatch_is_rejected_before_provider_call():
    context = _context()
    mismatched_question = Question(
        question_id="different-question",
        prompt=context.question.prompt,
        options=context.question.options,
        explanation=context.question.explanation,
    )
    with pytest.raises(QuestionPreviewError):
        QuestionPreviewContext(context.command, mismatched_question, context.intent, context.evidence)


@pytest.mark.asyncio
async def test_protected_canonical_field_is_rejected():
    context = _context()
    command = StructuredEditCommand(
        request_key=context.command.request_key,
        preview_key=context.command.preview_key,
        target=context.command.target,
        base_snapshot=context.command.base_snapshot,
        operation_constraints=OperationConstraints(
            allowed_field_paths=("question.text", "question.answer_options", "question.explanation"),
            protected_field_paths=("question.text",),
        ),
        instruction_text=context.command.instruction_text,
        locale=context.command.locale,
    )
    protected_context = QuestionPreviewContext(command, context.question, PreviewIntent.WORDING, context.evidence)
    with pytest.raises(AllProvidersFailedError):
        await preview_question(
            protected_context,
            _chain(_candidate(protected_context, prompt="Explain the approved access route.")),
            protected_context.command.base_snapshot,
        )


@pytest.mark.asyncio
async def test_adapter_patch_is_accepted_by_step2_preview_validation():
    context = _context()
    patch = await preview_question(
        context,
        _chain(_candidate(context, prompt="Explain the approved access route.")),
        context.command.base_snapshot,
    )

    class Provider:
        def propose_patch(self, command):
            return patch

    assert patch.operations[0].field_path == "question.text"
    assert preview_edit(context.command, Provider(), context.command.base_snapshot) == patch
