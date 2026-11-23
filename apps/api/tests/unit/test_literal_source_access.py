import copy
import hashlib
import json
from dataclasses import replace

import pytest

from app.modules.ai.v3.literal_source_access import LiteralSourceAccess
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.simple_semantic_source_plan import (
    build_semantic_slices,
    semantic_plan_request,
    semantic_unit_request,
)
from app.modules.source_editorial_review.domain import ApprovedEditorialDocument, render_text
from app.modules.source_preparation.domain import PreparedSource, SourceBlock, SourcePart, digest
from tests.unit.test_v3_simple_source_unit import corpus_for


def reference_case():
    rule = "Consultant chooses a module; check the exact model before ordering."
    table = "# [Worksheet] Catalogue\n\n| Code | Name | Description |\n\n| --- | --- | --- |\n\n" + "".join(
        f"| MODEL{i:03} | Cabinet {i} | PRIVATE_LITERAL_{i:03} " + ("Exact data. " * 100) + " |\n\n" for i in range(30)
    )
    source = rule + "\n\n" + table
    blob = hashlib.sha256(source.encode()).hexdigest()
    blocks = [SourceBlock(id="block-" + digest(x)[:24], text=x, kind="text") for x in (rule, table)]
    parts = [
        SourcePart(
            id="part-" + digest(blob + b.id + b.id)[:24],
            title=role,
            role=role,
            reason="Prepared fixture role",
            first_block=b.id,
            last_block=b.id,
        )
        for b, role in zip(blocks, ("learning", "supporting"), strict=True)
    ]
    preparation = PreparedSource(original_blob_sha256=blob, blocks=blocks, parts=parts).binding([p.id for p in parts])
    corpus = corpus_for(source)
    doc = corpus.documents[0]
    working, spans = render_text(source, [])
    revision = "document:" + blob
    approved = ApprovedEditorialDocument(
        doc.doc_id,
        revision,
        "approval",
        source,
        working,
        hashlib.sha256(working.encode()).hexdigest(),
        tuple(spans),
        {},
        preparation=preparation,
    )
    corpus = replace(
        corpus, documents=(replace(doc, source_revision=revision, source_text=working, editorial_document=approved),)
    )
    packet = build_practical_source_packet(corpus)
    return corpus, packet


def test_index_keeps_every_row_and_exact_late_lookup_without_full_catalogue():
    corpus, packet = reference_case()
    before = copy.deepcopy(corpus)
    store = LiteralSourceAccess(packet, corpus, literal_budget=1500)
    assert len(store.rows) == 30
    messages, _ = semantic_plan_request(packet, corpus, {})
    projected, fp = store.project(messages, "practical:simple:plan:v11:" + packet.fingerprint)
    assert "PRIVATE_LITERAL_029" not in projected[1]["content"]
    assert "MODEL029" in projected[1]["content"]
    assert "Consultant chooses a module" in projected[1]["content"]
    late = store.rows[-1]
    result = store.lookup([late.handle], source_fingerprint=packet.fingerprint)
    assert result[0]["text"] == corpus.documents[0].source_text[late.start : late.end]
    assert result[0]["table_header"] == late.header and "Code | Name" in late.header
    assert "PRIVATE_LITERAL_029" in result[0]["text"]
    assert store.project(messages, "practical:simple:plan:v11:" + packet.fingerprint) == (projected, fp)
    assert corpus == before


def test_unit_sends_selected_row_not_neighbours_and_preserves_parent_once():
    corpus, packet = reference_case()
    store = LiteralSourceAccess(packet, corpus, literal_budget=1500)
    slices = build_semantic_slices(packet, corpus)
    selected = next(s for s in slices if "MODEL000" in s["text"])
    _, fmt = semantic_plan_request(packet, corpus, {})
    plan = {
        "source_fingerprint": packet.fingerprint,
        "slices_fingerprint": fmt["json_schema"]["schema"]["properties"]["slices_fingerprint"]["enum"][0],
        "title": "Course",
        "units": [
            {"id": "work", "title": "Choose the module", "primary_slices": [selected["id"]], "supporting_slices": []}
        ],
        "non_teaching": [
            {
                "slice_ids": [s["id"] for s in slices if s["text"].strip() and s["id"] != selected["id"]],
                "reason": "Lookup remains available",
            }
        ],
    }
    messages, _, _ = semantic_unit_request(packet, corpus, {}, plan, "work")
    projected, _ = store.project(messages, "practical:simple:author-unit:v9:" + packet.fingerprint)
    payload = json.loads(projected[1]["content"])
    assert "PRIVATE_LITERAL_000" in projected[1]["content"] and "PRIVATE_LITERAL_029" not in projected[1]["content"]
    assert projected[1]["content"].count("PRIVATE_LITERAL_000") == 1
    assert len(payload["reference_rows"]) == 1
    assert all("text" not in b for b in payload["source_blocks"])
    assert "".join(s["text"] for b in payload["source_blocks"] for s in b["segments"]).count("| Code | Name |") == 1


