"""Provider-backed realization layered over the immutable V2 evidence plan."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl

from app.modules.ai.lesson_quality import (
    has_unprofessional_learner_language,
    neutralize_unprofessional_source_language,
)

from .adapters import XlsxEvidenceAdapter
from .engine import EvidenceCourseEngine
from .models import (
    AssessmentDraft,
    CourseDraft,
    CourseIntent,
    LessonDraft,
    LessonEvidence,
    QuestionDraft,
    SourceDocument,
    SourceFact,
    StageTiming,
    is_tabular_locator,
)
from .provider_models import GroundedBlock, ProviderBackedResult, RetrievalMeasurement
from .providers import QWEN_QUERY_PREFIX, ChatJsonProvider, EmbeddingProvider, ProviderCallError
from .quality import (
    contains_internal_generation_instruction,
    contains_visible_artifact,
    evaluate_publishability,
    filter_acceptable_questions,
    is_acceptable_title,
    is_generic_question,
)

if TYPE_CHECKING:
    from app.modules.ai.lesson_surface_review import (
        LessonSurfaceBlockCustody,
        LessonSurfaceReviewResult,
        PreparedLessonSurfaceReview,
    )


@dataclass(frozen=True, slots=True)
class LessonSurfaceRenderScope:
    """Display eligibility and whole-source completeness are separate contracts."""

    reviewed_sources: dict[int, tuple[str, ...]]
    complete_fact_ids: frozenset[str]
    incomplete_fact_ids: frozenset[str]
    partial_preserved_fact_ids: frozenset[str]
    custody: LessonSurfaceBlockCustody | None
    surface_ready: bool


def lesson_surface_render_scope(
    *, prepared: PreparedLessonSurfaceReview, result: LessonSurfaceReviewResult | None,
    base_lesson: LessonDraft, plan_fact_ids: set[str], facts_by_id: dict[str, SourceFact],
    blocks: list[dict[str, Any]],
) -> LessonSurfaceRenderScope:
    result = guarded_lesson_surface_review(prepared=prepared, result=result, base_lesson=base_lesson,
        plan_fact_ids=plan_fact_ids, facts_by_id=facts_by_id, blocks=blocks)
    custody = result.block_custody(prepared=prepared, lesson_id=base_lesson.lesson_id,
        lesson_plan_fact_ids=tuple(fid for fid in base_lesson.fact_ids if fid in plan_fact_ids),
        facts_by_id=facts_by_id, blocks=blocks) if result is not None else None
    healthy = set(custody.healthy_block_ids) if custody is not None else set()
    group_sources = {block_id: group.fact_ids for group in prepared.groups for block_id in group.block_ids}
    # Retain the complete independently reviewed source context as provenance;
    # the author's narrower citation is not an independently proved attribution.
    # This wider provenance never becomes whole-fact completeness below.
    reviewed_sources = {row.block_index: group_sources[row.block_id]
                        for row in custody.receipts if row.block_id in healthy} \
        if custody is not None else {}
    parent_receipts = {row.request_alias for row in result.receipts} if result is not None else set()
    complete: set[str] = set()
    partial: set[str] = set()
    for group in prepared.groups:
        if group.request_alias in parent_receipts and set(group.block_ids) <= healthy:
            complete.update(group.fact_ids)
        elif set(group.block_ids) & healthy:
            partial.update(group.fact_ids)
    return LessonSurfaceRenderScope(reviewed_sources, frozenset(complete),
        frozenset(plan_fact_ids - complete), frozenset(partial), custody,
        custody is not None and custody.surface_ready and complete == plan_fact_ids)


def normalized_lesson_surface_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Use the exact final text for independent review and renderer custody.

    This changes the proposed learner surface only, never a source fact. The
    existing closed display normalizers run before the candidate is reviewed.
    """
    blocks = payload.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("blocks must be a non-empty list")
    normalized = []
    for block in blocks:
        if not isinstance(block, dict) or not isinstance(block.get("heading"), str) or not isinstance(block.get("text"), str):
            raise ValueError("surface block heading and text must be strings")
        normalized.append({**block,
            "heading": neutralize_unprofessional_source_language(_clean_output_text(block["heading"])),
            "text": _clean_learner_body(block["text"])})
    return {**payload, "blocks": normalized}


def guarded_lesson_surface_review(
    *,
    prepared: PreparedLessonSurfaceReview,
    result: LessonSurfaceReviewResult | None,
    base_lesson: LessonDraft,
    plan_fact_ids: set[str],
    facts_by_id: dict[str, SourceFact],
    blocks: list[dict[str, Any]],
) -> LessonSurfaceReviewResult | None:
    """Apply necessary native vetoes once, shared by rendering and repair routing."""
    from app.modules.ai.assessment_meaning import source_coordination_issue
    from app.modules.ai.assessment_preservation import (
        source_governed_nominal_issue,
        source_nominal_relation_issue,
        universal_object_scope_issue,
    )
    from app.modules.ai.lesson_surface_review import reject_lesson_surface_groups

    if result is None:
        return None
    reviewed = result.reviewed_block_indices(
        prepared=prepared, lesson_id=base_lesson.lesson_id,
        lesson_plan_fact_ids=tuple(fid for fid in base_lesson.fact_ids if fid in plan_fact_ids),
        facts_by_id=facts_by_id, blocks=blocks)
    custody = result.block_custody(prepared=prepared, lesson_id=base_lesson.lesson_id,
        lesson_plan_fact_ids=tuple(fid for fid in base_lesson.fact_ids if fid in plan_fact_ids),
        facts_by_id=facts_by_id, blocks=blocks)
    if custody is not None:
        reviewed = reviewed | {row.block_index for row in custody.receipts
                               if row.block_id in custody.healthy_block_ids}
    candidate_issues = lesson_surface_candidate_issues(prepared, blocks=blocks, facts_by_id=facts_by_id) if reviewed else {}
    rejections = {}
    for group in prepared.groups:
        if not set(group.block_indices) & reviewed:
            continue
        positions = sorted(base_lesson.fact_ids.index(fid) for fid in group.fact_ids)
        group_facts = [facts_by_id[fid] for fid in group.fact_ids]
        text = "\n".join(blocks[index]["text"] for index in group.block_indices)
        code = None
        if group.request_alias in candidate_issues:
            code = "lesson_surface_candidate_invalid"
        elif positions != list(range(positions[0], positions[0] + len(positions))):
            code = "lesson_surface_nonadjacent_source_group"
        elif _changes_source_word_negation(text, group_facts):
            code = "lesson_surface_negation_changed"
        elif _loses_normative_qualification(text, group_facts):
            code = "lesson_surface_qualification_lost"
        elif universal_object_scope_issue("\n".join(fact.value for fact in group_facts), text):
            code = "lesson_surface_universal_scope_lost"
        elif source_governed_nominal_issue("\n".join(fact.value for fact in group_facts), text):
            code = "lesson_surface_governed_object_unproved"
        elif source_nominal_relation_issue("\n".join(fact.value for fact in group_facts),
                "\n".join(blocks[index]["heading"] + "\n" + blocks[index]["text"] for index in group.block_indices)):
            code = "lesson_surface_nominal_relation_unproved"
        elif source_coordination_issue(" ".join(fact.value for fact in group_facts), text):
            code = "lesson_surface_coordination_changed"
        if code is not None:
            rejections[group.request_alias] = code
    try:
        return reject_lesson_surface_groups(prepared, result, rejections)
    except ValueError:
        return None


def lesson_surface_candidate_issues(
    prepared: PreparedLessonSurfaceReview,
    *, blocks: list[dict[str, Any]], facts_by_id: dict[str, SourceFact],
) -> dict[str, tuple[str, ...]]:
    """Zero-credit visible-token preflight, shared with final native demotion.

    No renderer fallback can skip this check. Source IDs, hashes and locator
    counters are not evidence for a number in learner prose. This establishes
    neither semantic truth nor completeness and creates no critic receipt.
    """
    issues = {}
    for group in prepared.groups:
        source = " ".join(" ".join((facts_by_id[fid].subject,
            facts_by_id[fid].attribute, facts_by_id[fid].value)) for fid in group.fact_ids)
        allowed = _numbers(source)
        codes = []
        for index in group.block_indices:
            block = blocks[index]
            visible = block["heading"] + " " + block["text"]
            unsupported = _numbers(visible) - allowed
            if unsupported:
                codes.append("source_absent_number=" + ",".join(sorted(unsupported)[:8]))
            if contains_visible_artifact(visible):
                codes.append("visible_artifact")
            if has_unprofessional_learner_language(visible):
                codes.append("unprofessional_language")
            if contains_internal_generation_instruction(visible) and not contains_internal_generation_instruction(source):
                codes.append("internal_generation_instruction")
        if codes:
            issues[group.request_alias] = tuple(dict.fromkeys(codes))
    return issues


def validate_lesson_surface_candidate(
    prepared: PreparedLessonSurfaceReview,
    *, blocks: list[dict[str, Any]], facts_by_id: dict[str, SourceFact],
) -> None:
    issues = lesson_surface_candidate_issues(prepared, blocks=blocks, facts_by_id=facts_by_id)
    if issues:
        codes = tuple(dict.fromkeys(code for group in issues.values() for code in group))
        raise ValueError("lesson_surface_candidate_invalid:" + ";".join(codes)[:400])

