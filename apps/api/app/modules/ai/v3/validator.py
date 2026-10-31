"""Automated quality verification and invariant validator for V3 generation architecture."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.modules.ai.v3.models import V3Course


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
                "anti_cheating_distractor_overlap_percent": self.metrics.anti_cheating_distractor_overlap_percent,
                "source_quotes_found_percent": self.metrics.source_quotes_found_percent,
                "unverified_quotes": self.metrics.unverified_quotes,
            },
        }


def normalize_text_for_search(text: str) -> str:
    """Normalizes text by removing markdown table pipes, extra whitespace, and converting to lowercase."""
    cleaned = text.replace("|", " ").replace("\n", " ").replace("\r", " ").replace("\t", " ")
    return " ".join(cleaned.lower().split())


def validate_v3_course(
    course: V3Course,
    source_document_text: str = "",
    *,
    max_longest_correct_ratio: float = 0.25,
) -> ValidationReport:
    """Rigorous offline validation of V3Course against didactic and structural invariants.

    IMPORTANT SAFETY INVARIANT:
    Automatic structural and text-matching validation checks form, length symmetry, and literal citation presence.
    It CANNOT prove semantic alignment (e.g. it cannot distinguish whether the generated rule reversed a prohibition).
    Therefore, quality_status is ALWAYS returned as 'needs_review', never falsely claiming 'verified' without
    an independent two-factor semantic audit.
    """
    norm_source = normalize_text_for_search(source_document_text) if source_document_text else ""
    violations: list[str] = []

    if not norm_source:
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

                # Invariant 5: Strict Full-Quote Grounding (no 6-word shortcut)
                quote = variant.source_quote.strip()
                if quote and norm_source:
                    norm_q = normalize_text_for_search(quote)
                    if norm_q and norm_q in norm_source:
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
    if overlap_pct > 0.0:
        violations.append(f"Invariant 5 failed: distractor overlap across variants is {overlap_pct:.1f}% (required 0%)")
    if norm_source and quote_pct < 95.0:
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