@pytest.mark.parametrize("bad", ["foreign", "duplicate", "stale"])
def test_lookup_is_bound_to_complete_approved_store(bad):
    corpus, packet = reference_case()
    store = LiteralSourceAccess(packet, corpus, literal_budget=1500)
    ids = [store.rows[-1].handle]
    source = packet.fingerprint
    if bad == "foreign":
        ids = ["ROW-foreign"]
    elif bad == "duplicate":
        ids *= 2
    else:
        source = "0" * 64
    with pytest.raises(ValueError, match="unowned"):
        store.lookup(ids, source_fingerprint=source)


def test_learning_rows_and_visual_source_are_not_reference_catalogue():
    corpus, packet = reference_case()
    doc = corpus.documents[0]
    preparation = copy.deepcopy(doc.editorial_document.preparation)
    preparation["manifest"]["parts"][1]["role"] = "learning"
    package = PreparedSource.model_validate(preparation["manifest"])
    preparation = package.binding(preparation["selected_part_ids"])
    approval = replace(doc.editorial_document, preparation=preparation)
    corpus = replace(corpus, documents=(replace(doc, editorial_document=approval),))
    packet = build_practical_source_packet(corpus)
    store = LiteralSourceAccess(packet, corpus, literal_budget=1500)
    assert not store.rows
    messages, _ = semantic_plan_request(packet, corpus, {})
    projected, _ = store.project(messages, "practical:simple:plan:v11:" + packet.fingerprint)
    assert "PRIVATE_LITERAL_029" in projected[1]["content"]


def test_split_original_header_is_not_repeated_for_each_hidden_row():
    corpus, packet = reference_case()
    store = LiteralSourceAccess(packet, corpus, literal_budget=1500)
    row = store.rows[0]
    canonical = store.view.alias_to_canonical[row.source_ref]
    block = next(b for b in packet.blocks if b.block_id == canonical)
    boundary = row.start - block.start
    store.origins[canonical]["segments"] = [
        {"origin": "document_body", "text": block.text[:boundary]},
        {"origin": "document_body", "text": block.text[boundary:]},
    ]
    assert "".join(x["text"] for x in store._segments(row.source_ref)).count("| Code | Name |") == 1


def test_plan_preserves_human_decision_for_exposed_learning_rule():
    corpus, packet = reference_case()
    doc = corpus.documents[0]
    rule = doc.source_text.split("\n\n", 1)[0]
    decision = {
        "item_id": "kept-rule",
        "decision": "keep",
        "quote": rule,
        "reason": "Confirmed specific operative scope",
        "start": 0,
        "end": len(rule),
    }
    corpus = replace(
        corpus,
        documents=(replace(doc, editorial_document=replace(doc.editorial_document, decision_context=(decision,))),),
    )
    packet = build_practical_source_packet(corpus)
    store = LiteralSourceAccess(packet, corpus, literal_budget=1500)
    messages, _ = semantic_plan_request(packet, corpus, {})
    projected, _ = store.project(messages, "practical:simple:plan:v11:" + packet.fingerprint)
    assert json.loads(projected[1]["content"])["documents"][0]["approved_decisions"][0]["item_id"] == "kept-rule"


