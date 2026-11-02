"""Offline numeric citation regressions; all provider/network access is denied."""
import socket

import httpx
import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.partitioned_extraction import extract_partitioned_rule_model
from tests.unit.test_v3_partitioned_extraction import Journal


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError('network forbidden')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket.socket, 'connect_ex', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)
    monkeypatch.setattr(httpx.Client, 'send', deny)
    monkeypatch.setattr(httpx.AsyncClient, 'send', deny)


@pytest.mark.asyncio
@pytest.mark.parametrize(('quote', 'expected', 'unconfirmed'), [
    ('From 700 100 to 1 100 000 tenge', 'From 7**00 100 to 1 100 000** tenge', False),
    ('I category | From 700 100 to 1 400 000 tenge', 'I category | From 700 100 to 1 400 000 tenge', True),
])
async def test_numeric_formatting_and_noncontiguous_prefix(quote, expected, unconfirmed):
    source = ('| Category | Limit |\n| --- | --- |\n'
              '| I category | From 7**00 100 to 1 100 000** tenge<br>Group A'
              '<br>From **700 100 to 1 400 000** tenge<br>Group B |\n')
    document = DirectSourceDocument(doc_id='d1', title='synthetic', filename='s.txt', category='general',
                                    source_revision='rev', chunks=(), source_text=source)
    corpus = DirectSourceCorpus(tenant_id='tenant-1', documents=(document,), total_chars=len(source), total_chunks=0)
    async def invoke(_messages, _response_format):
        return {'rules': [{'rule_id': 'r', 'statement': 'synthetic range', 'source_quote': quote}]}
    model, warnings = await extract_partitioned_rule_model(corpus, Journal(), 'a' * 64, invoke)
    assert model.rules[0].source_quote == expected
    if unconfirmed:
        assert any('не подтверждена' in item for item in warnings)
        assert expected not in source
    else:
        assert expected in source
        assert any('SHA256=' in item for item in warnings)


@pytest.mark.asyncio
@pytest.mark.parametrize(('source', 'quote'), [
    ('| A | From 7**00 100** tenge |\n| B | From 7**00 100** tenge |',
     'From 700 100 tenge'),
    ('| A | From 7**00 100** tenge |', 'From 700 101 tenge'),
    ('| A | 7**00 100** |\n| B | 1 100 000 |', '700 100 B 1 100 000'),
])
async def test_ambiguous_changed_or_cross_row_numeric_quote_remains_unconfirmed(source, quote):
    document = DirectSourceDocument(doc_id='d1', title='synthetic', filename='s.txt', category='general',
                                    source_revision='rev', chunks=(), source_text=source)
    corpus = DirectSourceCorpus(tenant_id='tenant-1', documents=(document,), total_chars=len(source), total_chunks=0)
    async def invoke(_messages, _response_format):
        return {'rules': [{'rule_id': 'r', 'statement': 'synthetic range', 'source_quote': quote}]}
    model, warnings = await extract_partitioned_rule_model(corpus, Journal(), 'a' * 64, invoke)
    assert model.rules[0].source_quote == quote
    assert any('не подтверждена' in item for item in warnings)
    assert not any('SHA256=' in item for item in warnings)


@pytest.mark.asyncio
async def test_unconfirmed_cross_row_quote_holds_before_diversity_request():
    from app.modules.ai.v3.diversity_review import review_final_lesson
    from app.modules.ai.v3.primary_source_manifest import build_primary_source_manifest

    source = '| A | 7**00 100** |\n| B | 1 100 000 |'
    quote = '700 100 B 1 100 000'
    document = DirectSourceDocument(doc_id='d1', title='synthetic', filename='s.txt', category='general',
                                    source_revision='rev', chunks=(), source_text=source)
    corpus = DirectSourceCorpus(tenant_id='tenant-1', documents=(document,), total_chars=len(source), total_chunks=0)
    async def extract(_messages, _response_format):
        return {'rules': [{'rule_id': 'r', 'statement': 'synthetic range', 'source_quote': quote}]}
    journal = Journal()
    model, warnings = await extract_partitioned_rule_model(corpus, journal, 'a' * 64, extract)
    assert any('не подтверждена' in item for item in warnings)
    assert build_primary_source_manifest(corpus, model.rules, expected_tenant_id='tenant-1',
                                         expected_document_ids=('d1',)) is None
    calls = []
    async def review(messages):
        calls.append(messages)
        raise AssertionError('unconfirmed source reached review')
    result = await review_final_lesson(lesson=None, corpus=corpus, rules=model.rules,
        expected_tenant_id='tenant-1', expected_document_ids=('d1',), journal=journal,
        group_id='synthetic', source_sha256='b' * 64, route_fingerprint='a' * 64, invoke=review)
    assert result == {'status': 'unknown', 'reason': 'source_manifest_unavailable'}
    assert calls == []