# A period inside a date, decimal or hierarchical clause is not a sentence end.
# Splitting it can silently remove a numeric-only component during grounding or
# turn source clause 2.1 into two learner-visible list markers.
_TEACHING_SENTENCE_RE = re.compile(
    r"(?:\d\.\s*(?=\d|[-–—]\s*\S)|[^.!?])+(?:[.!?]+|$)"
)


def _normalize(vector: tuple[float, ...]) -> tuple[float, ...]:
    norm = math.sqrt(sum(value * value for value in vector))
    if not math.isfinite(norm) or norm <= 0:
        raise ProviderCallError("embedding vector has invalid norm")
    normalized = tuple(value / norm for value in vector)
    if any(not math.isfinite(value) for value in normalized):
        raise ProviderCallError("embedding vector contains non-finite values")
    return normalized


_GENERIC_NORMATIVE_LABELS = {'право', 'обязанность', 'запрет', 'срок', 'положение'}


def _source_fallback_heading(fact: SourceFact) -> str:
    """Do not promote a converter category or a cut sentence into a heading."""
    label = fact.attribute
    if (not is_tabular_locator(fact.source_locator)
            and is_acceptable_title(fact.subject)
            and not re.match(r'^\s*\d+(?:\.\d+)*[.)]?\s+', fact.subject)):
        label = fact.subject
    heading = neutralize_unprofessional_source_language(' '.join(label.strip().rstrip('.:').split()))
    if not is_tabular_locator(fact.source_locator) and heading.casefold() in _GENERIC_NORMATIVE_LABELS:
        marker = re.match(r'^\s*(\d+(?:\.\d+)*)[.)]?\s+', fact.value)
        return f'Правило {marker[1]}' if marker else 'Подтверждённые сведения'
    return heading or 'Подтверждённые сведения'


def coalesce_grounded_blocks(
    blocks: list[GroundedBlock],
    facts_by_id: dict[str, SourceFact],
) -> list[GroundedBlock]:
    """Render one stable section per repeated tabular attribute or heading.

    The provider and deterministic fallback may emit one block per worksheet
    cell.  Keeping those blocks separate preserves evidence but produces a
    repeated learner-visible heading for every row.  Coalescing happens only
    after validation, retains first-occurrence order, and unions every fact id.
    """

    grouped: dict[tuple[str, str], int] = {}
    result: list[GroundedBlock] = []
    texts: list[list[str]] = []
    fact_ids: list[list[str]] = []
    for block in blocks:
        cited = [facts_by_id[fact_id] for fact_id in block.fact_ids]
        tabular_scopes = {
            (
                locator.get("doc_id", ""),
                locator.get("source_revision", ""),
                locator.get("section", locator.get("sheet", "")),
                locator.get("table", ""),
                " ".join(fact.attribute.casefold().replace("ё", "е").split()),
            )
            for fact in cited
            for locator in (dict(parse_qsl(fact.source_locator.replace(";", "&"))),)
        }
        if cited and len(tabular_scopes) == 1 and all(
            is_tabular_locator(fact.source_locator) for fact in cited
        ):
            key = ("tabular-attribute", "|".join(next(iter(tabular_scopes))))
            heading = " ".join(cited[0].attribute.strip().rstrip(".:").split()) or block.heading
        else:
            heading = block.heading
            if heading.strip().casefold() in _GENERIC_NORMATIVE_LABELS:
                heading = (_source_fallback_heading(cited[0]) if len(cited) == 1
                           else 'Подтверждённые сведения')
            key = (
                "heading",
                " ".join(heading.casefold().replace("ё", "е").split()),
            )
        position = grouped.get(key)
        if position is not None and key[0] == "heading" and position != len(result) - 1:
            # A repeated prose heading is not sequencing authority. Coalescing
            # non-adjacent source-owned blocks moves the later rule ahead of
            # intervening facts; only adjacent prose blocks may share a heading.
            position = None
        if position is None:
            grouped[key] = len(result)
            result.append(
                GroundedBlock(
                    lesson_id=block.lesson_id,
                    heading=heading,
                    text=block.text,
                    fact_ids=block.fact_ids,
                )
            )
            texts.append([block.text])
            fact_ids.append(list(block.fact_ids))
            continue
        normalized_text = " ".join(block.text.casefold().replace("ё", "е").split())
        if normalized_text not in {
            " ".join(text.casefold().replace("ё", "е").split())
            for text in texts[position]
        }:
            texts[position].append(block.text)
        for fact_id in block.fact_ids:
            if fact_id not in fact_ids[position]:
                fact_ids[position].append(fact_id)
        previous = result[position]
        result[position] = GroundedBlock(
            lesson_id=previous.lesson_id,
            heading=previous.heading,
            text="\n\n".join(texts[position]),
            fact_ids=tuple(fact_ids[position]),
        )
    return result


def _split_nonadjacent_grounded_blocks(
    blocks: list[GroundedBlock],
    *,
    source_fact_ids: tuple[str, ...],
    plan_fact_ids: set[str],
    facts_by_id: dict[str, SourceFact],
) -> list[GroundedBlock]:
    """Keep a writer block only when its cited facts are adjacent in the lesson.

    A provider can combine source facts 1 and 3 in one paragraph and place the
    paragraph before fact 2. Sorting that indivisible block by its first fact
    cannot restore source order, while guessing which authored sentence belongs
    to which fact can detach a condition. For that narrow crossing shape, keep
    the authored heading but render each cited prose fact exactly and let the
    existing source-position sort interleave the intervening rule. Adjacent and
    tabular groups retain the provider's authored content.
    """

    planned_order = [fact_id for fact_id in source_fact_ids if fact_id in plan_fact_ids]
    positions = {fact_id: index for index, fact_id in enumerate(planned_order)}
    restored: list[GroundedBlock] = []
    for block in blocks:
        block_positions = sorted(positions[fact_id] for fact_id in block.fact_ids)
        adjacent = block_positions == list(
            range(block_positions[0], block_positions[0] + len(block_positions))
        )
        cited_facts = [facts_by_id[fact_id] for fact_id in block.fact_ids]
        if (
            len(block_positions) < 2
            or adjacent
            or any(is_tabular_locator(fact.source_locator) for fact in cited_facts)
        ):
            restored.append(block)
            continue
        for fact_id in sorted(block.fact_ids, key=positions.__getitem__):
            fact = facts_by_id[fact_id]
            restored.append(GroundedBlock(
                lesson_id=block.lesson_id,
                heading=block.heading,
                text=_display_source_value(
                    neutralize_unprofessional_source_language(fact.value.strip())
                ),
                fact_ids=(fact_id,),
            ))
    return restored


def _source_ordered_procedure_blocks(
    lesson: LessonDraft,
    facts: list[SourceFact],
) -> list[GroundedBlock] | None:
    """Keep a complete explicit numbered procedure in its original step order.

    Hash-sorted citations and writer grouping are not sequencing authority. This
    narrow projection applies only to a contiguous 1..N sequence in one verified
    document revision/section. Unnumbered prose, tables and unrelated sections
    retain their existing teaching path; no action or exception is invented.
    """
    if len(facts) < 2 or any(is_tabular_locator(fact.source_locator) for fact in facts):
        return None
    positioned: list[tuple[int, int, SourceFact]] = []
    scopes: set[tuple[str, str, str]] = set()
    for fact in facts:
        locator = dict(parse_qsl(fact.source_locator.replace(";", "&")))
        scope = (locator.get("doc_id", ""), locator.get("source_revision", ""),
                 locator.get("section", ""))
        part = locator.get("part", "")
        marker = re.match(r"^\s*(\d+)[.)]\s+\S", fact.value)
        if not all(scope) or not part.isdigit() or marker is None:
            return None
        scopes.add(scope)
        positioned.append((int(part), int(marker.group(1)), fact))
    positioned.sort(key=lambda item: item[0])
    if len(scopes) != 1 or len({part for part, _, _ in positioned}) != len(facts):
        return None
    if [ordinal for _, ordinal, _ in positioned] != list(range(1, len(facts) + 1)):
        return None
    return [GroundedBlock(
        lesson_id=lesson.lesson_id,
        heading=f"Шаг {ordinal}",
        text=_clean_output_text(neutralize_unprofessional_source_language(fact.value)),
        fact_ids=(fact.fact_id,),
    ) for _, ordinal, fact in positioned]


_SPOKEN_NUMBER_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"ноль\s+цел\w*\s+три\s+десят\w*", re.IGNORECASE), "0.3"),
    (re.compile(r"ноль\s+цел\w*\s+пять\s+десят\w*", re.IGNORECASE), "0.5"),
    (re.compile(r"ноль\s+цел\w*\s+три\s+сот\w*", re.IGNORECASE), "0.03"),
    (re.compile(r"\b(?:три|трех|трёх)\b", re.IGNORECASE), "3"),
    (re.compile(r"\b(?:пять|пяти)\b", re.IGNORECASE), "5"),
    (re.compile(r"\b(?:семь|семи)\b", re.IGNORECASE), "7"),
    (re.compile(r"\b(?:десять|десяти)\b", re.IGNORECASE), "10"),
    (re.compile(r"\b(?:пятнадцать|пятнадцати)\b", re.IGNORECASE), "15"),
    (re.compile(r"\b(?:тридцать|тридцати)\b", re.IGNORECASE), "30"),
    (re.compile(r"\b(?:сорок\s+пять|сорока\s+пяти)\b", re.IGNORECASE), "45"),
    (re.compile(r"\b(?:девяносто|девяноста)\b", re.IGNORECASE), "90"),
)


