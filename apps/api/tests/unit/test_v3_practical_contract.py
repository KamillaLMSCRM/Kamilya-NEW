from dataclasses import replace

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3 import practical_contract as contract
from app.modules.ai.v3.source_reference_decisions import SourceReferenceDecision


def corpus():
    text = "First paragraph.\n\nSecond paragraph."
    doc = DirectSourceDocument("doc", "Title", "file", "category", "r1", (), source_text=text)
    return DirectSourceCorpus("tenant", (doc,), len(text), 0)


def course(packet, choices=None):
    return {
        "title": "Course",
        "lessons": [
            {
                "id": "l1",
                "title": "Lesson",
                "content": "Content",
                "questions": [
                    {
                        "id": "q1",
                        "prompt": "Question",
                        "choices": choices or ["a", "b", "c"],
                        "correct_index": 0,
                        "explanation": "Reason",
                        "source_refs": [b.block_id for b in packet.blocks if b.text.strip()],
                    }
                ],
            }
        ],
    }


def test_source_is_exact_and_identity_is_bound():
    data = corpus()
    packet = contract.build_practical_source_packet(data)
    assert "".join(b.text for b in packet.blocks) == data.documents[0].source_text
    assert all(data.documents[0].source_text[b.start : b.end] == b.text for b in packet.blocks)
    other = replace(data, documents=(replace(data.documents[0], doc_id="other"),))
    assert packet.blocks[0].block_id != contract.build_practical_source_packet(other).blocks[0].block_id
    other = replace(data, documents=(replace(data.documents[0], source_text="Changed."),))
    assert packet.blocks[0].block_id != contract.build_practical_source_packet(other).blocks[0].block_id


def test_rejects_missing_coverage(monkeypatch):
    original = contract.plan_source_units
    monkeypatch.setattr(contract, "plan_source_units", lambda text: original(text)[:-1])
    with pytest.raises(ValueError, match="coverage"):
        contract.build_practical_source_packet(corpus())


def test_reference_decisions_are_bound_to_source():
    packet = contract.build_practical_source_packet(corpus())
    digest = packet.source_documents[0][2]
    decision = SourceReferenceDecision("tenant", "doc", "r1", digest, 0, 5, "First", 18, 24, "Second", "owner_chat")
    assert contract.build_practical_source_packet(corpus(), (decision,)).reference_context
    for altered in (
        replace(decision, tenant_id="other"),
        replace(decision, document_id="other"),
        replace(decision, converted_text_sha256="0" * 64),
        replace(decision, reference_exact="Wrong"),
    ):
        with pytest.raises(ValueError):
            contract.build_practical_source_packet(corpus(), (altered,))


@pytest.mark.parametrize("choices", [["a", "b", "c"], ["a", "b", "c", "d"]])
def test_valid_course_is_preserved_and_copied(choices):
    packet = contract.build_practical_source_packet(corpus())
    value = course(packet, choices)
    result = contract.validate_practical_course(value, packet)
    assert result == value and result is not value and result["lessons"] is not value["lessons"]
    assert contract.course_response_format(packet)["json_schema"]["strict"] is True


@pytest.mark.parametrize(
    "mutation", ["empty", "duplicate", "index", "bool", "foreign", "empty_ref", "duplicate_ref", "blank"]
)
def test_invalid_course_rejected(mutation):
    packet = contract.build_practical_source_packet(corpus())
    value = course(packet)
    q = value["lessons"][0]["questions"][0]
    if mutation == "empty":
        q["choices"] = []
    if mutation == "duplicate":
        q["choices"] = ["a", " A ", "c"]
    if mutation == "index":
        q["correct_index"] = 3
    if mutation == "bool":
        q["correct_index"] = True
    if mutation == "foreign":
        q["source_refs"] = ["other"]
    if mutation == "empty_ref":
        q["source_refs"] = []
    if mutation == "duplicate_ref":
        q["source_refs"].append(q["source_refs"][0])
    if mutation == "blank":
        q["prompt"] = "  "
    with pytest.raises(ValueError):
        contract.validate_practical_course(value, packet)


def test_subset_citations_and_registry_validation():
    packet = contract.build_practical_source_packet(corpus())
    value = course(packet)
    value["lessons"][0]["questions"][0]["source_refs"] = [packet.blocks[0].block_id]
    form = contract.course_response_format(packet)
    assert contract.validate_practical_course(value, packet) == value
    assert contract.is_practical_course_format(form)
    assert contract.matches_practical_course_response(value, form)
    value["lessons"][0]["questions"][0]["source_refs"] = ["foreign"]
    assert not contract.matches_practical_course_response(value, form)
    form["json_schema"]["strict"] = False
    assert not contract.is_practical_course_format(form)


def test_forged_packet_metadata_rejected():
    packet = contract.build_practical_source_packet(corpus())
    for forged in (
        replace(packet, fingerprint="bad"),
        replace(packet, source_documents=(("doc", "r1", "bad"),)),
        replace(packet, blocks=(replace(packet.blocks[0], text="forged"), *packet.blocks[1:])),
    ):
        with pytest.raises(ValueError):
            contract.course_response_format(forged)
        with pytest.raises(ValueError):
            contract.validate_practical_course(course(packet), forged)


def test_reference_may_span_blocks():
    data = corpus()
    text = data.documents[0].source_text
    packet = contract.build_practical_source_packet(data)
    decision = SourceReferenceDecision(
        "tenant", "doc", "r1", packet.source_documents[0][2], 0, len(text), text, 0, 5, "First", "owner_chat"
    )
    assert contract.build_practical_source_packet(data, (decision,)).reference_context
