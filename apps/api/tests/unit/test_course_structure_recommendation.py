from app.modules.ai.source_analysis import recommend_course_structure


def test_automatic_structure_scales_with_source_volume():
    brief = recommend_course_structure(total_chunks=4, document_count=1)
    detailed = recommend_course_structure(total_chunks=1000, document_count=4)
    assert brief.resolved_format == "brief"
    assert detailed.resolved_format == "detailed"
    assert brief.module_count < detailed.module_count


def test_manual_module_count_is_an_explicit_advanced_override():
    result = recommend_course_structure(total_chunks=30, document_count=3, course_format="automatic", manual_modules=2)
    assert result.resolved_format == "custom"
    assert result.module_count == 2
    assert "manual_module_override" in result.reason_codes


def test_recommendation_is_deterministic_and_duration_is_bounded():
    first = recommend_course_structure(total_chunks=18, document_count=2, course_format="standard")
    second = recommend_course_structure(total_chunks=18, document_count=2, course_format="standard")
    assert first == second
    assert first.hard_max_total_lessons >= first.recommended_total_lessons
    assert first.duration_min_minutes <= first.estimated_duration_minutes <= first.duration_max_minutes


def test_chunk_proxy_does_not_turn_18_chunks_into_14_standard_lessons():
    plan = recommend_course_structure(total_chunks=18, document_count=1, course_format="standard")
    assert plan.recommended_total_lessons == 4
    assert plan.recommended_total_lessons < 14
    assert "source_capacity_proxy_chunks" in plan.reason_codes
    assert "source_sparse" not in plan.reason_codes


def test_source_sparse_only_describes_genuinely_low_capacity():
    plan = recommend_course_structure(total_chunks=4, document_count=1, course_format="brief")
    assert plan.hard_max_total_lessons == 2
    assert "source_sparse" in plan.reason_codes


def test_format_depth_is_monotonic_for_the_same_large_source():
    brief = recommend_course_structure(total_chunks=1000, document_count=1, course_format="brief")
    standard = recommend_course_structure(total_chunks=1000, document_count=1, course_format="standard")
    detailed = recommend_course_structure(total_chunks=1000, document_count=1, course_format="detailed")
    assert brief.recommended_total_lessons < standard.recommended_total_lessons < detailed.recommended_total_lessons
    assert brief.hard_max_total_lessons < standard.hard_max_total_lessons < detailed.hard_max_total_lessons


def test_tiny_source_is_never_padded_to_a_format_minimum():
    for course_format in ("brief", "standard", "detailed"):
        plan = recommend_course_structure(total_chunks=1, document_count=1, course_format=course_format)
        assert plan.recommended_total_lessons == 1
        assert plan.hard_max_total_lessons == 1


def test_huge_source_has_finite_format_caps():
    plans = [
        recommend_course_structure(total_chunks=10_000, document_count=100, course_format=course_format)
        for course_format in ("brief", "standard", "detailed")
    ]
    assert [plan.recommended_total_lessons for plan in plans] == [14, 25, 40]
    assert all(plan.recommended_total_lessons == plan.hard_max_total_lessons for plan in plans)


def test_manual_override_is_bounded_by_source_capacity():
    plan = recommend_course_structure(total_chunks=3, document_count=1, manual_modules=100)
    assert plan.module_count == 2
    assert plan.recommended_total_lessons <= 2
    assert plan.hard_max_total_lessons == 2
    assert "manual_module_override_bounded_by_source_capacity" in plan.reason_codes
    assert "manual_module_override" in plan.reason_codes


def test_manual_override_respects_public_module_and_custom_caps():
    plan = recommend_course_structure(total_chunks=10_000, document_count=1, manual_modules=100)
    assert plan.module_count <= 10
    assert plan.hard_max_total_lessons <= 40
    assert plan.recommended_total_lessons <= plan.hard_max_total_lessons


def test_brief_duration_respects_schema_minimum():
    plan = recommend_course_structure(total_chunks=1, document_count=1, course_format="brief")
    assert plan.estimated_duration_minutes >= 5
    assert plan.duration_min_minutes <= plan.estimated_duration_minutes <= plan.duration_max_minutes


def test_quizzes_follow_the_one_per_lesson_contract():
    for course_format in ("brief", "standard", "detailed"):
        plan = recommend_course_structure(total_chunks=100, document_count=1, course_format=course_format)
        assert plan.quiz_count == plan.recommended_total_lessons
