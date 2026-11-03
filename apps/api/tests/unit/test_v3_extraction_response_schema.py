"""Typed extraction schema shape is distinct from factual acceptance."""
import hashlib
import json
from copy import deepcopy

import pytest

from app.modules.ai.v3.extraction_response_schema import (
    is_rule_extraction_response,
    is_rule_extraction_response_format,
    rule_extraction_response_format,
    rule_extraction_schema_hash,
)


def response():
    return {"document_title": "example", "overview": "", "rules": [{
        "rule_id": "r", "section": "s", "title": "t", "statement": "text", "conditions": ["if"],
        "exceptions": [], "actors": ["actor"], "timing": "", "consequences": "", "source_quote": "quote",
    }]}


def test_schema_is_exact_closed_and_unbounded():
    fmt = rule_extraction_response_format()
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["name"] == "v3_rule_extraction_v1" and fmt["json_schema"]["strict"] is True
    root = fmt["json_schema"]["schema"]
    rule = root["properties"]["rules"]["items"]
    for node in (root, rule):
        assert set(node) == {"type", "properties", "required", "additionalProperties"}
        assert node["type"] == "object" and node["additionalProperties"] is False
        assert set(node["required"]) == set(node["properties"])
    assert set(root["properties"]) == {"document_title", "overview", "rules"}
    assert set(rule["properties"]) == {"rule_id", "section", "title", "statement", "conditions", "exceptions",
                                       "actors", "timing", "consequences", "source_quote"}
    for field in ("conditions", "exceptions", "actors"):
        assert rule["properties"][field] == {"type": "array", "items": {"type": "string"}}
    assert is_rule_extraction_response(response())
    assert is_rule_extraction_response({"document_title": "", "overview": "", "rules": []})


@pytest.mark.parametrize("field", ["conditions", "exceptions", "actors"])
@pytest.mark.parametrize("bad", ["text", [1], [None], True, None, ("text",)])
def test_array_string_fields_reject_non_arrays_or_non_strings(field, bad):
    value = response()
    value["rules"][0][field] = bad
    assert not is_rule_extraction_response(value)


@pytest.mark.parametrize("mutation", ["missing", "extra", "doc_id", "root_extra", "wrong_string", "rules_tuple", "wrong_rule"])
def test_wrong_shapes_rejected(mutation):
    value = response()
    rule = value["rules"][0]
    if mutation == "missing":
        del rule["source_quote"]
    elif mutation == "extra":
        rule["source_revision"] = "x"
    elif mutation == "doc_id":
        rule["doc_id"] = "x"
    elif mutation == "root_extra":
        value["extra"] = True
    elif mutation == "wrong_string":
        rule["statement"] = False
    elif mutation == "rules_tuple":
        value["rules"] = tuple(value["rules"])
    else:
        value["rules"] = [None]
    assert not is_rule_extraction_response(value)


def test_format_hash_fresh_copy_and_exact_recognition():
    fmt = rule_extraction_response_format()
    original = deepcopy(fmt)
    expected = hashlib.sha256(json.dumps(fmt, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    assert rule_extraction_schema_hash() == expected and is_rule_extraction_response_format(fmt)
    fmt["json_schema"]["schema"]["properties"]["document_title"]["type"] = "number"
    assert rule_extraction_response_format() == original and not is_rule_extraction_response_format(fmt)
    changes = []
    for key, val in (("name", "other"), ("strict", 1)):
        candidate = deepcopy(original)
        candidate["json_schema"][key] = val
        changes.append(candidate)
    candidate = deepcopy(original)
    candidate["json_schema"]["schema"]["additionalProperties"] = True
    changes.append(candidate)
    candidate = deepcopy(original)
    candidate["json_schema"]["schema"]["required"] = tuple(candidate["json_schema"]["schema"]["required"])
    changes.extend([candidate, {"type": "json_object"}, None])
    assert all(not is_rule_extraction_response_format(value) for value in changes)
