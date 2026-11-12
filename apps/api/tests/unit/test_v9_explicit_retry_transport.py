"""Real managed HTTP, pending receipt, acknowledged retry and whole V9 continuation."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.qa_luna_dev_route import QA_TENANT
from app.modules.ai.v3 import explicit_stage_retry as retry
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.pending_stage_transactions import checked_entries
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.qa_luna_pending_policy import KEY as QA_KEY
from app.modules.ai.v3.qa_luna_pending_policy import MANAGED_POLICY
from app.modules.ai.v3.response_contracts import response_contract_hash
from app.modules.ai.v3.revision_policy import POLICY, SIMPLE_COURSE_REVIEW_V9_POLICY
from app.modules.ai.v3.service import generate_v3_course_from_corpus
from app.modules.source_editorial_review.service import SOURCE_PINS
from tests.unit.test_direct_luna_owned_stage import setup
from tests.unit.test_managed_http_rejection import Body
from tests.unit.test_v3_simple_owned_transport_v2 import client_for
from tests.unit.test_v3_simple_owned_transport_v3 import synthetic_corpus
from tests.unit.test_v3_simple_owned_transport_v9 import response_for


@pytest.mark.asyncio
@pytest.mark.parametrize(('failure', 'drift'), [('capacity', None), ('unavailable', None)] + [
    ('capacity', d) for d in ('prompt', 'route', 'cap', 'cache', 'skip')])
async def test_real_http_failure_is_retained_and_only_unfinished_stage_runs_again(monkeypatch, failure, drift):
    fake, journal, _, _, _ = setup()
    fake.tenant_id = journal.tenant_id = str(QA_TENANT)
    fake.job.id, fake.job.tenant_id = fake.job_id, QA_TENANT
    fake.job.course_id, fake.job.errors = None, ['generation_stage_outcome_unknown']
    journal.review_policy_bound = True
    journal.expected_review_policy = SIMPLE_COURSE_REVIEW_V9_POLICY
    corpus = synthetic_corpus(journal.tenant_id, mixed_origin=True)
    packet = build_practical_source_packet(corpus)
    client = client_for(journal)
    documents = [str(d.doc_id) for d in corpus.documents]
    fake.job.params = {'documents': documents, 'source_analysis': {'generation_engine': 'evidence_v3',
        'v3_review_policy': SIMPLE_COURSE_REVIEW_V9_POLICY, QA_KEY: MANAGED_POLICY,
        SOURCE_PINS: {'synthetic': 'pins'}}}
    fake.job.result = {'v3_owned_route_binding': {
        'policy': 'v3-owned-route-binding-v1', 'fingerprint': client.cache_fingerprint()}}
    picture = '![Caption a](source-asset:asset-' + 'a' * 64 + ')'
    roles = []
    wires = []
    failed = False

    async def handler(request):
        nonlocal failed
        payload = json.loads(request.content)
        fmt = payload['response_format']
        role, raw = response_for(fmt, payload['messages'], packet, picture, None)
        roles.append(role)
        wires.append(request.content)
        assert b'explicit_recovery' not in request.content and b'v3_explicit_stage_retries' not in request.content
        if role == 'author' and roles.count('author') == 2 and not failed:
            failed = True
            return httpx.Response(503, stream=Body(json.dumps({'error': failure}).encode()))
        envelope = {'model': client.model,
            'structured_output_policy': 'typed-json-object-v1', 'response_format_sha256': response_contract_hash(fmt),
            'choices': [{'message': {'content': json.dumps(raw)}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 25}}
        return httpx.Response(200, stream=Body(json.dumps(envelope).encode()))

    real_http = httpx.AsyncClient
    monkeypatch.setattr('app.modules.ai.managed_luna_client.httpx.AsyncClient',
        lambda **kw: real_http(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr('app.modules.ai.v3.service._practical_output_budget', AsyncMock(return_value=32768))
    monkeypatch.setattr(retry, 'PendingStageJournal', lambda *_: journal)
    monkeypatch.setattr('app.modules.source_editorial_review.service.resolve_pins', AsyncMock(return_value={}))
    args = {'corpus': corpus, 'intent': CourseIntent(), 'generation_client': None, 'extraction_journal': journal,
        'direct_client': client, 'revision_policy': POLICY, 'review_policy': SIMPLE_COURSE_REVIEW_V9_POLICY,
        'route_fingerprint': client.cache_fingerprint()}
    try:
        with pytest.raises(ExtractionOutcomeUnknownError):
            await generate_v3_course_from_corpus(**args)
        assert roles == ['plan', 'author', 'unit-review', 'author']
        pending = checked_entries(fake.job.result)
        digest, entry = next(iter(pending.items()))
        rejection = fake.job.result['v3_response_rejections']['entries'][digest]
        assert rejection['status'] == 503 and rejection['code'] == failure
        assert rejection['route_fingerprint'] == client.cache_fingerprint()
        assert 'raw_base64' not in rejection
        old_claim = copy.deepcopy(fake.values[entry['claim_key']])
        saved = {k: copy.deepcopy(v) for k, v in fake.values.items() if k.startswith('v3-stage-result:')}
        assert len(saved) == 3
        fake.job.status = 'interrupted'
        settings = SimpleNamespace(DEPLOYMENT_ENVIRONMENT='render-development',
            AI_MANAGED_LUNA_QA_DEV_ENABLED=True, AI_DIRECT_LUNA_QA_DEV_ENABLED=False, AI_QA_LUNA_DEV_ENABLED=True)
        async def scalars(statement):
            bound = list(statement.compile().params.values())
            assert QA_TENANT in bound and fake.job_id in bound
            return SimpleNamespace(all=lambda: [SimpleNamespace(generation_key=k, plan_payload=v)
                                               for k, v in fake.plans.items()])
        db = SimpleNamespace(scalars=scalars)
        await retry.authorize_retry(db, fake.job, journal.user_id, settings, retry.UnknownStageRetryRequest(
            stage_sha256=digest, recovery_id=uuid4(), acknowledge_unknown_outcome=True))
        journal.explicit_stage_retries = retry.checked_ledger(fake.job.params)
        inventory = next(iter(journal.explicit_stage_retries['entries'].values()))['completed_stages']
        assert len(inventory) == 3
        fake.job.status = 'running'
        if drift:
            before = list(roles)
            if drift == 'prompt':
                from app.modules.ai.v3 import simple_course_editor_v6 as v6
                original_request = v6.semantic_plan_request
                def changed_request(*args, **kwargs):
                    messages, fmt = original_request(*args, **kwargs)
                    messages[0]['content'] += '\nChanged earlier instruction.'
                    return messages, fmt
                monkeypatch.setattr(v6, 'semantic_plan_request', changed_request)
            elif drift == 'route':
                args['route_fingerprint'] = 'f' * 64
            elif drift == 'cap':
                monkeypatch.setattr('app.modules.ai.v3.service._practical_output_budget', AsyncMock(return_value=16384))
            elif drift == 'cache':
                del fake.values[next(iter(saved))]
            if drift == 'skip':
                for row in inventory.values():
                    await retry.guard_recovery_stage(journal, row['plan'])
                premature = {**next(iter(inventory.values()))['plan'], 'stage': 'review',
                    'group_id': 'practical:simple:review-content:v9:' + packet.fingerprint + ':unit=' + 'f' * 64 + ':output=32768'}
                with pytest.raises(ValueError, match='explicit_stage_retry_request_changed'):
                    await retry.guard_recovery_stage(journal, premature)
            else:
                with pytest.raises((ValueError, ExtractionOutcomeUnknownError)):
                    await generate_v3_course_from_corpus(**args)
            assert roles == before
            return
        result = await generate_v3_course_from_corpus(**args)
        assert len(result.diagnostics['practical_course']['lessons']) == 2
        assert roles == ['plan', 'author', 'unit-review', 'author', 'author', 'unit-review', 'review', 'joint']
        assert wires[3] == wires[4]
        assert all(fake.values[k] == v for k, v in saved.items())
        assert fake.values[entry['claim_key']] == old_claim and entry['result_key'] not in fake.values
        assert checked_entries(fake.job.result) == {}
        before = list(roles)
        cold = await generate_v3_course_from_corpus(**args)
        assert cold.content == result.content and cold.assessment == result.assessment and roles == before
    finally:
        client.close()
