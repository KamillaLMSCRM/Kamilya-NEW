"""Project deterministic validator findings into the public editor DTO."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import ClassVar, Final

from .question_validator import (
    QuestionFinding,
    QuestionValidationResult,
)
from .schemas import (
    EditorAssistantValidationIssue,
    EditorAssistantValidationReport,
    EditorPatchPath,
    EditorValidationStatus,
)


class EditorAssistantValidationProjectionError(ValueError):
    """Bounded error raised when findings cannot be exposed safely."""

    code: ClassVar[str] = "validation_projection_failed"

    def __init__(self) -> None:
        super().__init__("Не удалось подготовить отчёт проверки качества.")


_QUESTION_PATH: Final[re.Pattern[str]] = re.compile(
    r"^questions\[[0-9]+\](?:\.prompt)?$"
)
_OPTIONS_PATH: Final[re.Pattern[str]] = re.compile(
    r"^questions\[[0-9]+\]\.options(?:\[[0-9]+\])?$"
)
_EXPLANATION_PATH: Final[re.Pattern[str]] = re.compile(
    r"^questions\[[0-9]+\]\.explanation$"
)
_MAX_PUBLIC_ISSUES: Final[int] = 20


def _public_path(internal_path: str) -> EditorPatchPath:
    if internal_path == "questions" or _QUESTION_PATH.fullmatch(internal_path):
        return EditorPatchPath.TEXT
    if internal_path == "questions[*].options" or _OPTIONS_PATH.fullmatch(internal_path):
        return EditorPatchPath.ANSWER_OPTIONS
    if _EXPLANATION_PATH.fullmatch(internal_path):
        return EditorPatchPath.EXPLANATION
    raise EditorAssistantValidationProjectionError


def _status_for_findings(
    issues: Sequence[EditorAssistantValidationIssue],
) -> EditorValidationStatus:
    if any(issue.blocking for issue in issues):
        return EditorValidationStatus.FAIL
    if issues:
        return EditorValidationStatus.WARN
    return EditorValidationStatus.PASS


def project_validation_report(
    result_or_findings: QuestionValidationResult | Sequence[QuestionFinding],
) -> EditorAssistantValidationReport:
    """Return the safe public report for a validator result or finding sequence.

    Internal paths are reduced to the three public question-edit paths. The
    projection does not carry provider, prompt, source, tenant, or actor data.
    """

    if isinstance(result_or_findings, QuestionValidationResult):
        source_findings = result_or_findings.findings
        try:
            source_status = EditorValidationStatus(result_or_findings.status)
        except (TypeError, ValueError):
            raise EditorAssistantValidationProjectionError from None
    elif isinstance(result_or_findings, Sequence) and not isinstance(
        result_or_findings, str | bytes | bytearray
    ):
        source_findings = result_or_findings
        source_status = None
    else:
        raise EditorAssistantValidationProjectionError

    projected: list[EditorAssistantValidationIssue] = []
    seen: set[tuple[str, str, bool]] = set()
    for finding in source_findings:
        if not isinstance(finding, QuestionFinding):
            raise EditorAssistantValidationProjectionError
        public_path = _public_path(finding.field_path)
        key = (finding.code.value, public_path.value, finding.blocking)
        if key in seen:
            continue
        seen.add(key)
        projected.append(
            EditorAssistantValidationIssue(
                code=finding.code,
                message=finding.message,
                blocking=finding.blocking,
                field_path=public_path,
            )
        )
        if len(projected) > _MAX_PUBLIC_ISSUES:
            raise EditorAssistantValidationProjectionError

    public_status = _status_for_findings(projected)
    if source_status is not None and source_status is not public_status:
        raise EditorAssistantValidationProjectionError
    return EditorAssistantValidationReport(status=public_status, issues=tuple(projected))


__all__ = [
    "EditorAssistantValidationProjectionError",
    "project_validation_report",
]
