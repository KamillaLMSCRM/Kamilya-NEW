"""Server-derived evidence demand for source-owned assessment components.

This module classifies only the *kind* of evidence a component needs.  It does
not approve a source plan, establish meaning, select a key, or turn a supporting
list label into an independently assessed workplace decision.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

from app.modules.ai.assessment_preservation import is_bounded_nominal_category
from app.modules.ai.complete_clause import _owned_checklist_leaf

if TYPE_CHECKING:
    from app.modules.ai.lesson_cycle import LearningTarget

EvidenceLevel = Literal["source_recognition", "operational_decision"]

_NON_OPERATIONAL_DIMENSIONS = frozenset({
    "object",
    "condition",
    "exception",
    "timing",
    "actor",
    "quantity",
    "operator",
})


def component_evidence_level(
    target: LearningTarget,
    *,
    component: str,
    source_id: str,
    source_text: str,
    dimension: str,
) -> EvidenceLevel:
    """Return the fail-closed evidence demand for one exact owned component.

    ``source_quote_slot`` remains the explicit recognition protocol.  The only
    additional recognition case is a single ordinary nominal leaf whose actor,
    colon governor, physical list row and source offsets are already proved.
    Everything else remains operational, including malformed input.
    """

    if target.construction_mode == "source_quote_slot":
        return "source_recognition"
    requirements = target.answer_requirements
    owners = target.component_source_ids
    if (
        not isinstance(dimension, str)
        or dimension not in _NON_OPERATIONAL_DIMENSIONS
        or not isinstance(component, str)
        or not isinstance(source_id, str)
        or not isinstance(source_text, str)
        or not component
        or not source_id
        or not source_text
        or target.construction_mode
        or target.component_construction
        or target.question_format
        or target.fixed_source_context is not None
        or target.original_context_bindings
        or target.assessed_focus
        or target.source_quote_proposition is not None
        or target.case_context_bindings
        or not isinstance(requirements, tuple | list)
        or len(requirements) != 1
        or not isinstance(requirements[0], tuple | list)
        or tuple(requirements[0]) != (component,)
        or not isinstance(owners, tuple | list)
        or len(owners) != 1
        or not isinstance(owners[0], tuple | list)
        or tuple(owners[0]) != (source_id,)
    ):
        return "operational_decision"
    bindings = target.qualification_bindings
    if not isinstance(bindings, tuple | list) or any(
        isinstance(row, dict) and str(row.get("branch_effect", "")).startswith("changes_")
        for row in bindings
    ):
        return "operational_decision"
    nominal = re.sub(r"[,;.]\Z", "", component)
    if not is_bounded_nominal_category(nominal):
        return "operational_decision"
    if not _owned_checklist_leaf(target, component, source_id, source_text):
        return "operational_decision"
    return "source_recognition"