def test_separately_prepared_rows_keep_all_late_literals_and_layout_is_not_evidence():
    corpus, _ = reference_case()
    doc = corpus.documents[0]
    # Actual spreadsheet preparation stores each row without its following newline.
    # The existing source-unit parser includes that newline in the structural span.
    texts = [x for x in doc.source_text.split("\n\n") if x]
    source = "\n\n".join(texts)
    blob = hashlib.sha256(source.encode()).hexdigest()
    blocks = [SourceBlock(id="block-" + digest(x)[:24], text=x, kind="text") for x in texts]
    learning = SourcePart(
        id="part-" + digest(blob + blocks[0].id + blocks[0].id)[:24],
        title="Learning",
        role="learning",
        reason="Fixture",
        first_block=blocks[0].id,
        last_block=blocks[0].id,
    )
    reference = SourcePart(
        id="part-" + digest(blob + blocks[1].id + blocks[-1].id)[:24],
        title="Reference",
        role="supporting",
        reason="Fixture",
        first_block=blocks[1].id,
        last_block=blocks[-1].id,
    )
    package = PreparedSource(original_blob_sha256=blob, blocks=blocks, parts=[learning, reference])
    working, spans = render_text(source, [])
    approved = ApprovedEditorialDocument(
        doc.doc_id,
        "document:" + blob,
        "approved",
        source,
        working,
        hashlib.sha256(working.encode()).hexdigest(),
        tuple(spans),
        {},
        preparation=package.binding([learning.id, reference.id]),
    )
    corpus = replace(
        corpus,
        documents=(
            replace(doc, source_revision=approved.source_revision, source_text=working, editorial_document=approved),
        ),
    )
    packet = build_practical_source_packet(corpus)
    store = LiteralSourceAccess(packet, corpus, literal_budget=1500)
    assert len(store.rows) == 30
    assert len(set(store.slice_rows.values())) == 30
    messages, _ = semantic_plan_request(packet, corpus, {})
    projected, _ = store.project(messages, "practical:simple:plan:v11:" + packet.fingerprint)
    assert "PRIVATE_LITERAL_000" not in projected[1]["content"] and "PRIVATE_LITERAL_029" not in projected[1]["content"]
    assert (
        "PRIVATE_LITERAL_029" in store.lookup([store.rows[-1].handle], source_fingerprint=packet.fingerprint)[0]["text"]
    )


def test_plan_accounting_references_missing_and_neighbor_rows_without_literal_duplication():
    corpus, packet = reference_case()
    store = LiteralSourceAccess(packet, corpus, literal_budget=1500)
    slices = build_semantic_slices(packet, corpus)
    table = [part for part in slices if part["id"] in store.slice_rows]
    narrative = next(part for part in slices if "Consultant chooses a module" in part["text"])
    body = {
        "source_fingerprint": packet.fingerprint,
        "missing_slices": [*table[:-1], narrative],
        "literal_neighbor_context": table[-1:],
    }
    messages = [{"role": "system", "content": "Account for the missing slices."},
                {"role": "user", "content": json.dumps(body)}]
    late = store.rows[-1]
    projected, _ = store.project(messages, "practical:simple:plan-accounting:v11:" + packet.fingerprint, (late.handle,))
    payload = json.loads(projected[1]["content"])
    assert len(payload["reference_index"]) == len(store.rows)
    assert payload["missing_slices"][-1] == narrative
    assert all("text" not in row and row["literal_available_by_lookup"] for row in payload["missing_slices"][:-1])
    assert payload["literal_neighbor_context"][0]["reference_row_id"] == late.handle
    assert payload["reference_rows"][0]["text"] == late.text
    assert projected[1]["content"].count("PRIVATE_LITERAL_029") == 1
    assert "PRIVATE_LITERAL_000" not in projected[1]["content"]


def test_narrative_mentions_respect_the_same_literal_budget_as_automatic_rows():
    corpus, packet = reference_case()
    store = LiteralSourceAccess(packet, corpus, literal_budget=1500)
    messages, _ = semantic_plan_request(packet, corpus, {})
    payload = json.loads(messages[1]["content"])
    payload["intent_notes"] = " ".join(row.key for row in store.rows)
    messages[1]["content"] = json.dumps(payload)
    projected, _ = store.project(messages, "practical:simple:plan:v11:" + packet.fingerprint)
    contents = json.loads(projected[1]["content"])
    assert len(contents["reference_index"]) == len(store.rows)
    assert len(contents["reference_rows"]) == 1
    assert sum(len(row["text"]) for row in contents["reference_rows"]) <= store.budget
