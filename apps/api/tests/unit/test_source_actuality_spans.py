from hashlib import sha256
from uuid import uuid4

from app.modules.ai.direct_source import DirectSourceDocument
from app.modules.source_actuality.spans import WorkingTextChanges


def digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def document(value: str) -> DirectSourceDocument:
    return DirectSourceDocument(
        doc_id=str(uuid4()), title="Procedure", filename="proc.txt", category="general",
        source_revision=f"document:{digest(value)}", chunks=(), source_text=value,
    )


def reference(source: DirectSourceDocument, quote: str) -> dict:
    text = source.source_text or ""
    start = text.index(quote)
    return {
        "kind": "working_text_span_v1", "doc_id": source.doc_id,
        "source_revision": source.source_revision, "source_text_sha256": digest(text),
        "start": start, "end": start + len(quote), "span_sha256": digest(quote),
    }


def test_rule_change_rebinds_only_the_affected_span():
    first = "Store the completed form for 3 working days."
    changed = first.replace("3", "15")
    second = "The supervisor checks the signature before closing the shift."
    old = document(f"{first}\n{second}\n")
    new = document(f"{changed}\n{second}\n")
    mapping = WorkingTextChanges(old, new)
    assert mapping.rebind(reference(old, first)) == (reference(new, changed), True)
    assert mapping.rebind(reference(old, second)) == (reference(new, second), False)
    assert mapping.edits_are_covered([reference(old, first), reference(old, second)])


def test_parent_heading_edit_requires_review_even_when_the_cited_sentence_is_unchanged():
    quote = "Keep access open until the inspection is complete."
    old = document(f"Applies to site A\n{quote}")
    new = document(f"Applies to site B\n{quote}")
    mapping = WorkingTextChanges(old, new)
    assert mapping.rebind(reference(old, quote)) == (reference(new, quote), False)
    assert not mapping.edits_are_covered([reference(old, quote)])


def test_stale_or_unrecognizable_span_has_no_verified_replacement():
    first = "Store the completed form for 3 working days."
    old = document(first)
    new = document("The warehouse closes every Friday.")
    before = reference(old, first)
    assert WorkingTextChanges(old, new).rebind(before) is None
    assert WorkingTextChanges(old, document(first)).rebind({**before, "span_sha256": "0" * 64}) is None
