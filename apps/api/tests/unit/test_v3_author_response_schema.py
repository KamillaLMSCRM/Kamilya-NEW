"""The author format is a strict shape contract, not semantic approval."""
from copy import deepcopy

import pytest

from app.modules.ai.v3.author_response_schema import (
    is_lesson_author_response_format,
    lesson_author_response_format,
    lesson_author_schema_hash,
)


def assert_subset_schema(schema):
    kind = schema["type"]
    if kind == "object":
        assert set(schema) == {"type", "properties", "required", "additionalProperties"}
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        assert len(schema["required"]) == len(schema["properties"])
        for item in schema["properties"].values():
            assert_subset_schema(item)
    elif kind == "array":
        assert set(schema) <= {"type", "items", "minItems"}
        assert_subset_schema(schema["items"])
    else:
        assert kind == "string" and set(schema) <= {"type", "enum"}


def matches(schema, value):
    kind = schema["type"]
    if kind == "object":
        return (isinstance(value, dict) and set(value) == set(schema["required"])
                and all(matches(sub, value[key]) for key, sub in schema["properties"].items()))
    if kind == "array":
        return (isinstance(value, list) and len(value) >= schema.get("minItems", 0)
                and all(matches(schema["items"], item) for item in value))
    return isinstance(value, str) and ("enum" not in schema or value in schema["enum"])


def valid_lesson():
    variant = {"variant_id": "v", "branch_context": "", "scenario_premise": "example", "prompt": "question",
               "correct_option": {"text": "correct"},
               "distractor_pool": [{"text": "wrong", "distractor_category": "procedural_confusion"} for _ in range(3)],
               "explanation": "explanation", "source_quote": "example"}
    return {"lesson_id": "l", "title": "title", "module_title": "module", "content": "text",
            "cases": [{"case_id": "c", "rule_id": "r", "learning_objective": "objective", "variants": [variant]}]}


def test_strict_shape_and_real_prompt_fields():
    fmt = lesson_author_response_format()
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["name"] == "v3_lesson_author_v1"
    assert fmt["json_schema"]["strict"] is True
    schema = fmt["json_schema"]["schema"]
    assert_subset_schema(schema)
    assert matches(schema, valid_lesson())
    longer = valid_lesson()
    longer["cases"][0]["variants"][0]["distractor_pool"].append({"text": "other", "distractor_category": "threshold_error"})
    assert matches(schema, longer)
    assert matches(schema, {**valid_lesson(), "cases": []})


@pytest.mark.parametrize("mutation", ["missing", "extra", "wrong_type", "few_distractors", "bad_category", "flat_questions"])
def test_schema_rejects_wrong_transport_shapes(mutation):
    lesson = valid_lesson()
    variant = lesson["cases"][0]["variants"][0]
    if mutation == "missing":
        del variant["source_quote"]
    elif mutation == "extra":
        variant["extra"] = "x"
    elif mutation == "wrong_type":
        lesson["content"] = []
    elif mutation == "few_distractors":
        variant["distractor_pool"].pop()
    elif mutation == "bad_category":
        variant["distractor_pool"][0]["distractor_category"] = "invented"
    else:
        lesson["questions"] = []
    assert not matches(lesson_author_response_format()["json_schema"]["schema"], lesson)


def test_fresh_deep_copies_exact_recognition_and_hash():
    first = lesson_author_response_format()
    snapshot = deepcopy(first)
    assert is_lesson_author_response_format(first)
    assert len(lesson_author_schema_hash()) == 64
    first["json_schema"]["schema"]["properties"]["title"]["type"] = "number"
    assert lesson_author_response_format() == snapshot
    assert snapshot["json_schema"]["schema"]["properties"]["content"]["type"] == "string"
    assert not is_lesson_author_response_format(first)
    assert not is_lesson_author_response_format({"type": "json_object"})
    assert not is_lesson_author_response_format(None)
