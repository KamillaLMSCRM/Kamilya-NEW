"""Explicit source structure joins a table to its lead-in and marked note."""

import pytest

from app.modules.ai.v3.partitioned_extraction import _unit_family_ids
from app.modules.ai.v3.source_units import SourceUnit


def units_for(parts):
    text = "".join(part[0] for part in parts)
    cursor = 0
    units = []
    for value, kind, family in parts:
        units.append(SourceUnit(cursor, cursor + len(value), value, kind, container_id=family))
        cursor += len(value)
    return text, units


def test_explicit_lead_in_and_marked_footnote_join_the_table():
    text, units = units_for([("1. Conditions:\n", "prose", ""), ("| A | 1 |\n", "table_row", "table-a"),
                             ("| B | 2 |\n", "table_row", "table-a"), ("*\\*Note applies to rows.\n", "prose", "")])
    assert _unit_family_ids(units, text) == ["table-a"] * 4


def test_unmarked_neighboring_paragraphs_are_not_merged():
    text, units = units_for([("1. General information.\n", "prose", ""),
                             ("| A | 1 |\n", "table_row", "table-a"),
                             ("An independent paragraph.\n", "prose", "")])
    assert _unit_family_ids(units, text) == ["", "table-a", ""]


def test_following_new_section_is_not_attached_even_if_it_looks_like_a_note():
    text, units = units_for([("1. Intro:\n", "prose", ""), ("| A | 1 |\n", "table_row", "table-a"),
                             ("2. New section\n*\\*Different note\n", "prose", "")])
    assert _unit_family_ids(units, text) == ["table-a", "table-a", ""]


def test_separate_tables_do_not_share_family():
    text, units = units_for([("1. First:\n", "prose", ""), ("| A | 1 |\n", "table_row", "table-a"),
                             ("2. Second:\n", "prose", ""), ("| B | 2 |\n", "table_row", "table-b")])
    assert _unit_family_ids(units, text) == ["table-a", "table-a", "table-b", "table-b"]


@pytest.mark.asyncio
async def test_owned_extraction_replay_keeps_table_lead_in_and_footnote_together():
    from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.v3.partitioned_extraction import extract_partitioned_rule_model
    from app.modules.ai.v3.service import _build_curriculum_groups
    from tests.unit.test_v3_partitioned_extraction import Journal

    source = "1. Conditions:\n\n| Type | Value |\n| --- | --- |\n| A | 1 |\n| B | 2 |\n\n*\\*Note applies to both.\n"
    document = DirectSourceDocument(doc_id="d1", title="source", filename="s", category="general",
                                    source_revision="revision", chunks=(), source_text=source)
    corpus = DirectSourceCorpus(tenant_id="tenant-1", documents=(document,), total_chars=len(source), total_chunks=0)
    journal = Journal()
    calls = []

    async def invoke(messages, response_format):
        target = messages[1]["content"].split("ЦЕЛЕВОЙ ФРАГМЕНТ:\n", 1)[1]
        calls.append(1)
        return {"rules": [{"rule_id": f"rule-{len(calls)}", "statement": target, "source_quote": target}]}

    result, _ = await extract_partitioned_rule_model(corpus, journal, "a" * 64, invoke)
    count = len(calls)
    replay, _ = await extract_partitioned_rule_model(corpus, journal, "a" * 64, invoke)
    assert len(calls) == count and result == replay and count >= 3
    assert len({rule.source_family for rule in result.rules}) == 1
    assert result.rules[0].source_family
    assert len(_build_curriculum_groups(result)) == 1