def _numbers(value: str) -> set[str]:
    numbers = {
        item.replace(",", ".")
        for item in re.findall(r"(?<![\w])\d+(?:[.,]\d+)?", value)
    }
    for pattern, normalized in _SPOKEN_NUMBER_PATTERNS:
        if pattern.search(value):
            numbers.add(normalized)
    return numbers


def _clean_output_text(value: str) -> str:
    cleaned = re.sub(r"\bтаюке\b", "также", value, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bвидна\s+жительство\b", "вид на жительство", cleaned,
                     flags=re.IGNORECASE)
    cleaned = re.sub(r"\bзаконодательством\s+PK\b", "законодательством РК", cleaned,
                     flags=re.IGNORECASE)
    cleaned = re.sub(
        r'\b\d{1,3}\.\s*[%("]\s*(?=(?:паспорт|удостоверение|вид\s+на\s+жительство)\b)',
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"(^|[.;:])\s*[%*]\s+(?=(?:паспорт|удостоверение|вид\s+на\s+жительство)\b)",
        r"\1 ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\bи\.\s*др\.", "и др.", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bдр\.\s+\)", "др.)", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"([.!?])\s+,", r"\1,", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _safe_fallback_navigation_heading(
    heading: str,
    cited_facts: list[SourceFact],
) -> bool:
    """Allow provider prose to label, but never substantiate, exact fallback."""

    if (
        not heading
        or contains_visible_artifact(heading)
        or contains_internal_generation_instruction(heading)
        or has_unprofessional_learner_language(heading)
    ):
        return False
    allowed_numbers = set().union(
        *(
            _numbers(" ".join((fact.subject, fact.attribute, fact.value)))
            for fact in cited_facts
        )
    )
    return not (_numbers(heading) - allowed_numbers)


def _readable_source_text(value: str) -> str:
    """Restore presentation boundaries only, never rewrite admitted evidence.

    Grounding uses normalized text. That normalization is not a display format:
    an entire source list must not become a single learner-visible paragraph.
    Only whitespace changes are allowed after the existing grounding gates.
    """
    letters = "A-Za-zА-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі"
    text = re.sub(rf"\s+(?=\d+[.)]\s*[-—]\s*[{letters}])", "\n", value.strip())

    def separate_bullet(match: re.Match[str]) -> str:
        # A composite OCR marker '6. -action' is one visual list marker. Do not
        # move its dash away from its number and create stray numeric prose.
        prefix = match.string[:match.start()]
        if re.search(r"\d+[.)]\s*$", prefix):
            return " "
        # In a source branch, 'при условии - действие' is one requirement,
        # not two independent list items. Keep the separator inside that
        # branch; a following explicit condition still starts its own item.
        condition = r"(?:при|если|в\s+случае)\b"
        if (re.search(rf"(?:^|\n|;\s+|,\s+(?:а\s+)?)(?:[-—]\s*)?(?:\d+[.)]\s*)?(?:[-—]\s*)?{condition}[^.!?\n;]*$",
                      prefix, re.IGNORECASE)
                and not re.match(rf"-\s*(?:\d+[.)]\s*)?{condition}",
                                 match.string[match.end():], re.IGNORECASE)):
            return " "
        return "\n"

    text = re.sub(rf"[ \t]+(?=-\s*(?:\d+[.)]\s*)?[{letters}])", separate_bullet, text)
    text = re.sub(rf"(?m)^(\d+[.)]\s*)?([-—])(?=[{letters}])", r"\1\2 ", text)
    lines: list[str] = []
    for line in text.splitlines():
        if len(line) <= 480:
            lines.append(line)
            continue
        start = 0
        paragraph_start = 0
        for match in re.finditer(r"[.!?]\s+(?=[A-ZА-ЯЁӘҒҚҢӨҰҮҺІ])", line):
            # City/initial abbreviations and numeric notation are not a new
            # paragraph. Never split the content of a sentence by a quota.
            previous_word = re.search(r"([^\W\d_]+)[.!?]$", line[:match.start()+1])
            if previous_word and (
                len(previous_word.group(1)) <= 2
                or previous_word.group(1).casefold() in {"стр", "руб", "рис", "тел", "проф", "ред"}
            ):
                continue
            end = match.start() + 1
            if end - paragraph_start >= 300:
                lines.append(line[start:end].strip())
                lines.append("")
                start = match.end()
                paragraph_start = start
        lines.append(line[start:].strip())
    result = "\n".join(lines).strip()
    if re.sub(r"\s+", "", result) != re.sub(r"\s+", "", value):
        raise ValueError("display formatting changed source content")
    return result


def _structured_source_value(value: str) -> bool:
    """A writer's plain paragraph is not authority to flatten source structure."""
    return "\n" in value or bool(re.search(
        r":\s+(?:\d+[.)]\s*)?[-—•]\s*\S", value,
    ))


def _display_source_value(value: str) -> str:
    """Keep verified paragraph boundaries while applying existing text cleanup."""
    return "\n".join(_clean_output_text(line) for line in value.splitlines()).strip()


def _clean_learner_body(value: str) -> str:
    """Clean horizontal noise without erasing authored paragraphs or list scope.

    Heading/query/source-fact normalization remains intentionally single-line.
    This body-specific operation runs identically before review and rendering.
    """
    lines = []
    for line in value.splitlines():
        indentation = line[:len(line) - len(line.lstrip(" \t"))]
        cleaned = neutralize_unprofessional_source_language(_clean_output_text(line))
        lines.append(indentation + cleaned if cleaned else "")
    return "\n".join(lines).strip()


def _orthographic_negation_view(
    sequence: list[str], counterpart: list[str],
) -> list[str]:
    """Split a proved full-predicate ``неX`` only when the other view has ``не X``.

    This comparison-only view never alters source/candidate bytes.  Exact fused
    spelling plus dictionary family and inflection proof prevents lexical pairs
    such as ``не деля`` / ``неделя`` from acquiring negation equivalence.
    """
    from app.modules.ai.assessment_preservation import _morph

    inflection_grammemes = {
        "sing", "plur", "nomn", "gent", "datv", "accs", "ablt", "loct",
        "masc", "femn", "neut",
    }

    def compatible_full_predicate(positive: str, fused: str) -> bool:
        if fused != "не" + positive or len(positive) < 3:
            return False
        try:
            analyzer = _morph()
            if not (analyzer.word_is_known(positive) and analyzer.word_is_known(fused)):
                return False
            positive_parses = [
                parsed for parsed in analyzer.parse(positive)
                if parsed.tag.POS in {"ADJF", "PRTF"}
            ]
            fused_parses = [
                parsed for parsed in analyzer.parse(fused)
                if parsed.tag.POS in {"ADJF", "PRTF"}
            ]
        except (ImportError, OSError, RuntimeError, ValueError):
            return False
        return any(
            frozenset(left.tag.grammemes) & inflection_grammemes
            == frozenset(right.tag.grammemes) & inflection_grammemes
            and bool(frozenset(left.tag.grammemes) & {"sing", "plur"})
            and right.normal_form.startswith("не")
            and any(
                base.normal_form == left.normal_form
                for base in analyzer.parse(right.normal_form[2:])
                if base.tag.POS in {"ADJF", "PRTF"}
            )
            for left in positive_parses
            for right in fused_parses
        )

    counterpart_split = {
        counterpart[index + 1]
        for index, word in enumerate(counterpart[:-1])
        if word == "не"
    }
    canonical: list[str] = []
    for word in sequence:
        if (
            word.startswith("не")
            and word[2:] in counterpart_split
            and compatible_full_predicate(word[2:], word)
        ):
            canonical.extend(("не", word[2:]))
        else:
            canonical.append(word)
    return canonical


def _changes_source_word_negation(text: str, facts: list[SourceFact]) -> bool:
    """Veto a literal reversal while retaining each mixed word's source order."""
    tokens = re.findall(r"[^\W\d_]+", text.casefold(), re.UNICODE)
    source_tokens = re.findall(
        r"[^\W\d_]+", " ".join(fact.value for fact in facts).casefold(), re.UNICODE,
    )
    raw_tokens, raw_source_tokens = tokens, source_tokens
    tokens = _orthographic_negation_view(raw_tokens, raw_source_tokens)
    source_tokens = _orthographic_negation_view(raw_source_tokens, raw_tokens)
    words, source_words = set(tokens), set(source_tokens)
    def polarities(
        sequence: list[str],
    ) -> tuple[set[str], set[str], dict[str, tuple[bool, ...]]]:
        negative = {word for index, word in enumerate(sequence) if index and sequence[index - 1] == "не"}
        positive = {word for index, word in enumerate(sequence) if not index or sequence[index - 1] != "не"}
        occurrences: dict[str, list[bool]] = defaultdict(list)
        for index, word in enumerate(sequence):
            occurrences[word].append(bool(index and sequence[index - 1] == "не"))
        return negative, positive, {
            word: tuple(pattern) for word, pattern in occurrences.items()
        }
    negative, positive, occurrence_polarity = polarities(tokens)
    source_negative, source_positive, source_occurrence_polarity = polarities(source_tokens)
    mixed_source_polarity = source_negative & source_positive
    if ((source_negative - source_positive) & positive
            or (negative - source_negative) & source_positive
            or any(
                source_occurrence_polarity[word] != occurrence_polarity.get(word, ())
                for word in mixed_source_polarity
            )):
        return True
    # Word-internal noun negation must compare dictionary identities, not case
    # endings: несоответствия / несоответствии retain the same polarity. Unknown
    # or ambiguous words keep the previous literal guard; no suffix guessing.
    from app.modules.ai.assessment_preservation import source_edit_noun_signature

    def noun_identity(word: str) -> str:
        signature = source_edit_noun_signature(word)
        if signature and len(signature) == 1 and signature[0].startswith("noun:"):
            return signature[0][5:]
        return word

    normalized_tokens = [noun_identity(word) for word in tokens]
    normalized_source = [noun_identity(word) for word in source_tokens]
    words, source_words = set(normalized_tokens), set(normalized_source)
    mixed_bases = {word[2:] for word in source_words
        if len(word) >= 6 and word.startswith("не") and word[2:] in source_words}
    def signed_runs(sequence: list[str], base: str) -> tuple[bool, ...]:
        runs: list[bool] = []
        for word in sequence:
            if word in {base, "не" + base}:
                polarity = word.startswith("не")
                if not runs or runs[-1] != polarity:
                    runs.append(polarity)
        return tuple(runs)

    # Explanatory prose can mention the same positive noun fewer times without
    # reversing it. Retain order of polarity transitions, not a word-count quota.
    if any(signed_runs(normalized_source, base) != signed_runs(normalized_tokens, base) for base in mixed_bases):
        return True
    return any(
        len(word) >= 6 and word.startswith("не") and word[2:] in words
        and word[2:] not in source_words
        for word in source_words
    ) or any(
        len(word) >= 6 and word.startswith("не") and word[2:] in source_words
        and word not in source_words
        for word in words
    )


