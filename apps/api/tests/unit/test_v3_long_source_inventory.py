"""A long source is inventoried losslessly before any model call."""

import pytest

from app.modules.ai.v3.source_units import (
    coalesce_leading_context,
    coalesce_structural_prose,
    coalesce_table_headers,
    plan_source_units,
)


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_spaced_tables_keep_rows_headers_and_exact_source_spans(newline):
    source = newline.join([
        '# First catalogue', '', '| Article | Material |', '', '| --- | --- |', '',
        '| A1 | First material |', '', '| A2 | ' + 'Complete long row ' * 3000 + ' |', '',
        'Independent prose.', '', '| Item | Dimensions |', '', '| --- | --- |', '',
        '| B1 | 10 × 20 × 30 |', '', '| B2 | 40 × 50 × 60 |', '', 'After tables.',
    ])
    units = plan_source_units(source)
    assert ''.join(unit.text for unit in units) == source
    assert all(unit.text == source[unit.start:unit.end] for unit in units)
    headers = [unit for unit in units if unit.kind == 'table_header']
    rows = [unit for unit in units if unit.kind == 'table_row']
    assert len(headers) == 2 and len(rows) == 4
    assert all('Article' in unit.context and 'Dimensions' not in unit.context for unit in rows[:2])
    assert all('Dimensions' in unit.context and 'Article' not in unit.context for unit in rows[2:])
    assert len({unit.container_id for unit in rows}) == 2
    assert sum('Complete long row ' in unit.text for unit in units) == 1


def test_hundred_section_source_inventory_preserves_every_boundary_and_marker():
    source = "".join(
        f"{index}. Section {index}\n\nMARKER_{index:03d} " + ("условие и действие; " * 130) + "\n\n"
        for index in range(1, 101)
    )
    units = coalesce_leading_context(coalesce_structural_prose(coalesce_table_headers(plan_source_units(source), source),
                                                                source), source)
    assert len(source) > 200_000
    assert "".join(unit.text for unit in units) == source
    assert all(unit.text == source[unit.start:unit.end] for unit in units)
    for index in range(1, 101):
        marker = f"MARKER_{index:03d} "
        assert sum(marker in unit.text for unit in units) == 1


@pytest.mark.asyncio
async def test_hundred_section_extraction_replays_without_losing_or_recalling_units():
    from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.v3.partitioned_extraction import extract_partitioned_rule_model
    from tests.unit.test_v3_partitioned_extraction import Journal

    source = "".join(
        f"{index}. Section {index}\n\nMARKER_{index:03d} " + ("условие и действие; " * 130) + "\n\n"
        for index in range(1, 101)
    )
    document = DirectSourceDocument(doc_id="long-doc", title="synthetic", filename="s", category="general",
                                    source_revision="rev", chunks=(), source_text=source)
    corpus = DirectSourceCorpus(tenant_id="tenant-1", documents=(document,), total_chars=len(source), total_chunks=0)
    journal = Journal()
    calls = []

    async def provider(messages, response_format):
        target = messages[1]["content"].split("ЦЕЛЕВОЙ ФРАГМЕНТ:\n", 1)[1]
        found = [f"MARKER_{i:03d}" for i in range(1, 101) if f"MARKER_{i:03d} " in target]
        calls.append(len(messages[1]["content"]))
        return {"rules": [{"rule_id": marker, "statement": marker, "source_quote": marker} for marker in found]}

    model, _ = await extract_partitioned_rule_model(corpus, journal, "a" * 64, provider)
    count = len(calls)
    replay, _ = await extract_partitioned_rule_model(corpus, journal, "a" * 64, provider)
    assert replay == model and len(calls) == count
    assert {r.rule_id for r in model.rules} == {f"MARKER_{i:03d}" for i in range(1, 101)}
    assert len(model.rules) == 100
    assert max(calls) < len(source) // 4
