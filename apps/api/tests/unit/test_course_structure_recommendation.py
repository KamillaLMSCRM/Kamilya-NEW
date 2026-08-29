from app.modules.ai.source_analysis import recommend_course_structure


def test_automatic_structure_scales_with_source_volume():
    brief = recommend_course_structure(total_chunks=4, document_count=1)
    detailed = recommend_course_structure(total_chunks=30, document_count=4)
    assert brief.resolved_format == "brief"
    assert detailed.resolved_format == "detailed"
    assert brief.module_count < detailed.module_count


def test_manual_module_count_is_an_explicit_advanced_override():
    result = recommend_course_structure(total_chunks=30, document_count=3, course_format="automatic", manual_modules=2)
    assert result.resolved_format == "custom"
    assert result.module_count == 2
    assert result.reason_codes == ("manual_module_override",)
