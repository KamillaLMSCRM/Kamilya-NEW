"""Pure server-side contracts for operational application evidence.

These helpers transport and validate already-decided evidence requirements.  They
do not classify source text, infer a key, or replace the existing source,
component, language, education, and independent-critic gates.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.modules.ai.assessment_obligations import MaterialObligation

APPLICATION_PROOF_FIELDS = frozenset(
    {"target_id", "applied", "premise_quote", "action_quote", "reason"}
)
_EVIDENCE_STRENGTH = {"": 0, "source_recognition": 1, "operational_decision": 2}


def derive_assessment_levels(
    target_ids: Sequence[str], obligations: Sequence[MaterialObligation]
) -> dict[str, str]:
    """Return the strongest reconciled evidence level for each requested target.

    The obligation ledger has already established source ownership and admission.
    This function performs only a target-ID intersection and level precedence; it
    neither mutates its inputs nor grants source or assessment approval.
    """

    levels = {target_id: "" for target_id in target_ids}
    for obligation in obligations:
        evidence_level = obligation.evidence_level
        if evidence_level not in {"source_recognition", "operational_decision"}:
            continue
        for target_id in obligation.target_ids:
            if (
                target_id in levels
                and _EVIDENCE_STRENGTH[evidence_level] > _EVIDENCE_STRENGTH[levels[target_id]]
            ):
                levels[target_id] = evidence_level
    return levels


def _bounded_quote(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value == value.strip()
        and 4 <= len(value) <= 1000
    )


def application_proof_issue(
    proofs: Any,
    required_target_ids: Sequence[str],
    stem: str,
    answer: str,
) -> str | None:
    """Return one finite negative code when application evidence is unproved.

    An empty required-target set intentionally needs no application receipt and
    returns ``None``.  That result grants no target or coverage credit; callers
    decide which targets require this independent gate.
    """

    required = tuple(dict.fromkeys(required_target_ids))
    if not required:
        return None
    if not isinstance(stem, str) or not isinstance(answer, str):
        return "application_proof_surface_invalid"
    if not isinstance(proofs, list | tuple):
        return "application_proof_shape_invalid"
    if len(proofs) != len(required):
        return "application_proof_target_coverage_invalid"

    required_set = set(required)
    seen: set[str] = set()
    for proof in proofs:
        if not isinstance(proof, dict) or set(proof) != APPLICATION_PROOF_FIELDS:
            return "application_proof_shape_invalid"
        target_id = proof["target_id"]
        if not isinstance(target_id, str) or target_id not in required_set or target_id in seen:
            return "application_proof_target_coverage_invalid"
        seen.add(target_id)
        if proof["applied"] is not True:
            return "application_not_proven"

        premise_quote = proof["premise_quote"]
        if not _bounded_quote(premise_quote) or premise_quote not in stem:
            return "application_premise_invalid"
        action_quote = proof["action_quote"]
        if not _bounded_quote(action_quote) or action_quote not in answer:
            return "application_action_invalid"
        reason = proof["reason"]
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 300:
            return "application_reason_invalid"

    if seen != required_set:
        return "application_proof_target_coverage_invalid"
    return None