_GROUNDING_STOPWORDS = {
    "без", "более", "бы", "был", "была", "быть", "в", "во", "для", "до",
    "его", "если", "и", "из", "или", "к", "как", "на", "не", "но", "о",
    "по", "при", "с", "со", "также", "то", "только", "у", "что", "это",
    "a", "an", "and", "as", "at", "for", "from", "if", "in", "is", "not",
    "of", "on", "only", "or", "the", "this", "to", "when", "with",
}


def _grounding_tokens(value: str) -> set[str]:
    return {
        token[:7]
        for token in re.findall(r"[^\W\d_]{3,}", value.casefold().replace("ё", "е"), re.UNICODE)
        if token not in _GROUNDING_STOPWORDS
    }


_REDUNDANCY_GENERIC_TOKENS = {"колл", "лине", "сери", "coll", "rang"}


def _redundancy_tokens(value: str) -> set[str]:
    return {token[:4] for token in _grounding_tokens(value)} - _REDUNDANCY_GENERIC_TOKENS


def _is_covered_sentence(value: str, previous: list[set[str]]) -> bool:
    """Return true when a later short sentence adds no new source meaning."""
    tokens = _redundancy_tokens(value)
    if len(tokens) < 3:
        return False
    return any(
        len(tokens) <= len(available)
        and len(tokens & available) / len(tokens) >= 0.85
        for available in previous
    )


_ADDED_OBJECT_REFERENT_PATTERNS = (
    re.compile(
        r"\b(?P<verb>[A-Za-z]{3,})\s+"
        r"(?P<pronoun>it|them|him|her)\s+"
        r"(?P<preposition>for|from|on|to|of|by|with)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<verb>[^\W\d_]{3,}(?:ть|ти|чь))\s+"
        r"(?P<pronoun>его|ее|её|их|это|этих)\s+"
        r"(?P<preposition>на|для|по|при|с|со|в|во|к|из)\b",
        re.IGNORECASE,
    ),
)


def _restore_unresolved_source_referents(text: str, facts: list[SourceFact]) -> str:
    """Remove only an object pronoun absent from an exact source verb/preposition pair."""
    source = " ".join(_clean_output_text(fact.value) for fact in facts)

    def restore(match: re.Match[str]) -> str:
        verb = match.group("verb")
        pronoun = match.group("pronoun")
        preposition = match.group("preposition")
        direct = re.compile(
            rf"\b{re.escape(verb)}\s+{re.escape(preposition)}\b",
            re.IGNORECASE,
        )
        explicit = re.compile(
            rf"\b{re.escape(verb)}\s+{re.escape(pronoun)}\s+{re.escape(preposition)}\b",
            re.IGNORECASE,
        )
        if direct.search(source) and not explicit.search(source):
            return f"{verb} {preposition}"
        return match.group(0)

    for pattern in _ADDED_OBJECT_REFERENT_PATTERNS:
        text = pattern.sub(restore, text)
    return text


def _loses_normative_qualification(text: str, facts: list[SourceFact]) -> bool:
    """Conservative RU qualification-loss detector, never semantic acceptance.

    Bind a closed adjective family to its corresponding following source object.
    Repeated same-stem objects retain source occurrence order, so moving a
    qualifier to another object cannot justify dropping it here. Unsupported
    paraphrases may fall back to complete source wording, not invented prose.
    """
    qualifier = re.compile(
        r"(?P<kind>действующ|утвержденн|разрешенн|согласованн|уполномоченн)"
        r"(?:ый|ий|ых|их|ого|его|ым|им|ыми|ими|ую|юю|ой|ей|ые|ие|ая|яя|ое|ее)"
    )

    def words(value: str) -> list[str]:
        return re.findall(r"[а-я]+(?:-[а-я]+)*", value.casefold().replace("ё", "е"))

    raw_candidates = [words(match.group(0)) for match in _TEACHING_SENTENCE_RE.finditer(text)]
    raw_source_tokens = [
        token
        for fact in facts
        for token in words(fact.value)
    ]
    raw_candidate_tokens = [token for sentence in raw_candidates for token in sentence]
    candidates = [
        _orthographic_negation_view(sentence, raw_source_tokens)
        for sentence in raw_candidates
    ]
    candidate_occurrences: dict[str, list[tuple[list[str], int]]] = defaultdict(list)
    legal_basis = re.compile(r"\bв силу действующих нормативных правовых и иных актов\b", re.IGNORECASE)
    teaching_sentences = [match.group(0) for match in _TEACHING_SENTENCE_RE.finditer(text)]
    prior_source_tokens: list[str] = []
    for fact in facts:
        for source_sentence in _TEACHING_SENTENCE_RE.finditer(fact.value):
            if legal_basis.search(source_sentence.group(0)):
                anchors = _grounding_tokens(legal_basis.sub("", source_sentence.group(0)))
                if not any(legal_basis.search(candidate) and anchors
                           and len(anchors & _grounding_tokens(candidate)) / len(anchors) >= 0.65
                           for candidate in teaching_sentences):
                    return True
        tokens = _orthographic_negation_view(words(fact.value), raw_candidate_tokens)
        for index, token in enumerate(tokens):
            first = qualifier.fullmatch(token)
            if first is None:
                continue
            required = {first["kind"]}
            end = index + 1
            while end + 1 < len(tokens) and tokens[end] == "и":
                following = qualifier.fullmatch(tokens[end + 1])
                if following is None:
                    break
                required.add(following["kind"])
                end += 2
            if end >= len(tokens) or len(tokens[end]) < 4:
                continue
            object_stem = tokens[end][:6]
            if object_stem not in candidate_occurrences:
                candidate_occurrences[object_stem].extend(
                    (sentence, position)
                    for sentence in candidates
                    for position, word in enumerate(sentence)
                    if word.startswith(object_stem)
                )
            source_ordinal = sum(
                word.startswith(object_stem)
                for word in (*prior_source_tokens, *tokens[:end + 1])
            ) - 1
            occurrences = candidate_occurrences[object_stem]
            if source_ordinal >= len(occurrences):
                return True
            sentence, position = occurrences[source_ordinal]
            present: set[str] = set()
            preceding = position - 1
            while preceding >= 0:
                match = qualifier.fullmatch(sentence[preceding])
                if match is not None:
                    present.add(match["kind"])
                elif sentence[preceding] != "и":
                    break
                preceding -= 1
            if not required <= present:
                return True
        prior_source_tokens.extend(tokens)
    return False


