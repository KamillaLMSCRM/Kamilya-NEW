"""Pure validation and application of methodologist proposal corrections."""

from __future__ import annotations

from collections.abc import Iterable

from app.modules.staff_import_legacy_adapter import LEGACY_ROOT_EXTERNAL_KEY

from .schemas import (
    EvidenceItem,
    ImportSessionProposal,
    MatchAction,
    ProposalConfidence,
    ProposalCorrection,
    ProposalItemKind,
)


def _validated_copy(item, updates: dict):
    payload = item.model_dump(mode="python")
    payload.update(updates)
    return type(item).model_validate(payload)


def _replace(items: Iterable, correction: ProposalCorrection, updates: dict):
    found = False
    result = []
    for item in items:
        if item.external_key != correction.external_key:
            result.append(item)
            continue
        if found:
            raise ValueError(f"duplicate proposal external key: {correction.external_key}")
        found = True
        action = correction.action or item.action
        if action is MatchAction.CONFLICT:
            action = MatchAction.CREATE
        evidence = [
            *item.evidence,
            EvidenceItem(
                evidence_code="methodologist_correction",
                claim="Структура исправлена методистом до подтверждения.",
                confidence=ProposalConfidence.HIGH,
                reason="Явное исправление в мастере импорта",
            ),
        ]
        result.append(
            _validated_copy(
                item,
                {
                    **updates,
                    "action": action,
                    "confidence": ProposalConfidence.HIGH,
                    "evidence": evidence,
                },
            )
        )
    if not found:
        raise ValueError(f"proposal item not found: {correction.external_key}")
    return result


def apply_proposal_corrections(
    proposal: ImportSessionProposal,
    corrections: list[ProposalCorrection],
) -> ImportSessionProposal:
    """Apply bounded typed corrections and revalidate every hierarchy edge."""

    if not corrections:
        raise ValueError("at least one proposal correction is required")
    if len(corrections) > 500:
        raise ValueError("too many proposal corrections")

    branches = list(proposal.branches)
    departments = list(proposal.departments)
    positions = list(proposal.positions)
    staff = list(proposal.staff)
    corrected_keys: set[str] = set()

    for correction in corrections:
        if correction.external_key in corrected_keys:
            raise ValueError(f"duplicate correction: {correction.external_key}")
        corrected_keys.add(correction.external_key)
        if correction.kind is ProposalItemKind.BRANCH:
            updates = {"branch_name": correction.name} if correction.name is not None else {}
            branches = _replace(branches, correction, updates)
        elif correction.kind is ProposalItemKind.DEPARTMENT:
            updates = {}
            if correction.name is not None:
                updates["department_name"] = correction.name
            if correction.branch_external_key is not None:
                updates["branch_external_key"] = correction.branch_external_key
            departments = _replace(departments, correction, updates)
        elif correction.kind is ProposalItemKind.POSITION:
            updates = {}
            if correction.name is not None:
                updates["position_name"] = correction.name
            if correction.branch_external_key is not None:
                updates["branch_external_key"] = correction.branch_external_key
            if correction.department_external_key is not None:
                updates["department_external_key"] = (
                    None
                    if correction.department_external_key == LEGACY_ROOT_EXTERNAL_KEY
                    else correction.department_external_key
                )
            positions = _replace(positions, correction, updates)
        else:
            updates = {}
            if correction.position_external_key is not None:
                updates["position_external_key"] = correction.position_external_key
            if correction.branch_external_key is not None:
                updates["branch_external_key"] = correction.branch_external_key
            if correction.department_external_key is not None:
                updates["department_external_key"] = (
                    None
                    if correction.department_external_key == LEGACY_ROOT_EXTERNAL_KEY
                    else correction.department_external_key
                )
            staff = _replace(staff, correction, updates)

    branch_keys = {item.external_key for item in branches}
    department_keys = {item.external_key for item in departments}
    position_keys = {item.external_key for item in positions}
    allowed_branches = branch_keys | {LEGACY_ROOT_EXTERNAL_KEY}
    for item in departments:
        if item.branch_external_key not in allowed_branches:
            raise ValueError(f"unknown department branch: {item.branch_external_key}")
    for item in positions:
        if item.branch_external_key not in allowed_branches:
            raise ValueError(f"unknown position branch: {item.branch_external_key}")
        if item.department_external_key is not None and item.department_external_key not in department_keys:
            raise ValueError(f"unknown position department: {item.department_external_key}")
    for item in staff:
        if item.branch_external_key not in allowed_branches:
            raise ValueError(f"unknown staff branch: {item.branch_external_key}")
        if item.department_external_key is not None and item.department_external_key not in department_keys:
            raise ValueError(f"unknown staff department: {item.department_external_key}")
        if item.position_external_key not in position_keys:
            raise ValueError(f"unknown staff position: {item.position_external_key}")

    remaining_conflicts = [
        conflict for conflict in proposal.conflicts if not (set(conflict.proposal_ids) & corrected_keys)
    ]
    return ImportSessionProposal.model_validate(
        {
            **proposal.model_dump(mode="python"),
            "branches": branches,
            "departments": departments,
            "positions": positions,
            "staff": staff,
            "conflicts": remaining_conflicts,
            "revision": None,
            "revision_hash": None,
        }
    )
