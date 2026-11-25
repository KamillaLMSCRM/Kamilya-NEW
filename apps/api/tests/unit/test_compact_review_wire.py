import json

from app.modules.ai.v3.normalized_editorial_review import normalized_review_format
from app.modules.ai.v3.source_access_contract import (
    CONNECTOR_SCHEMA_MAX_BYTES,
    access_format,
    compact_oversized_review,
    matches_access,
    retired_oversized_review,
)


def test_large_review_fits_connector_and_checks_every_source_reference():
    source, draft, context = ("1" * 64, "2" * 64, "3" * 64)
    group = f"practical:simple:review-content:v9:{source}:unit={draft}"
    refs = [f"SRC{i}" for i in range(1, 501)]
    lesson_ids = [f"lesson-{i}" for i in range(16)]
    inner = normalized_review_format(refs, lesson_ids, ["question-1"], source, draft)
    legacy = access_format(inner, source, context, group, [])
    compact = compact_oversized_review(legacy)

    assert len(json.dumps(legacy, ensure_ascii=False).encode()) > CONNECTOR_SCHEMA_MAX_BYTES
    assert len(json.dumps(compact, ensure_ascii=False).encode()) < CONNECTOR_SCHEMA_MAX_BYTES
    assert retired_oversized_review(compact) == legacy
    assert retired_oversized_review(legacy) is None

    review = {"source_fingerprint": source, "course_fingerprint": draft, "summary": "Reviewed teaching",
              "findings": [], "source_notes": [],
              "narrative_sources": {lesson: ["SRC500"] for lesson in lesson_ids}}
    value = {"source_fingerprint": source, "context_fingerprint": context,
             "base_group": group, "lookup_ids": [], "results": [review]}
    assert matches_access(value, legacy) and matches_access(value, compact)
    review["narrative_sources"][lesson_ids[0]] = ["SRC501"]
    assert not matches_access(value, compact)
    review["narrative_sources"].pop(lesson_ids[0])
    assert not matches_access(value, compact)

    small = access_format(normalized_review_format(refs[:4], lesson_ids[:2], ["question-1"], source, draft),
                          source, context, group, [])
    assert compact_oversized_review(small) == small