def _grounded_teaching_text(text: str, facts: list[SourceFact]) -> str:
    """Keep supported prose and restore every omitted sentence of cited facts."""
    text = _restore_unresolved_source_referents(text, facts)
    # A writer can reintroduce a plain heading ahead of the actual source rule.
    # Remove only an exact repeated subject followed by the verified first
    # source clause; never trim an arbitrary short/action-bearing prefix.
    for fact in facts:
        prefix = f"{_clean_output_text(fact.subject)} "
        first_clause = re.split(r"[.!?]", _clean_output_text(fact.value), maxsplit=1)[0]
        if len(first_clause) >= 12 and text.startswith(prefix):
            remainder = text[len(prefix):]
            if remainder.startswith(first_clause):
                text = remainder
                break
    sources = [
        " ".join((fact.subject, fact.attribute, _clean_output_text(fact.value)))
        for fact in facts
    ]
    normalized_sources = [" ".join(source.casefold().replace("ё", "е").split())
                          for source in sources]
    source_tokens = [_grounding_tokens(source) for source in sources]
    sentences = [match.group(0).strip() for match in _TEACHING_SENTENCE_RE.finditer(text)
                 if match.group(0).strip()]
    grounded: list[str] = []
    for sentence in sentences:
        normalized = " ".join(sentence.casefold().replace("ё", "е").split())
        tokens = _grounding_tokens(sentence)
        exact = any(normalized in source or source in normalized for source in normalized_sources)
        lexical = max(
            ((len(tokens & available) / len(tokens)) if tokens else 0.0)
            for available in source_tokens
        )
        if exact or lexical >= 0.65:
            grounded.append(sentence)
    if grounded:
        deduplicated: list[str] = []
        seen_sentences: set[str] = set()
        seen_token_sets: list[set[str]] = []
        for sentence in grounded:
            normalized = " ".join(sentence.casefold().replace("ё", "е").split())
            if normalized in seen_sentences or _is_covered_sentence(sentence, seen_token_sets):
                continue
            seen_sentences.add(normalized)
            seen_token_sets.append(_redundancy_tokens(sentence))
            deduplicated.append(sentence)
        grounded = deduplicated
        # Citing one fact id is not enough when the provider kept only one
        # sentence of a multi-sentence rule. Preserve supported paraphrases,
        # then append only source sentences whose meaning is still absent.
        # OCR-tainted facts remain excluded from this restoration path.
        if not any(contains_visible_artifact(_clean_output_text(fact.value)) for fact in facts):
            restored_any = False
            grounded_normalized = [
                " ".join(sentence.casefold().replace("ё", "е").split())
                for sentence in grounded
            ]
            grounded_tokens = [_grounding_tokens(sentence) for sentence in grounded]
            combined_grounded_tokens = set().union(*grounded_tokens) if grounded_tokens else set()
            grounded_redundancy_tokens = [
                _redundancy_tokens(sentence) for sentence in grounded
            ]
            for fact in facts:
                source_sentences = [
                    match.group(0).strip()
                    for match in _TEACHING_SENTENCE_RE.finditer(_clean_output_text(fact.value))
                    if match.group(0).strip()
                    and any(character.isalpha() for character in match.group(0))
                ]
                for source_sentence in source_sentences:
                    normalized = " ".join(
                        source_sentence.casefold().replace("ё", "е").split()
                    )
                    tokens = _grounding_tokens(source_sentence)
                    semantic_threshold = 0.65 if len(source_sentences) == 1 else 0.9
                    covered = any(
                        normalized in candidate or candidate in normalized
                        for candidate in grounded_normalized
                    ) or any(
                        tokens and len(tokens & available) / len(tokens) >= semantic_threshold
                        for available in grounded_tokens
                    ) or any(
                        tokens
                        and available
                        and len(tokens & available) / min(len(tokens), len(available)) >= 0.85
                        and len(available) / len(tokens) >= 0.45
                        for available in grounded_tokens
                    ) or (
                        tokens
                        and len(tokens & combined_grounded_tokens) / len(tokens) >= 0.65
                    ) or _is_covered_sentence(
                        source_sentence, grounded_redundancy_tokens
                    )
                    if covered:
                        continue
                    restored_any = True
                    restored = _clean_output_text(
                        neutralize_unprofessional_source_language(source_sentence)
                    )
                    grounded.append(restored)
                    grounded_normalized.append(normalized)
                    grounded_tokens.append(tokens)
                    grounded_redundancy_tokens.append(
                        _redundancy_tokens(source_sentence)
                    )
            if (
                restored_any
                and all(not is_tabular_locator(fact.source_locator) for fact in facts)
                and not any(contains_internal_generation_instruction(fact.value) for fact in facts)
                and sum(len(re.findall(r"\w+", fact.value)) for fact in facts) <= 100
            ):
                # A short rule mixed with a partial paraphrase reads as the
                # same instruction twice. Prefer its complete source wording
                # once; long/OCR/table sources keep their existing path.
                return " ".join(
                    _clean_output_text(
                        neutralize_unprofessional_source_language(fact.value)
                    )
                    for fact in facts
                )
        return " ".join(grounded)
    if any(contains_visible_artifact(_clean_output_text(fact.value)) for fact in facts):
        # A validated clean omission notice is safer than re-exposing unreadable
        # source glyphs or guessing the missing value.
        return text
    # Do not splice several bare table-cell values into an unsupported model
    # block. The caller can render uncovered facts separately with their labels.
    return ""


def _tabular_block_covers_labelled_facts(text: str, facts: list[SourceFact]) -> bool:
    """A cited workbook cell needs its own attribute beside its value.

    Citing five cell IDs while listing five naked values is not a lesson.
    When the provider omits even one label, the source-owned fallback renders
    those cells individually instead of treating the whole block as covered.
    """
    clauses = [clause.strip() for clause in re.split(r"[.!?;,]+", text) if clause.strip()]
    for fact in facts:
        # A spreadsheet cell may itself contain a complete prose rule. This
        # guard is only for short atomic values such as "МДФ" or "24 месяца";
        # long/sentential cells keep the normal grounding and dedup path.
        clean_value = _clean_output_text(fact.value)
        if len(re.findall(r"\w+", clean_value)) > 12 or re.search(r"[.!?;]", clean_value):
            # A document table row carries its own rule scope (e.g. category).
            # Unlike a worksheet lesson's shared product subject, that scope
            # cannot be inferred from the lesson title or a neighbouring row.
            if any(field.startswith("table=") for field in fact.source_locator.split(";")):
                subject = " ".join(_clean_output_text(fact.subject).casefold().split())
                normalized_text = " ".join(text.casefold().split())
                if subject and not re.search(rf"(?<!\w){re.escape(subject)}(?!\w)", normalized_text):
                    return False
            continue
        value = " ".join(_clean_output_text(fact.value).casefold().split())
        attribute_tokens = _grounding_tokens(fact.attribute)
        if not value or not attribute_tokens:
            return False
        if not any(
            value in " ".join(clause.casefold().split())
            and bool(attribute_tokens & _grounding_tokens(clause))
            for clause in clauses
        ):
            return False
    return True


def _tabular_source_row(fact: SourceFact) -> int | None:
    if not is_tabular_locator(fact.source_locator):
        return None
    matched = re.search(r"(?:^|;)row=(\d+)(?:;|$)", fact.source_locator)
    return int(matched.group(1)) if matched else None


