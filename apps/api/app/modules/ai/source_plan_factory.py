"""Explicit source-planner dispatch; no implicit fallback or checkpoint sharing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

from app.modules.ai import source_application_plan as application
from app.modules.ai.description_negative_review_contract import DESCRIPTION_REVIEW_POLICY
from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact
from app.modules.ai.source_assessment_plan import (
    PLAN_POLICY,
    SourceAssessmentPlan,
    build_source_assessment_plan,
)

SourcePlanMode = Literal["ordinary", "application_first"]
APPLICATION_PLAN_POLICY = application.POLICY


@dataclass(frozen=True, slots=True)
class SourcePlanFactory:
    """Reuse the existing planners and their own evidence/replay contracts."""

    mode: SourcePlanMode = "ordinary"
    description_review: bool = False

    def __post_init__(self) -> None:
        if type(self.mode) is not str or self.mode not in {"ordinary", "application_first"}:
            raise ValueError("worker_cycle_invalid_source_plan_mode")
        if type(self.description_review) is not bool:
            raise ValueError("worker_cycle_invalid_description_review_mode")
        if self.description_review and self.mode != "ordinary":
            raise ValueError("worker_cycle_application_description_review_unsupported")

    @property
    def policy(self) -> str:
        return PLAN_POLICY if self.mode == "ordinary" else application.POLICY

    def identity(self) -> dict[str, str]:
        # Preserve existing ordinary journal identities byte-for-byte.
        if self.mode == "ordinary":
            return ({"description_review_policy": DESCRIPTION_REVIEW_POLICY}
                    if self.description_review else {})
        return {"source_plan_mode": self.mode, "source_plan_policy": self.policy,
                "source_plan_contract_sha256": application.contract_digest()}

    async def build(
        self, lesson: LessonDraft, primary: list[SourceFact], context: list[SourceFact], *,
        client: Any, saved_evidence: dict[str, Any] | None = None,
        audit_first: bool = False, pre_audit_rebuild: bool = False,
        ordinary_builder: Any = None,
    ) -> SourceAssessmentPlan:
        if self.mode == "application_first":
            if audit_first or pre_audit_rebuild:
                raise ValueError("worker_cycle_application_ordinary_flags")
            # Complete-only and at most five calls are owned by this builder.
            # A rejection never invokes the ordinary planner as a fallback.
            return await application.build_application_first_source_plan(
                lesson, primary, context, client=client, saved_evidence=saved_evidence)
        builder = ordinary_builder or build_source_assessment_plan
        flags = ({"audit_first": True} if audit_first else {})
        if pre_audit_rebuild:
            flags["pre_audit_rebuild"] = True
        if self.description_review:
            flags["description_review"] = True
        return cast(SourceAssessmentPlan, await builder(
            lesson, primary, context, client=client, saved_evidence=saved_evidence, **flags))
