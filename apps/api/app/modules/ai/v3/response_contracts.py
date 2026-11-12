"""Closed versioned model artifacts; shape validation grants no semantic approval."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.modules.ai.v3.author_response_schema import is_lesson_author_response, is_lesson_author_response_format
from app.modules.ai.v3.auxiliary_response_contracts import (
    auxiliary_contract,
    is_auxiliary_format,
    matches_auxiliary_response,
)
from app.modules.ai.v3.batch_review_response_schema import is_batch_review_response, is_batch_review_response_format
from app.modules.ai.v3.diversity_response_schema import is_diversity_author_format, is_diversity_author_response
from app.modules.ai.v3.extraction_response_schema import is_rule_extraction_response, is_rule_extraction_response_format
from app.modules.ai.v3.isolated_attachment_choice_contract import (
    is_attachment_choice_format,
    matches_attachment_choice_response,
)
from app.modules.ai.v3.normalized_editorial_review import (
    is_normalized_editorial_review_format,
    matches_normalized_editorial_review,
)
from app.modules.ai.v3.practical_action_object_graph import is_action_object_graph_format, matches_action_object_graph
from app.modules.ai.v3.practical_arbitration import is_arbitration_format, matches_arbitration
from app.modules.ai.v3.practical_atomic_audit import is_atomic_audit_format, matches_atomic_audit
from app.modules.ai.v3.practical_compact_editorial_contract import (
    is_compact_editorial_review_format,
    is_compact_editorial_verification_format,
    matches_compact_editorial_review,
    matches_compact_editorial_verification,
)
from app.modules.ai.v3.practical_contract import is_practical_course_format, matches_practical_course_response
from app.modules.ai.v3.practical_curriculum import (
    is_curriculum_bank_format,
    is_curriculum_format,
    matches_curriculum,
    matches_curriculum_bank,
)
from app.modules.ai.v3.practical_editorial_contract import (
    is_editorial_review_format,
    is_editorial_revision_format,
    matches_editorial_review,
    matches_editorial_revision,
)
from app.modules.ai.v3.practical_editorial_verification import (
    is_editorial_verification_format,
    matches_editorial_verification,
    matches_editorial_verification_shape,
)
from app.modules.ai.v3.practical_option_predicates import is_option_predicates_format, matches_option_predicates
from app.modules.ai.v3.practical_patch import is_practical_patch_format, matches_practical_patch
from app.modules.ai.v3.practical_prose_revision import is_prose_revision_format, matches_prose_revision
from app.modules.ai.v3.practical_question_context import is_context_format, matches_context_response
from app.modules.ai.v3.practical_question_editor import is_question_editor_format, matches_question_editor
from app.modules.ai.v3.practical_review import is_practical_review_format, matches_practical_review
from app.modules.ai.v3.practical_rule_editorial_contract import (
    is_rule_editorial_review_format,
    is_rule_editorial_verification_format,
    matches_rule_editorial_review,
    matches_rule_editorial_verification,
)
from app.modules.ai.v3.practical_source_audit import is_source_audit_format, matches_source_audit
from app.modules.ai.v3.practical_source_core import is_source_core_format, matches_source_core
from app.modules.ai.v3.practical_source_core_editor import is_source_core_editor_format, matches_source_core_editor
from app.modules.ai.v3.practical_source_reader import is_source_read_format, matches_source_read
from app.modules.ai.v3.practical_source_semantics import (
    is_source_completeness_format,
    is_source_semantics_format,
    is_source_semantics_verification_format,
    matches_source_completeness,
    matches_source_semantics,
    matches_source_semantics_verification,
)
from app.modules.ai.v3.simple_course_address_repair import is_address_repair_format, matches_address_repair_shape
from app.modules.ai.v3.simple_course_block_editor import (
    is_simple_block_editor_format,
    matches_simple_block_editor_shape,
)
from app.modules.ai.v3.simple_course_delta_editor import is_simple_delta_editor_format, matches_simple_delta_editor
from app.modules.ai.v3.simple_course_editor import (
    is_simple_editor_format,
    is_simple_review_format,
    matches_simple_editor,
    matches_simple_review,
)
from app.modules.ai.v3.simple_course_revision_v2 import (
    is_simple_revision_v2_format,
    matches_simple_revision_v2,
)
from app.modules.ai.v3.simple_question_scope_review import (
    is_simple_question_scope_format,
    matches_simple_question_scope,
)
from app.modules.ai.v3.simple_semantic_source_plan import is_semantic_plan_format, matches_semantic_plan_structure
from app.modules.ai.v3.simple_source_unit_plan import is_source_unit_plan_format, matches_source_unit_plan
from app.modules.ai.v3.typed_review_buckets import is_typed_review_format, is_typed_review_response


def response_contract(value: object) -> str | None:
    if is_address_repair_format(value):
        return "simple_course_address_repair"
    if is_simple_block_editor_format(value):
        return "simple_course_block_editor"
    if is_normalized_editorial_review_format(value):
        return "normalized_editorial_review"
    if is_semantic_plan_format(value):
        return "simple_semantic_source_plan"
    if is_simple_delta_editor_format(value):
        return "simple_course_delta_editor"
    if is_source_unit_plan_format(value):
        return "simple_source_unit_plan"
    if is_simple_question_scope_format(value):
        return "simple_question_scope_review"
    if is_simple_revision_v2_format(value):
        return "simple_course_revision_v2"
    if is_simple_editor_format(value):
        return "simple_course_editor"
    if is_simple_review_format(value):
        return "simple_course_review"
    if is_action_object_graph_format(value):
        return "practical_action_object_graph"
    if is_question_editor_format(value):
        return "practical_question_editor"
    if is_prose_revision_format(value):
        return "practical_prose_revision"
    if is_attachment_choice_format(value):
        return "practical_isolated_attachment_choice"
    if is_option_predicates_format(value):
        return "practical_option_predicates"
    if is_compact_editorial_review_format(value):
        return "practical_compact_editorial_review"
    if is_compact_editorial_verification_format(value):
        return "practical_compact_editorial_verification"
    if is_source_completeness_format(value):
        return "practical_source_completeness"
    if is_source_semantics_format(value):
        return "practical_source_semantics"
    if is_source_semantics_verification_format(value):
        return "practical_source_semantics_verification"
    if is_rule_editorial_review_format(value):
        return "practical_rule_editorial_review"
    if is_rule_editorial_verification_format(value):
        return "practical_rule_editorial_verification"
    if is_editorial_verification_format(value):
        return "practical_editorial_verification"
    if is_editorial_review_format(value):
        return "practical_editorial_review"
    if is_editorial_revision_format(value):
        return "practical_editorial_revision"
    if is_source_core_editor_format(value):
        return "practical_source_core_editor"
    if is_source_core_format(value):
        return "practical_source_core"
    if is_curriculum_format(value):
        return "practical_curriculum"
    if is_curriculum_bank_format(value):
        return "practical_curriculum_bank"
    if is_context_format(value):
        return "practical_question_context"
    if is_arbitration_format(value):
        return "practical_arbitration"
    if is_source_read_format(value):
        return "practical_source_read"
    if is_source_audit_format(value) or is_atomic_audit_format(value):
        return "practical_source_audit"
    if is_practical_course_format(value):
        return "practical_course"
    if is_practical_review_format(value):
        return "practical_review"
    if is_practical_patch_format(value):
        return "practical_patch"
    if is_diversity_author_format(value):
        return "diversity_author"
    auxiliary = auxiliary_contract(value)
    if auxiliary is not None and is_auxiliary_format(value):
        return "aux:" + auxiliary
    if is_lesson_author_response_format(value):
        return "lesson"
    if is_rule_extraction_response_format(value):
        return "extraction"
    if is_batch_review_response_format(value):
        return "batch_review"
    if is_typed_review_format(value):
        return "batch_review_buckets"
    return None


def response_contract_hash(value: dict[str, Any]) -> str:
    if response_contract(value) is None:
        raise ValueError("v3_response_format_unknown")
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    ).hexdigest()


def matches_transport_contract(value: object, response_format: dict[str, Any]) -> bool:
    """Retain typed partial decisions; strict compiler approval remains separate."""
    if response_contract(response_format) == 'practical_editorial_verification':
        return matches_editorial_verification_shape(value, response_format)
    return matches_response_contract(value, response_format)


def matches_response_contract(value: object, response_format: dict[str, Any]) -> bool:
    kind = response_contract(response_format)
    if kind == "simple_course_address_repair":
        return matches_address_repair_shape(value, response_format)
    if kind == "simple_course_block_editor":
        return matches_simple_block_editor_shape(value, response_format)
    if kind == "normalized_editorial_review":
        return matches_normalized_editorial_review(value, response_format)
    if kind == "simple_semantic_source_plan":
        return matches_semantic_plan_structure(value, response_format)
    if kind == "simple_course_delta_editor":
        return matches_simple_delta_editor(value, response_format)
    if kind == "simple_source_unit_plan":
        return matches_source_unit_plan(value, response_format)
    if kind == "simple_question_scope_review":
        return matches_simple_question_scope(value, response_format)
    if kind == "simple_course_revision_v2":
        return matches_simple_revision_v2(value, response_format)
    if kind == "simple_course_editor":
        return matches_simple_editor(value, response_format)
    if kind == "simple_course_review":
        return matches_simple_review(value, response_format)
    if kind == "practical_action_object_graph":
        return matches_action_object_graph(value, response_format)
    if kind == "practical_question_editor":
        return matches_question_editor(value, response_format)
    if kind == "practical_prose_revision":
        return matches_prose_revision(value, response_format)
    if kind == "practical_isolated_attachment_choice":
        return matches_attachment_choice_response(value, response_format)
    if kind == "practical_option_predicates":
        return matches_option_predicates(value, response_format)
    if kind == "practical_compact_editorial_review":
        return matches_compact_editorial_review(value, response_format)
    if kind == "practical_compact_editorial_verification":
        return matches_compact_editorial_verification(value, response_format)
    if kind == "practical_source_completeness":
        return matches_source_completeness(value, response_format)
    if kind == "practical_source_semantics":
        return matches_source_semantics(value, response_format)
    if kind == "practical_source_semantics_verification":
        return matches_source_semantics_verification(value, response_format)
    if kind == "practical_rule_editorial_review":
        return matches_rule_editorial_review(value, response_format)
    if kind == "practical_rule_editorial_verification":
        return matches_rule_editorial_verification(value, response_format)
    if kind == "practical_editorial_verification":
        return matches_editorial_verification(value, response_format)
    if kind == "practical_editorial_review":
        return matches_editorial_review(value, response_format)
    if kind == "practical_editorial_revision":
        return matches_editorial_revision(value, response_format)
    if kind == "practical_source_core_editor":
        return matches_source_core_editor(value, response_format)
    if kind == "practical_source_core":
        return matches_source_core(value, response_format)
    if kind == "practical_curriculum":
        return matches_curriculum(value, response_format)
    if kind == "practical_curriculum_bank":
        return matches_curriculum_bank(value, response_format)
    if kind == "practical_question_context":
        return matches_context_response(value, response_format)
    if kind == "practical_arbitration":
        return matches_arbitration(value, response_format)
    if kind == "practical_source_read":
        return matches_source_read(value, response_format)
    if kind == "practical_source_audit":
        return (matches_atomic_audit(value, response_format) if is_atomic_audit_format(response_format)
                else matches_source_audit(value, response_format))
    if kind == "practical_course":
        return matches_practical_course_response(value, response_format)
    if kind == "practical_review":
        return matches_practical_review(value, response_format)
    if kind == "practical_patch":
        return matches_practical_patch(value, response_format)
    if kind == "diversity_author":
        return is_diversity_author_response(value, response_format)
    if kind is not None and kind.startswith("aux:"):
        return matches_auxiliary_response(value, response_format)
    if kind == "lesson":
        return is_lesson_author_response(value)
    if kind == "extraction":
        return is_rule_extraction_response(value)
    if kind == "batch_review":
        return is_batch_review_response(value)
    if kind == "batch_review_buckets":
        return is_typed_review_response(value, response_format)
    return False