class ProviderBackedEvidenceEngine:
    """Use Qwen retrieval and DeepSeek prose without surrendering fact ownership."""

    def __init__(
        self,
        *,
        embeddings: EmbeddingProvider,
        chat: ChatJsonProvider,
        max_realizer_attempts: int = 2,
    ) -> None:
        if max_realizer_attempts < 1:
            raise ValueError("max_realizer_attempts must be positive")
        self._embeddings = embeddings
        self._chat = chat
        self._max_realizer_attempts = max_realizer_attempts
        self._evidence = EvidenceCourseEngine()
        self._xlsx = XlsxEvidenceAdapter()

    def generate(
        self,
        source_path: Path,
        *,
        intent: CourseIntent | None = None,
        simulation_seed: int = 0,
    ) -> ProviderBackedResult:
        if source_path.suffix.casefold() != ".xlsx":
            raise ValueError(f"Unsupported local source type: {source_path.suffix}")
        return self.generate_from_document(
            self._xlsx.read(source_path),
            intent=intent,
            simulation_seed=simulation_seed,
        )

    def generate_from_document(
        self,
        document: SourceDocument,
        *,
        intent: CourseIntent | None = None,
        simulation_seed: int = 0,
    ) -> ProviderBackedResult:
        started = perf_counter()
        evidence_result = self._evidence.generate_from_document(
            document,
            intent=intent,
            simulation_seed=simulation_seed,
        )
        evidence_seconds = perf_counter() - started
        facts = list(evidence_result.admitted_facts)
        facts_by_id = {fact.fact_id: fact for fact in facts}
        lesson_by_id = {lesson.lesson_id: lesson for lesson in evidence_result.course.lessons}
        questions_by_lesson: dict[str, list[QuestionDraft]] = defaultdict(list)
        for question in evidence_result.assessment.questions:
            questions_by_lesson[question.lesson_id].append(question)

        embedding_started = perf_counter()
        embedding_model = ""
        embedding_dimension = 0
        embedding_degraded = False
        embedding_error = ""
        retrieval: list[RetrievalMeasurement] = []
        try:
            document_batch = self._embeddings.embed([fact.value for fact in facts])
            document_vectors = tuple(_normalize(vector) for vector in document_batch.vectors)
            if len(document_vectors) != len(facts):
                raise ProviderCallError("document embedding count does not match admitted facts")
            query_texts = [
                QWEN_QUERY_PREFIX
                + " ".join(
                    [
                        plan.title,
                        plan.objective,
                        *sorted({facts_by_id[fact_id].attribute for fact_id in plan.fact_ids}),
                    ]
                )
                for plan in evidence_result.evidence_plan
            ]
            query_batch = self._embeddings.embed(query_texts)
            query_vectors = tuple(_normalize(vector) for vector in query_batch.vectors)
            if len(query_vectors) != len(evidence_result.evidence_plan):
                raise ProviderCallError("query embedding count does not match lesson plan")
            retrieval = self._measure_retrieval(
                facts=facts,
                document_vectors=document_vectors,
                query_vectors=query_vectors,
                plans=evidence_result.evidence_plan,
            )
            embedding_model = document_batch.model
            embedding_dimension = len(document_vectors[0]) if document_vectors else 0
        except ProviderCallError as exc:
            embedding_degraded = True
            embedding_error = type(exc).__name__
        embedding_seconds = perf_counter() - embedding_started

        realized_lessons: list[LessonDraft] = []
        realized_questions: list[QuestionDraft] = []
        grounded_blocks: list[GroundedBlock] = []
        validation_errors: list[str] = []
        fallback_count = 0
        deterministic_fallback_lesson_ids: list[str] = []
        prompt_tokens = 0
        completion_tokens = 0
        chat_attempt_count = 0
        chat_model = ""
        realization_started = perf_counter()
        for plan in evidence_result.evidence_plan:
            base_lesson = lesson_by_id[plan.lesson_id]
            seeds = questions_by_lesson.get(plan.lesson_id, [])
            request = self._realizer_request(plan, facts_by_id, seeds, intent or CourseIntent())
            accepted: tuple[LessonDraft, list[QuestionDraft], list[GroundedBlock]] | None = None
            last_error = ""
            for _ in range(self._max_realizer_attempts):
                try:
                    chat_attempt_count += 1
                    completion = self._chat.complete_json(request)
                    chat_model = completion.model
                    prompt_tokens += completion.prompt_tokens
                    completion_tokens += completion.completion_tokens
                    accepted = self._validate_and_render(
                        completion.payload,
                        base_lesson=base_lesson,
                        plan_fact_ids=set(plan.fact_ids),
                        facts_by_id=facts_by_id,
                        seeds=seeds,
                    )
                    break
                except (ProviderCallError, ValueError, KeyError, TypeError) as exc:
                    last_error = f"{type(exc).__name__}: {str(exc)[:180]}"
                    request["validation_feedback"] = last_error
            if accepted is None:
                fallback_count += 1
                deterministic_fallback_lesson_ids.append(plan.lesson_id)
                validation_errors.append(f"{plan.lesson_id}: {last_error or 'provider unavailable'}")
                fallback_lesson = LessonDraft(
                    lesson_id=base_lesson.lesson_id,
                    module_title=base_lesson.module_title,
                    title=neutralize_unprofessional_source_language(base_lesson.title),
                    objective=neutralize_unprofessional_source_language(base_lesson.objective),
                    content=neutralize_unprofessional_source_language(base_lesson.content),
                    fact_ids=base_lesson.fact_ids,
                    supporting_fact_ids=base_lesson.supporting_fact_ids,
                    duration_minutes=base_lesson.duration_minutes,
                )
                realized_lessons.append(fallback_lesson)
                realized_questions.extend(seeds)
                grounded_blocks.append(
                    GroundedBlock(
                        lesson_id=fallback_lesson.lesson_id,
                        heading="Детерминированный черновик",
                        text=fallback_lesson.content,
                        fact_ids=fallback_lesson.fact_ids,
                    )
                )
            else:
                lesson, questions, lesson_blocks = accepted
                realized_lessons.append(lesson)
                realized_questions.extend(questions)
                grounded_blocks.extend(lesson_blocks)
        realization_seconds = perf_counter() - realization_started

        realized_questions = filter_acceptable_questions(realized_questions)
        realized_course = CourseDraft(
            title=evidence_result.course.title,
            description=evidence_result.course.description,
            lessons=tuple(realized_lessons),
        )
        realized_assessment = AssessmentDraft(questions=tuple(realized_questions))
        publishability = evaluate_publishability(
            course=realized_course,
            assessment=realized_assessment,
            blocks=tuple(grounded_blocks),
            planned_fact_ids={fact.fact_id for fact in evidence_result.admitted_facts},
            provider_fallback_count=fallback_count,
        )
        if evidence_result.evaluation.uncertain_fact_count:
            publishability = replace(
                publishability, publishable=False,
                reasons=tuple(dict.fromkeys((*publishability.reasons, "incomplete_source_admission"))),
            )

        return ProviderBackedResult(
            evidence_result=evidence_result,
            realized_course=realized_course,
            realized_assessment=realized_assessment,
            embedding_model=embedding_model,
            embedding_dimension=embedding_dimension,
            embedding_degraded=embedding_degraded,
            embedding_error=embedding_error,
            chat_model=chat_model,
            retrieval=tuple(retrieval),
            grounded_blocks=tuple(grounded_blocks),
            publishability=publishability,
            provider_fallback_count=fallback_count,
            deterministic_fallback_count=fallback_count,
            deterministic_fallback_lesson_ids=tuple(deterministic_fallback_lesson_ids),
            validation_errors=tuple(validation_errors),
            chat_attempt_count=chat_attempt_count,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            timings=(
                StageTiming(stage="evidence_plan", seconds=evidence_seconds),
                StageTiming(stage="qwen_embeddings", seconds=embedding_seconds),
                StageTiming(stage="deepseek_realization", seconds=realization_seconds),
            ),
        )

    @staticmethod
    def _measure_retrieval(
        *,
        facts: list[SourceFact],
        document_vectors: tuple[tuple[float, ...], ...],
        query_vectors: tuple[tuple[float, ...], ...],
        plans: tuple[LessonEvidence, ...],
    ) -> list[RetrievalMeasurement]:
        measurements: list[RetrievalMeasurement] = []
        for plan, query in zip(plans, query_vectors, strict=True):
            ranked = sorted(
                zip(facts, document_vectors, strict=True),
                key=lambda item: sum(left * right for left, right in zip(query, item[1], strict=True)),
                reverse=True,
            )
            k = min(len(ranked), max(8, len(plan.fact_ids) * 2))
            top_ids = tuple(fact.fact_id for fact, _ in ranked[:k])
            expected = set(plan.fact_ids)
            recall = len(expected.intersection(top_ids)) / len(expected) if expected else 1.0
            measurements.append(
                RetrievalMeasurement(
                    lesson_id=plan.lesson_id,
                    recall_at_k=recall,
                    k=k,
                    top_fact_ids=top_ids,
                )
            )
        return measurements

    @staticmethod
    def _realizer_request(
        plan: LessonEvidence,
        facts_by_id: dict[str, SourceFact],
        seeds: list[QuestionDraft],
        intent: CourseIntent,
    ) -> dict[str, Any]:
        return {
            "lesson_title": plan.title,
            "objective": plan.objective,
            "course_intent": {
                "purpose": intent.purpose,
                "audience": intent.audience,
                "emphasis": list(intent.emphasis),
            },
            "facts": [
                {
                    "fact_id": fact_id,
                    "subject": facts_by_id[fact_id].subject,
                    "attribute": facts_by_id[fact_id].attribute,
                    "value": _clean_output_text(facts_by_id[fact_id].value),
                    "source_locator": facts_by_id[fact_id].source_locator,
                }
                for fact_id in plan.fact_ids
            ],
            "question_seeds": [
                {
                    "fact_id": seed.fact_id,
                    "prompt": seed.prompt,
                    "options": list(seed.options),
                    "correct_answer": seed.correct_answer,
                }
                for seed in seeds
            ],
        }

    @staticmethod
    def _validate_and_render(
        payload: dict[str, Any],
        *,
        base_lesson: LessonDraft,
        plan_fact_ids: set[str],
        facts_by_id: dict[str, SourceFact],
        seeds: list[QuestionDraft],
        surface_review: tuple[PreparedLessonSurfaceReview, LessonSurfaceReviewResult | None] | None = None,
    ) -> tuple[LessonDraft, list[QuestionDraft], list[GroundedBlock]]:
        blocks = payload.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            raise ValueError("blocks must be a non-empty list")
        reviewed_indices: set[int] = set()
        reviewed_sources: dict[int, tuple[str, ...]] = {}
        partial_preserved_fact_ids: frozenset[str] = frozenset()
        if surface_review is not None:
            prepared, receipt = surface_review
            render_scope = lesson_surface_render_scope(
                prepared=prepared, result=receipt, base_lesson=base_lesson,
                plan_fact_ids=plan_fact_ids, facts_by_id=facts_by_id, blocks=blocks)
            # The receipt is not trusted merely because a caller supplies it:
            # all source and final-visible candidate bytes are re-bound here.
            reviewed_sources.update(render_scope.reviewed_sources)
            reviewed_indices.update(reviewed_sources)
            partial_preserved_fact_ids = render_scope.partial_preserved_fact_ids
        rendered: list[str] = []
        grounded_blocks: list[GroundedBlock] = []
        rendered_fact_ids: set[str] = set()
        # Local object provenance survives sorting, never value equality with
        # a separately reconstructed fallback or coalesced block.
        reviewed_body_ids: set[int] = set()
        seen_blocks: set[tuple[str, tuple[str, ...]]] = set()
        seen_lesson_sentences: set[str] = set()
        seen_lesson_token_sets: list[set[str]] = []
        prior_sentences_by_fact: dict[str, list[str]] = defaultdict(list)
        prior_tokens_by_fact: dict[str, set[str]] = defaultdict(set)
        fallback_headings: dict[str, str] = {}
        for block_index, block in enumerate(blocks):
            if not isinstance(block, dict):
                raise ValueError("block must be an object")
            raw_heading = _clean_output_text(str(block.get("heading") or ""))
            heading = neutralize_unprofessional_source_language(
                raw_heading
            )
            text = _clean_learner_body(str(block.get("text") or ""))
            fact_ids = {str(value) for value in block.get("fact_ids") or []}
            if not heading or not text or not fact_ids:
                raise ValueError("block heading, text and fact_ids are required")
            if not fact_ids <= plan_fact_ids:
                raise ValueError("block cites a fact outside the lesson plan")
            cited_facts = [facts_by_id[fact_id] for fact_id in fact_ids]
            # Lazy import keeps the evidence-engine package initializer out of
            # the meaning/source-literal import cycle. This is a negative veto,
            # never permission to infer a replacement rule.
            from app.modules.ai.assessment_meaning import source_coordination_issue

            independently_reviewed = block_index in reviewed_indices
            if independently_reviewed:
                # Fresh block custody proves display eligibility. Keep the full
                # audited context as provenance without asserting its coverage.
                fact_ids = set(reviewed_sources[block_index])
                cited_facts = [facts_by_id[fid] for fid in reviewed_sources[block_index]]
            qualification_lost = (not independently_reviewed and _loses_normative_qualification(text, cited_facts))
            if qualification_lost and any(
                contains_visible_artifact(_clean_output_text(fact.value))
                or contains_internal_generation_instruction(fact.value) for fact in cited_facts
            ):
                # Neither a broadened paraphrase nor copying a tainted source
                # is safe evidence for this qualification. Keep the gate closed.
                raise ValueError("source qualification requires clean evidence")
            structured_source = (not independently_reviewed and (surface_review is not None or any(
                _structured_source_value(fact.value) for fact in cited_facts)))
            changes_negation = not independently_reviewed and _changes_source_word_negation(text, cited_facts)
            coordination_issue = None if independently_reviewed else source_coordination_issue(
                " ".join(fact.value for fact in cited_facts), text
            )
            if structured_source or changes_negation or qualification_lost or coordination_issue:
                if (
                    surface_review is None and (structured_source or changes_negation)
                    and _safe_fallback_navigation_heading(raw_heading, cited_facts)
                ):
                    for fact_id in fact_ids:
                        fallback_headings.setdefault(fact_id, heading)
                # Render uncovered facts below with their normal labels/order,
                # rather than keep a broadened qualification or invert a word.
                continue
            if (any(is_tabular_locator(fact.source_locator) for fact in cited_facts)
                    and not all(is_tabular_locator(fact.source_locator) for fact in cited_facts)):
                # A prose/table mixture can restore bare cell values without
                # their row and column labels. Retain the valid homogeneous
                # blocks; render these uncovered facts with attribution below.
                continue
            if contains_visible_artifact(heading) or contains_visible_artifact(text):
                raise ValueError("block exposes unresolved OCR artifacts")
            if has_unprofessional_learner_language(heading) or has_unprofessional_learner_language(text):
                raise ValueError("block contains blocked learner-visible language")
            cited_source = " ".join(facts_by_id[fact_id].value for fact_id in fact_ids)
            if (
                contains_internal_generation_instruction(text)
                and not contains_internal_generation_instruction(cited_source)
            ):
                raise ValueError("block exposes internal generation instructions")
            allowed_numbers = set().union(
                *(
                    _numbers(
                        " ".join(
                            (
                                facts_by_id[fact_id].subject,
                                facts_by_id[fact_id].attribute,
                                facts_by_id[fact_id].value,
                                facts_by_id[fact_id].source_locator,
                            )
                        )
                    )
                    for fact_id in fact_ids
                )
            )
            unexpected_numbers = _numbers(text + " " + heading if independently_reviewed else text) - allowed_numbers
            if unexpected_numbers:
                raise ValueError(
                    "block introduces a number absent from cited facts: "
                    f"{sorted(unexpected_numbers)}"
                )
            if independently_reviewed:
                # Whole-fact aggregate proof permits several learner blocks to
                # explain one list. Do not reset each partial block to the whole
                # source or erase independently reviewed sentences by overlap.
                grounded_blocks.append(GroundedBlock(
                    lesson_id=base_lesson.lesson_id, heading=heading, text=text,
                    fact_ids=tuple(sorted(fact_ids))))
                reviewed_body_ids.add(id(grounded_blocks[-1]))
                rendered_fact_ids.update(fact_ids)
                continue
            text = _grounded_teaching_text(
                text,
                [facts_by_id[fact_id] for fact_id in sorted(fact_ids)],
            )
            cited_facts = [facts_by_id[fact_id] for fact_id in sorted(fact_ids)]
            if (
                text
                and all(is_tabular_locator(fact.source_locator) for fact in cited_facts)
                and not _tabular_block_covers_labelled_facts(text, cited_facts)
            ):
                # Every cell will be rendered later with subject and label.
                # A model block that cites all cells but teaches only a subset
                # must not suppress that fallback by claiming their coverage.
                continue
            if not text:
                # Unsupported model prose contributes no coverage. Facts still
                # absent after all blocks are rendered below with attribution.
                continue
            fresh_sentences: list[str] = []
            for match in _TEACHING_SENTENCE_RE.finditer(text):
                sentence = match.group(0).strip()
                if not sentence:
                    continue
                normalized_sentence = " ".join(
                    sentence.casefold().replace("ё", "е").split()
                )
                if (
                    normalized_sentence in seen_lesson_sentences
                    or _is_covered_sentence(sentence, seen_lesson_token_sets)
                ):
                    continue
                tail = " ".join(
                    re.sub(
                        r"[ .;:]+$", "",
                        sentence.rsplit(",", 1)[-1].casefold().replace("ё", "е"),
                    ).split()
                )
                sentence_tokens = _redundancy_tokens(sentence)
                if (
                    "," in sentence
                    and len(_redundancy_tokens(tail)) >= 2
                    and any(
                        sentence_tokens <= prior_tokens_by_fact[fact_id]
                        and any(
                            tail in earlier for earlier in prior_sentences_by_fact[fact_id]
                        )
                        for fact_id in fact_ids
                    )
                ):
                    # The clause after the condition was already taught in
                    # full, and this restatement adds no source vocabulary.
                    continue
                seen_lesson_sentences.add(normalized_sentence)
                seen_lesson_token_sets.append(sentence_tokens)
                for fact_id in fact_ids:
                    prior_sentences_by_fact[fact_id].append(normalized_sentence)
                    prior_tokens_by_fact[fact_id].update(sentence_tokens)
                fresh_sentences.append(sentence)
            text = _clean_output_text(" ".join(fresh_sentences))
            if (
                all(is_tabular_locator(fact.source_locator) for fact in cited_facts)
                and not _tabular_block_covers_labelled_facts(text, cited_facts)
            ):
                # Deduplication can erase a different row's numeric value or
                # identical cell text. Validate the final visible text again;
                # cited IDs alone cannot suppress the labelled-cell fallback.
                continue
            if not text:
                # The same grounded sentence was already rendered by an
                # earlier block; only this duplicate can claim coverage.
                rendered_fact_ids.update(fact_ids)
                continue
            block_key = (
                " ".join(text.casefold().replace("ё", "е").split()),
                tuple(sorted(fact_ids)),
            )
            if block_key in seen_blocks:
                rendered_fact_ids.update(fact_ids)
                continue
            seen_blocks.add(block_key)
            rendered_fact_ids.update(fact_ids)
            rendered.extend([f"### {heading}", "", text, ""])
            grounded_blocks.append(
                GroundedBlock(
                    lesson_id=base_lesson.lesson_id,
                    heading=heading,
                    text=text,
                    fact_ids=tuple(sorted(fact_ids)),
                )
            )
        # Keep valid provider-authored teaching blocks, but do not discard an
        # entire lesson merely because the model omitted one of many atomic
        # source facts. Missing facts are rendered verbatim and remain cited,
        # so the server still guarantees complete, source-only coverage.
        for fact_id in base_lesson.fact_ids:
            if fact_id not in plan_fact_ids or fact_id in rendered_fact_ids or fact_id in partial_preserved_fact_ids:
                continue
            fact = facts_by_id[fact_id]
            text = _display_source_value(
                neutralize_unprofessional_source_language(fact.value.strip())
            )
            if contains_visible_artifact(text):
                raise ValueError("fallback fact exposes unresolved OCR artifacts")
            if is_tabular_locator(fact.source_locator) and (
                not re.search(r"[.!?]$", text)
                or any(field.startswith("table=") for field in fact.source_locator.split(";"))
            ):
                # A workbook cell alone is not a teachable statement. Preserve
                # its exact subject, column label and value without inventing
                # a grammatical relationship absent from the source.
                subject = _clean_output_text(fact.subject)
                attribute = _clean_output_text(fact.attribute)
                terminal = "" if re.search(r"[.!?]$", text) else "."
                text = f"{subject} — {attribute}: {text}{terminal}"
            heading = fallback_headings.get(fact_id) or _source_fallback_heading(fact)
            rendered.extend([f"### {heading}", "", text, ""])
            grounded_blocks.append(
                GroundedBlock(
                    lesson_id=base_lesson.lesson_id,
                    heading=heading,
                    text=text,
                    fact_ids=(fact_id,),
                )
            )
            rendered_fact_ids.add(fact_id)
        if rendered_fact_ids | set(partial_preserved_fact_ids) != plan_fact_ids:
            raise ValueError("realizer did not cover every planned fact")

        grounded_blocks = _split_nonadjacent_grounded_blocks(
            grounded_blocks,
            source_fact_ids=base_lesson.fact_ids,
            plan_fact_ids=plan_fact_ids,
            facts_by_id=facts_by_id,
        )
        source_positions = {fact_id: index for index, fact_id in enumerate(base_lesson.fact_ids)}
        grounded_blocks.sort(key=lambda block: min(source_positions[fact_id] for fact_id in block.fact_ids))

        source_rows = {
            fact_id: _tabular_source_row(facts_by_id[fact_id])
            for fact_id in plan_fact_ids
        }
        if source_rows and all(row is not None for row in source_rows.values()):
            # A model may mention warranty before purpose, and the plan may
            # rank facts by assessment value. Present a workbook lesson in
            # the source's row order regardless of either incidental order.
            table_scopes: dict[str, tuple[str, ...]] = {}
            table_positions: dict[tuple[str, ...], int] = {}
            for fact_id in base_lesson.fact_ids:
                locator = dict(parse_qsl(facts_by_id[fact_id].source_locator.replace(";", "&")))
                scope = tuple(locator.get(key, "") for key in (
                    "doc_id", "source_revision", "section", "sheet", "table",
                ))
                table_scopes[fact_id] = scope
                table_positions.setdefault(scope, source_positions[fact_id])
            grounded_blocks.sort(key=lambda block: min(
                (table_positions[table_scopes[fact_id]], source_rows[fact_id] or 0)
                for fact_id in block.fact_ids
            ))
        ordered_procedure = _source_ordered_procedure_blocks(
            base_lesson,
            [facts_by_id[fact_id] for fact_id in base_lesson.fact_ids
             if fact_id in plan_fact_ids],
        ) if (set(base_lesson.fact_ids) == plan_fact_ids
              and not any(id(block) in reviewed_body_ids for block in grounded_blocks)) else None
        if ordered_procedure:
            grounded_blocks = ordered_procedure
        else:
            preserved: list[GroundedBlock] = []
            unreviewed_run: list[GroundedBlock] = []
            for block in grounded_blocks:
                if id(block) not in reviewed_body_ids:
                    unreviewed_run.append(block)
                    continue
                preserved.extend(coalesce_grounded_blocks(unreviewed_run, facts_by_id))
                unreviewed_run = []
                preserved.append(block)
            preserved.extend(coalesce_grounded_blocks(unreviewed_run, facts_by_id))
            grounded_blocks = preserved
        rendered = [
            part
            for block in grounded_blocks
            for part in (f"### {block.heading}", "", (
                block.text if id(block) in reviewed_body_ids
                else _readable_source_text(block.text)), "")
        ]

        seed_by_fact = {seed.fact_id: seed for seed in seeds}
        raw_questions = payload.get("questions")
        if not isinstance(raw_questions, list):
            raw_questions = []
        rewritten_by_fact: dict[str, QuestionDraft] = {}
        seen_fact_ids: set[str] = set()
        for raw in raw_questions:
            if not isinstance(raw, dict):
                continue
            cited = tuple(str(value) for value in raw.get("fact_ids") or [])
            if len(cited) != 1 or cited[0] not in seed_by_fact or cited[0] in seen_fact_ids:
                continue
            seed = seed_by_fact[cited[0]]
            options = seed.options
            correct_answer = seed.correct_answer
            prompt = neutralize_unprofessional_source_language(
                _clean_output_text(str(raw.get("prompt") or ""))
            )
            explanation = neutralize_unprofessional_source_language(
                _clean_output_text(str(raw.get("explanation") or ""))
            )
            if not prompt or not explanation:
                continue
            if is_generic_question(prompt):
                continue
            if contains_visible_artifact(prompt) or contains_visible_artifact(explanation):
                continue
            if has_unprofessional_learner_language(prompt) or has_unprofessional_learner_language(explanation):
                continue
            fact = facts_by_id[seed.fact_id]
            allowed_numbers = set().union(
                *(
                    _numbers(value)
                    for value in (
                        *seed.options,
                        seed.prompt,
                        fact.subject,
                        fact.attribute,
                        fact.value,
                        fact.source_locator,
                    )
                )
            )
            unexpected_numbers = (_numbers(prompt) | _numbers(explanation)) - allowed_numbers
            if unexpected_numbers:
                continue
            rewritten_by_fact[seed.fact_id] = QuestionDraft(
                question_id=seed.question_id,
                lesson_id=seed.lesson_id,
                kind=seed.kind,
                # A specific deterministic seed already names the tested
                # attribute and is safer than an unconstrained paraphrase.
                # Only generic source-membership seeds require model rewriting.
                prompt=(prompt if is_generic_question(seed.prompt) else seed.prompt),
                options=options,
                correct_answer=correct_answer,
                explanation=explanation,
                fact_id=seed.fact_id,
                distractor_fact_ids=seed.distractor_fact_ids,
            )
            seen_fact_ids.add(seed.fact_id)
        questions = [rewritten_by_fact.get(seed.fact_id, seed) for seed in seeds]
        word_count = len(re.findall(r"\w+", " ".join(rendered)))
        if word_count > 650:
            raise ValueError("lesson exceeds the 650-word publishability ceiling")
        title = neutralize_unprofessional_source_language(
            _clean_output_text(str(payload.get("title") or base_lesson.title)).lstrip("# ")
        )
        objective = neutralize_unprofessional_source_language(
            _clean_output_text(str(payload.get("objective") or base_lesson.objective))
        )
        if surface_review is not None or (plan_fact_ids and all(
            is_tabular_locator(facts_by_id[fact_id].source_locator)
            for fact_id in plan_fact_ids
        )):
            # The plan owns the row subject. A model must not turn a collection
            # into one item mentioned only in a supporting catalog sheet; both
            # fields feed the later assessment author as factual context.
            title = base_lesson.title
            objective = base_lesson.objective
        if not is_acceptable_title(title):
            raise ValueError("lesson title is not a concise complete nominal phrase")
        if has_unprofessional_learner_language(title) or has_unprofessional_learner_language(objective):
            raise ValueError("lesson metadata contains blocked learner-visible language")
        lesson = LessonDraft(
            lesson_id=base_lesson.lesson_id,
            module_title=base_lesson.module_title,
            title=title,
            objective=objective,
            content="\n".join(rendered).strip(),
            fact_ids=base_lesson.fact_ids,
            supporting_fact_ids=base_lesson.supporting_fact_ids,
            duration_minutes=max(2, math.ceil(word_count / 130)),
        )
        return lesson, questions, grounded_blocks


