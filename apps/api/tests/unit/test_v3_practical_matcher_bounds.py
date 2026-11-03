import pytest

from app.modules.ai.v3.batch_review_response_schema import _matches


@pytest.mark.parametrize("value,schema,expected", [
    ("foreign", {"type": "string", "enum": ["owned"]}, False),
    ("owned", {"type": "string", "enum": ["owned"]}, True),
    (2, {"type": "integer", "enum": [0, 1]}, False),
    (True, {"type": "integer", "enum": [1]}, False),
    ([], {"type": "array", "items": {"type": "string"}, "minItems": 1}, False),
    (["a", "b"], {"type": "array", "items": {"type": "string"}, "maxItems": 1}, False),
    (["a"], {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 1}, True),
])
def test_enum_and_array_bounds_are_enforced(value, schema, expected):
    assert _matches(value, schema) is expected
