"""Rendered OCR formatting may bind only to the unique owned source unit."""

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.partitioned_extraction import extract_partitioned_rule_model
from tests.unit.test_v3_partitioned_extraction import Journal


@pytest.mark.asyncio
async def test_unique_rendered_rule_quote_is_bound_to_exact_source_with_review_signal():
    source = "Не выдавать<br>без **согласования**."
    document = DirectSourceDocument(doc_id="d1", title="s", filename="s", category="general",
                                    source_revision="rev", chunks=(), source_text=source)
    corpus = DirectSourceCorpus(tenant_id="tenant-1", documents=(document,), total_chars=len(source), total_chunks=0)

    async def invoke(messages, response_format):
        return {"rules": [{"rule_id": "r", "statement": "Не выдавать без согласования.",
                           "source_quote": "Не выдавать без согласования."}]}

    model, warnings = await extract_partitioned_rule_model(corpus, Journal(), "a" * 64, invoke)
    assert model.rules[0].source_quote == source
    assert any("SHA256=" in warning for warning in warnings)


@pytest.mark.asyncio
async def test_ambiguous_rendered_rule_quote_is_not_automatically_bound():
    source = "Не выдавать<br>без **согласования**. Не выдавать<br>без **согласования**."
    document = DirectSourceDocument(doc_id="d1", title="s", filename="s", category="general",
                                    source_revision="rev", chunks=(), source_text=source)
    corpus = DirectSourceCorpus(tenant_id="tenant-1", documents=(document,), total_chars=len(source), total_chunks=0)

    async def invoke(messages, response_format):
        return {"rules": [{"rule_id": "r", "statement": "Не выдавать без согласования.",
                           "source_quote": "Не выдавать без согласования."}]}

    model, _ = await extract_partitioned_rule_model(corpus, Journal(), "a" * 64, invoke)
    assert model.rules[0].source_quote == "Не выдавать без согласования."


@pytest.mark.asyncio
async def test_rendered_rule_quote_cannot_join_different_table_cells_or_rows():
    source = "| Category | Limit |\n| --- | --- |\n| A | 100 |\n| B | 200 |\n"
    document = DirectSourceDocument(doc_id="d1", title="s", filename="s", category="general",
                                    source_revision="rev", chunks=(), source_text=source)
    corpus = DirectSourceCorpus(tenant_id="tenant-1", documents=(document,), total_chars=len(source), total_chunks=0)

    async def invoke(messages, response_format):
        return {"rules": [{"rule_id": "r", "statement": "claim", "source_quote": "100 B"}]}

    model, warnings = await extract_partitioned_rule_model(corpus, Journal(), "a" * 64, invoke)
    assert all(rule.source_quote == "100 B" for rule in model.rules)
    assert any("не подтверждена" in warning for warning in warnings)
