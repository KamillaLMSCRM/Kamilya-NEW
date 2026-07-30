from app.modules.courses.release_service import canonical_json_sha256


def test_canonical_json_sha256_is_stable_across_key_order():
    first = {"course": {"id": "1", "title": "Курс"}, "version": 1}
    second = {"version": 1, "course": {"title": "Курс", "id": "1"}}

    assert canonical_json_sha256(first) == canonical_json_sha256(second)
    assert len(canonical_json_sha256(first)) == 64