@dataclass(frozen=True, slots=True)
class SupportedGroundedBlock(GroundedBlock):
    """Opt-in provenance; `fact_ids` remain the only owned coverage IDs."""

    supporting_fact_ids: tuple[str, ...]
    support_request_sha256: str
    support_context_sha256: str


@dataclass(frozen=True, slots=True)
class SupportedSurfaceRender:
    lesson: LessonDraft
    blocks: tuple[SupportedGroundedBlock, ...]
    requires_review: bool = True
    publishable: bool = False


async def render_supported_surface(*, assessor: Any, base_lesson: LessonDraft,
                                   facts_by_id: dict[str, SourceFact], blocks: list[dict[str, Any]],
                                   prepared: Any, response: Any, checkpoint: Any) -> SupportedSurfaceRender:
    """Render a source-reviewed sidecar without crediting supporting facts.

    This is a draft-only contract. The caller still owns provider provenance,
    independent language review and every later publication gate.
    """
    from app.modules.ai.lesson_surface_support import (
        PreparedSupportSurface,
        SupportSurfaceResponse,
        prepare_support_surface,
        support_response_valid,
    )

    if not isinstance(prepared, PreparedSupportSurface) or not isinstance(response, SupportSurfaceResponse):
        raise ValueError("supported_surface_invalid_custody")

    async def revalidate() -> None:
        context = await assessor.semantic_author_context(base_lesson, facts_by_id)
        if context is None:
            raise ValueError("supported_surface_invalid_custody")
        await assessor.validate_semantic_author_citations(base_lesson, facts_by_id, blocks)
        current = prepare_support_surface(lesson_id=base_lesson.lesson_id, owned_fact_ids=base_lesson.fact_ids,
                                          facts_by_id=facts_by_id, blocks=blocks, verified_context=context)
        if (current != prepared or response.request_sha256 != prepared.request_sha256
                or response.context_sha256 != prepared.context_sha256):
            raise ValueError("supported_surface_stale_custody")

    await checkpoint()
    await revalidate()
    if not support_response_valid(prepared, response, positive=True):
        raise ValueError("supported_surface_review_unproved")
    base_blocks = [{key: row[key] for key in ("heading", "text", "fact_ids")} for row in blocks]
    authored_keys = [(row["heading"], row["text"], tuple(row["fact_ids"])) for row in blocks]
    if len(set(authored_keys)) != len(authored_keys):
        raise ValueError("supported_surface_duplicate_block")
    scope = lesson_surface_render_scope(prepared=prepared.base, result=response._result,
        base_lesson=base_lesson, plan_fact_ids=set(base_lesson.fact_ids), facts_by_id=facts_by_id,
        blocks=base_blocks)
    if (not scope.surface_ready or scope.complete_fact_ids != frozenset(base_lesson.fact_ids)
            or set(scope.reviewed_sources) != set(range(len(blocks)))):
        raise ValueError("supported_surface_review_unproved")
    payload = {"title": base_lesson.title, "objective": base_lesson.objective, "blocks": base_blocks}
    rendered_lesson, _, grounded = ProviderBackedEvidenceEngine._validate_and_render(
        payload, base_lesson=base_lesson, plan_fact_ids=set(base_lesson.fact_ids),
        facts_by_id=facts_by_id, seeds=[], surface_review=(prepared.base, response._result))
    if len(grounded) != len(blocks):
        raise ValueError("supported_surface_render_changed")
    supported = []
    for row, output in zip(blocks, grounded, strict=True):
        if (output.heading != row["heading"] or output.text != row["text"]
                or set(output.fact_ids) != set(row["fact_ids"])):
            raise ValueError("supported_surface_render_changed")
        supported.append(SupportedGroundedBlock(output.lesson_id, output.heading, output.text, output.fact_ids,
            tuple(row["supporting_fact_ids"]), prepared.request_sha256, prepared.context_sha256))
    supporting = tuple(dict.fromkeys(fid for row in blocks for fid in row["supporting_fact_ids"]))
    rendered_lesson = replace(rendered_lesson, supporting_fact_ids=tuple(dict.fromkeys(
        (*rendered_lesson.supporting_fact_ids, *supporting))))
    await checkpoint()
    await revalidate()
    return SupportedSurfaceRender(rendered_lesson, tuple(supported))
