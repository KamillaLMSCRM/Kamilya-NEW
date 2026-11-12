"""Versioned unit context and one optional model-owned plan allocation correction."""
from __future__ import annotations

from typing import Any

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.simple_course_editor_v10 import run_simple_course_editor_v10
from app.modules.ai.v3.simple_finding_evidence import apply_evidence, evidence_request, matches_evidence


async def run_simple_course_editor_v11(packet: Any, corpus: Any, intent: Any, stage: Any, *,
    reference_decisions: tuple[Any, ...] = (), planned_callback: Any = None) -> Any:
    async def versioned(name: str, group: str, messages: Any, fmt: Any, validator: Any) -> Any:
        if ':plan:v9:' in group:
            group = group.replace(':plan:v9:', ':plan:v11:', 1)
        return await stage(name, group, messages, fmt, validator)

    async def repair_evidence(base: Any, additional: Any) -> Any:
        try:
            messages, fmt, context = evidence_request(packet, base)
        except ValueError as exc:
            if str(exc) != 'simple_evidence_not_eligible':
                raise
            return base
        await additional()

        def validate(value: Any) -> Any:
            if not matches_evidence(value, fmt):
                raise ValueError('simple_evidence_response_invalid')
            return value

        group = ('practical:simple:repair-evidence:v11:' + packet.fingerprint + ':unit=' + _digest(base.course)
                 + ':proposal=' + context['inventory_fingerprint'])
        proposal = await stage('repair', group, messages, fmt, validate)
        return apply_evidence(packet, base, context, validate(proposal))

    return await run_simple_course_editor_v10(packet, corpus, intent, versioned,
        reference_decisions=reference_decisions, planned_callback=planned_callback,
        retain_unit_title_context=True, repair_plan_accounting=True, operational_review=True,
        after_body_callback=repair_evidence)
