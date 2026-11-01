"""Automated quality verification and invariant validator for V3 generation architecture."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from app.modules.ai.v3.models import V3Course

_POSITION_WORD = r"(?:перв\w*|втор\w*|трет\w*|четв[её]рт\w*|first|second|third|fourth)"
_OPTION_WORD = r"(?:вариант\w*|ответ\w*|дистрактор\w*|option\w*|answer\w*|distractor\w*)"
_POSITIONAL_FEEDBACK = re.compile(
    rf"\b(?:{_POSITION_WORD}\s+(?:(?:неверн\w*|неправильн\w*|правильн\w*|ошибочн\w*|incorrect|wrong|correct)\s+)?{_OPTION_WORD}"
    rf"|{_OPTION_WORD}\s*\(?(?:№\s*\d{{1,3}}|[1-9]|(?-i:[А-ГA-D])|{_POSITION_WORD})\b\)?"
    rf"|(?:выбер\w*|select|choose)\s+{_POSITION_WORD})",
    re.IGNORECASE,
)


def has_order_dependent_feedback(explanation: str) -> bool:
    """Detect explicit position-based feedback; a clean result is not semantic proof."""
    return bool(_POSITIONAL_FEEDBACK.search(explanation))


@dataclass(frozen=True)
class QualityMetrics:
    total_cases: int
    total_variants: int
    total_options_evaluated: int
    four_option_adherence_percent: float
    single_correct_adherence_percent: float
    zero_binary_adherence_percent: float
    distractor_category_breakdown: dict[str, int]
    length_bias_ratio_mean: float
    longest_correct_count: int
    longest_correct_percent: float
    anti_cheating_distractor_overlap_percent: float
    source_quotes_found_percent: float
    shortest_correct_count: int = 0
    shortest_correct_percent: float = 0.0
    unverified_quotes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ValidationReport:
    structural_verdict: str  # "PASS" or "FAIL"
    quality_status: str  # Always "needs_review" until independent semantic review proves factual truth
    metrics: QualityMetrics
    violations: list[str]

    @property
    def verdict(self) -> str:
        return self.structural_verdict

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.structural_verdict,
            "structural_verdict": self.structural_verdict,
            "quality_status": self.quality_status,
            "violations": self.violations,
            "metrics": {
                "total_cases": self.metrics.total_cases,
                "total_variants": self.metrics.total_variants,
                "total_options_evaluated": self.metrics.total_options_evaluated,
                "four_option_adherence_percent": self.metrics.four_option_adherence_percent,
                "single_correct_adherence_percent": self.metrics.single_correct_adherence_percent,
                "zero_binary_adherence_percent": self.metrics.zero_binary_adherence_percent,
                "distractor_category_breakdown": self.metrics.distractor_category_breakdown,
                "length_bias_ratio_mean": self.metrics.length_bias_ratio_mean,
                "longest_correct_count": self.metrics.longest_correct_count,
                "longest_correct_percent": self.metrics.longest_correct_percent,
                "shortest_correct_count": self.metrics.shortest_correct_count,
                "shortest_correct_percent": self.metrics.shortest_correct_percent,
                "anti_cheating_distractor_overlap_percent": self.metrics.anti_cheating_distractor_overlap_percent,
                "source_quotes_found_percent": self.metrics.source_quotes_found_percent,
                "unverified_quotes": self.metrics.unverified_quotes,
            },
        }


def is_search_separator(c: str) -> bool:
    """Checks whether character is whitespace, newline, table pipe, or Unicode space separator."""
    return c in " \t\r\n\f\v|" or unicodedata.category(c) in ("Zs", "Zl", "Zp")


def normalize_with_char_map(text: str) -> tuple[str, list[int]]:
    """Normalizes text with Unicode space/NBSP collapse, lowercasing, and 1:1 original char index mapping.

    Guarantees:
        len(norm_text) == len(char_map)
        Every sub-character from case folding (e.g. 'İ' -> 'i\\u0307') maps to the original index.
        Non-breaking spaces (U+00A0), narrow NBSP (U+202F), and table pipes are handled consistently.
    """
    cleaned_chars: list[str] = []
    char_map: list[int] = []
    in_whitespace = True

    for idx, char in enumerate(text):
        if is_search_separator(char):
            if not in_whitespace:
                cleaned_chars.append(" ")
                char_map.append(idx)
                in_whitespace = True
        else:
            lowered = char.lower()
            for sub_char in lowered:
                cleaned_chars.append(sub_char)
                char_map.append(idx)
            in_whitespace = False

    if cleaned_chars and cleaned_chars[-1] == " ":
        cleaned_chars.pop()
        char_map.pop()

    return "".join(cleaned_chars), char_map


def normalize_text_for_search(text: str) -> str:
    """Normalizes text by removing markdown table pipes, extra whitespace/NBSP, and converting to lowercase.

    Uses identical Unicode and separator logic as normalize_with_char_map to ensure zero search divergence.
    """
    norm_text, _ = normalize_with_char_map(text)
    return norm_text


def normalize_literal_quote(text: str) -> str:
    """Normalize case and whitespace without erasing table boundaries."""
    return normalize_literal_quote_with_char_map(text)[0]


def normalize_literal_quote_with_char_map(text: str) -> tuple[str, list[int]]:
    """Preserve delimiters and reversible positions while collapsing whitespace."""
    chars: list[str] = []
    offsets: list[int] = []
    pending_space: int | None = None
    for index, char in enumerate(text):
        if char.isspace():
            if chars and pending_space is None:
                pending_space = index
            continue
        if pending_space is not None:
            chars.append(" ")
            offsets.append(pending_space)
            pending_space = None
        for lowered in char.lower():
            chars.append(lowered)
            offsets.append(index)
    return "".join(chars), offsets


def validate_v3_course(
    course: V3Course,
    source_document_text: str = "",
    *,
    max_longest_correct_ratio: float = 0.25,
    source_documents: tuple[str, ...] | None = None,
) -> ValidationReport:
    """Rigorous offline validation of V3Course against didactic and structural invariants.

    IMPORTANT SAFETY INVARIANT:
    Automatic structural and text-matching validation checks form, length symmetry, and literal citation presence.
    It CANNOT prove semantic alignment (e.g. it cannot distinguish whether the generated rule reversed a prohibition).
    Therefore, quality_status is ALWAYS returned as 'needs_review', never falsely claiming 'verified' without
    an independent two-factor semantic audit.
    """
    sources = source_documents if source_documents is not None else (source_document_text,)
    normalized_sources = tuple(normalize_literal_quote(value) for value in sources if value.strip())
    violations: list[str] = []

    if not normalized_sources:
        violations.append("Source document text is empty; citation grounding cannot be verified.")

    total_cases = 0
    total_variants = 0
    total_options = 0
    four_opt_count = 0
    single_correct_count = 0
    zero_binary_count = 0
    distractor_categories: dict[str, int] = {}
    length_ratios: list[float] = []
    longest_correct_count = 0
    shortest_correct_count = 0
    quotes_verified = 0
    unverified_quotes: list[str] = []
    case_overlap_flags = 0

    prohibited_binary_words = {"да", "нет", "разрешено", "запрещено", "верно", "неверно", "все вышеперечисленное"}

    for _l_idx, lesson in enumerate(course.lessons, 1):
        for c_idx, case in enumerate(lesson.cases, 1):
            total_cases += 1
            variants = case.variants
            total_variants += len(variants)

            # Anti-cheating check: distinct distractors across variants of the same case
            if len(variants) >= 2:
                texts_v1 = {opt.text.strip().lower() for opt in variants[0].distractor_pool}
                texts_v2 = {opt.text.strip().lower() for opt in variants[1].distractor_pool}
                if texts_v1.intersection(texts_v2):
                    case_overlap_flags += 1
                    violations.append(
                        f"Anti-cheating violation: Case {case.case_id} shares duplicate distractors across variants"
                    )

            for v_idx, variant in enumerate(variants, 1):
                # Assemble question exactly as production adapter does
                assembled = variant.assemble_question(seed=100 + c_idx * 10 + v_idx)
                if has_order_dependent_feedback(assembled.explanation):
                    violations.append(f"Variant {variant.variant_id} has order-dependent explanation")
                opts = assembled.options
                total_options += len(opts)

                # Invariant 1: Exactly 4 options
                if len(opts) == 4:
                    four_opt_count += 1
                else:
                    violations.append(f"Variant {variant.variant_id} assembled with {len(opts)} options, expected 4")

                # Invariant 2: Exactly 1 correct option
                correct_opts = [o for o in opts if o.is_correct]
                wrong_opts = [o for o in opts if not o.is_correct]
                if len(correct_opts) == 1:
                    single_correct_count += 1
                else:
                    violations.append(
                        f"Variant {variant.variant_id} has {len(correct_opts)} correct options, expected 1"
                    )

                # Invariant 3: Zero binary yes/no
                has_binary = any(o.text.strip().lower() in prohibited_binary_words for o in opts)
                if not has_binary:
                    zero_binary_count += 1
                else:
                    violations.append(f"Variant {variant.variant_id} contains prohibited binary/blanket option")

                # Track distractor categories
                for d in variant.distractor_pool:
                    cat_name = d.distractor_category.value if d.distractor_category else "unspecified"
                    distractor_categories[cat_name] = distractor_categories.get(cat_name, 0) + 1

                # Invariant 4: Length symmetry & Anti-shortcut check
                if correct_opts and wrong_opts:
                    corr_len = len(correct_opts[0].text)
                    wrong_lens = [len(w.text) for w in wrong_opts]
                    avg_wrong = sum(wrong_lens) / len(wrong_lens)
                    if avg_wrong > 0:
                        length_ratios.append(corr_len / avg_wrong)

                    # Shortcut: correct is strictly longest
                    if corr_len > max(wrong_lens):
                        longest_correct_count += 1
                    if corr_len < min(wrong_lens):
                        shortest_correct_count += 1

                # Invariant 5: Strict Full-Quote Grounding (no 6-word shortcut)
                quote = variant.source_quote.strip()
                if quote and normalized_sources:
                    norm_q = normalize_literal_quote(quote)
                    if norm_q and any(norm_q in source for source in normalized_sources):
                        quotes_verified += 1
                    else:
                        unverified_quotes.append(f"{variant.variant_id}: '{quote[:70]}...'")
                        violations.append(
                            f"Citation grounding failure: Quote for {variant.variant_id} not found in full text"
                        )
                elif not quote:
                    unverified_quotes.append(f"{variant.variant_id}: Empty citation")
                    violations.append(f"Citation grounding failure: Empty quote in {variant.variant_id}")

    # Calculate percentages
    n_var = max(1, total_variants)
    four_opt_pct = (four_opt_count / n_var) * 100.0
    single_corr_pct = (single_correct_count / n_var) * 100.0
    zero_bin_pct = (zero_binary_count / n_var) * 100.0
    mean_ratio = round(sum(length_ratios) / max(1, len(length_ratios)), 2)
    longest_corr_pct = round((longest_correct_count / n_var) * 100.0, 1)
    shortest_corr_pct = round((shortest_correct_count / n_var) * 100.0, 1)
    overlap_pct = (case_overlap_flags / max(1, total_cases)) * 100.0
    quote_pct = round((quotes_verified / n_var) * 100.0, 1)

    # Invariant threshold checks
    if four_opt_pct < 100.0:
        violations.append(f"Invariant 1 failed: 4-option adherence is {four_opt_pct:.1f}% (required 100%)")
    if single_corr_pct < 100.0:
        violations.append(f"Invariant 2 failed: single-correct adherence is {single_corr_pct:.1f}% (required 100%)")
    if zero_bin_pct < 100.0:
        violations.append(f"Invariant 3 failed: zero-binary adherence is {zero_bin_pct:.1f}% (required 100%)")
    if not (0.80 <= mean_ratio <= 1.25):
        violations.append(f"Invariant 4 failed: length bias ratio {mean_ratio} outside [0.80, 1.25]")
    if longest_corr_pct > (max_longest_correct_ratio * 100.0):
        violations.append(
            f"Invariant 4 (Shortcut Gate) failed: correct answer is longest in {longest_corr_pct:.1f}% of questions "
            f"(maximum allowed {max_longest_correct_ratio*100:.1f}%)"
        )
    # A few questions cannot establish a reliable pattern. A strict shortest
    # answer in a majority of a larger set is a review-blocking clue, not a
    # semantic assessment of any individual answer.
    if total_variants >= 4 and shortest_correct_count * 2 > total_variants:
        violations.append(
            f"Invariant 4 (Shortcut Gate) failed: correct answer is shortest in {shortest_corr_pct:.1f}% of questions"
        )
    if overlap_pct > 0.0:
        violations.append(f"Invariant 5 failed: distractor overlap across variants is {overlap_pct:.1f}% (required 0%)")
    if normalized_sources and quote_pct < 95.0:
        violations.append(f"Invariant 6 failed: full source quote fidelity is {quote_pct:.1f}% (required >= 95%)")

    passed = len(violations) == 0
    structural_verdict = "PASS" if passed else "FAIL"

    # NOTE: Never set verified on automated structural checks alone!
    # Status is ALWAYS needs_review until methodologist or independent two-factor semantic review passes.
    quality_status = "needs_review"

    metrics = QualityMetrics(
        total_cases=total_cases,
        total_variants=total_variants,
        total_options_evaluated=total_options,
        four_option_adherence_percent=four_opt_pct,
        single_correct_adherence_percent=single_corr_pct,
        zero_binary_adherence_percent=zero_bin_pct,
        distractor_category_breakdown=distractor_categories,
        length_bias_ratio_mean=mean_ratio,
        longest_correct_count=longest_correct_count,
        longest_correct_percent=longest_corr_pct,
        shortest_correct_count=shortest_correct_count,
        shortest_correct_percent=shortest_corr_pct,
        anti_cheating_distractor_overlap_percent=overlap_pct,
        source_quotes_found_percent=quote_pct,
        unverified_quotes=unverified_quotes,
    )

    return ValidationReport(
        structural_verdict=structural_verdict,
        quality_status=quality_status,
        metrics=metrics,
        violations=violations,
    )
