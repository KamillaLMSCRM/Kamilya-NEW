import socket
from dataclasses import replace

import httpx
import pytest

from app.modules.ai.v3.diversity_repair_selection import select_candidate
from app.modules.ai.v3.diversity_variant_candidate import parse_target_variant
from tests.unit.test_v3_diversity_repair_selection import setup


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def denied(*_args, **_kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(httpx, "Client", denied)
    monkeypatch.setattr(httpx, "AsyncClient", denied)


@pytest.mark.parametrize("index", [1, 2])
def test_variant_candidate_preserves_other_fields(index):
    data = setup()
    selected = select_candidate(**(data | {"selected_index": index}))
    assert selected is not None
    lesson = data["lesson"]
    lesson = replace(lesson, questions=(lesson.cases[0].variants[0].assemble_question(seed=42),))
    response = {"variant_id": selected.variant_id, "branch_context": "", "scenario_premise": "new situation",
                "prompt": "new target?", "correct": "new fact", "explanation": "reason",
                "source_quote": selected.source_quote,
                "distractors": [{"text": value, "category": "role_confusion"} for value in ("a", "b", "c")]}
    candidate = parse_target_variant(lesson, selected, response)
    assert candidate is not None
    assert candidate.cases[0].variants[index - 1].prompt == "new target?"
    assert candidate.cases[0].variants[2 - index] == lesson.cases[0].variants[2 - index]
    assert parse_target_variant(lesson, selected, response | {"source_quote": "invented"}) is None
    assert parse_target_variant(lesson, selected, response | {"variant_id": "other"}) is None
    assert parse_target_variant(lesson, selected, response | {"correct": "a"}) is None
