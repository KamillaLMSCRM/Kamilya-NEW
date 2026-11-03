"""Disposable-schema direct typed-review rejection custody; fake transport only."""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Any
from uuid import uuid4


def _contains_private_payload(value: Any, raw: str) -> bool:
    if isinstance(value, dict):
        return 'raw_base64' in value or any(_contains_private_payload(item, raw) for item in value.values())
    if isinstance(value, list):
        return any(_contains_private_payload(item, raw) for item in value)
    return isinstance(value, str) and (raw in value or base64.b64encode(raw.encode()).decode() in value)


async def exercise(owner: Any, runtime: Any, schema: str, tenant: Any, *, enabled: bool = False) -> None:
    if not enabled:
        raise RuntimeError('direct_bucket_gate_disabled')
    import ai_generation_checkpoint_dev_check as canonical
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.modules.ai.delivery_ownership import delivery_id
    from app.modules.ai.direct_luna_responses_client import DirectLunaResponsesClient
    from app.modules.ai.direct_luna_responses_contract import COUNT_ENDPOINT, GENERATION_ENDPOINT
    from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
    from app.modules.ai.v3.managed_rejection_quarantine import KEY, private_key, private_plan
    from app.modules.ai.v3.owned_source_context import OwnedSourceContext
    from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
    from app.modules.ai.v3.pending_stage_transactions import has_pending
    from app.modules.ai.v3.revision_policy import POLICY, REVIEW_POLICY, stamp_policy
    from app.modules.ai.v3.stage_checkpoint import _digest, stage_once, stage_plan
    from app.modules.ai.v3.typed_review_buckets import BUCKETS, build_typed_review_format

    canonical.validate_schema(schema)
    job, actor, document = str(uuid4()), uuid4(), uuid4()
    content = 'Synthetic direct bucket custody fixture ' + job
    source_hash = hashlib.sha256(content.encode()).hexdigest()
    params = {'documents': [str(document)], 'source_analysis': stamp_policy({'generation_engine': 'evidence_v3'}),
              'generation_reservation_required': True, 'generation_reservation_released': False}
    async with owner.begin() as conn:
        await conn.execute(text(f'''INSERT INTO "{schema}".documents
            (id,tenant_id,uploaded_by,title,filename,content_type,file_size,category,content_sha256,lifecycle_status)
            VALUES(:d,:t,:u,'synthetic','synthetic.txt','text/plain',:size,'general',:sha,'active')'''),
            {'d': document, 't': tenant, 'u': actor, 'size': len(content), 'sha': source_hash})
        await conn.execute(text(f'''INSERT INTO "{schema}".ai_jobs (id,tenant_id,user_id,status,params,result)
            VALUES(:j,:t,:u,'running',CAST(:p AS json),CAST(:r AS json))'''),
            {'j': job, 't': tenant, 'u': actor, 'p': json.dumps(params), 'r': '{}'})
    sessions = async_sessionmaker(runtime, expire_on_commit=False)
    doc = DirectSourceDocument(str(document), 'synthetic', 'synthetic.txt', 'general',
                               'document:' + source_hash, (), source_text=content)
    corpus = DirectSourceCorpus(str(tenant), (doc,), len(content), 0)
    journal = PendingStageJournal(str(tenant), actor, job, sessions)
    source = OwnedSourceContext(corpus, journal, tenant, actor, job, (str(document),))
    journal.expected_revision_policy, journal.expected_revision_actor = POLICY, actor
    journal.review_policy_bound, journal.expected_review_policy = True, REVIEW_POLICY
    journal.expected_revision_source = source
    journal.expected_revision_plan = {'schema': 'v3-stage-checkpoint-v1', 'tenant_id': str(tenant),
                                      'job_id': job, 'source_sha256': source_hash}
    async def verify(session: Any, active: Any, plan: dict[str, Any]) -> bool:
        return (active.user_id == actor and active.params.get('documents') == [str(document)]
                and await source.verify_locked(session, active, plan) is True)
    journal.verify_source = verify
    client = DirectLunaResponsesClient(api_key='synthetic-only', tenant_id=tenant, user_id=actor, job_id=job)
    expected = {method: [] for method in BUCKETS}
    expected['review_answer'] = ['a' * 64]
    fmt = build_typed_review_format(expected)
    wrong = {bucket: [] for bucket in BUCKETS.values()}
    wrong['answer_reviews'] = [{'id': 'a' * 64, 'review': {'verdict': 'PASS', 'factual_score': 5,
        'alignment_score': 5, 'didactic_score': 5, 'summary': 'synthetic', 'defects': []}}]
    raw = json.dumps({'model': 'gpt-6-luna', 'status': 'completed', 'output': [{'type': 'message',
        'role': 'assistant', 'status': 'completed', 'content': [{'type': 'output_text', 'text': json.dumps(wrong)}]}],
        'usage': {'input_tokens': 3, 'output_tokens': 2}}, ensure_ascii=False, indent=2)
    calls: list[str] = []
    async def fake_post(endpoint: str, _payload: dict[str, Any], *, stage_id: str | None = None) -> str:
        calls.append(endpoint)
        if endpoint == COUNT_ENDPOINT:
            return json.dumps({'object': 'response.input_tokens', 'input_tokens': 3})
        if endpoint == GENERATION_ENDPOINT and stage_id is not None:
            return raw
        raise AssertionError('direct_bucket_unexpected_transport')
    client._post = fake_post
    messages = [{'role': 'user', 'content': 'synthetic'}]
    async def forbidden() -> dict[str, Any]:
        raise AssertionError('direct_bucket_fallback_called')
    args = dict(journal=journal, stage='review', group_id='batched-review:synthetic', source_sha256=source_hash,
                route_fingerprint=client.cache_fingerprint(), messages=messages, response_format=fmt,
                invoke=forbidden, direct_client=client, direct_max_output_tokens=100)
    token = delivery_id.set(job)
    cold_client = None
    try:
        try:
            await stage_once(**args)
        except ExtractionOutcomeUnknownError:
            pass
        else:
            raise AssertionError('direct_bucket_wrong_shape_accepted')
        plan = stage_plan(journal, stage='review', group_id='batched-review:synthetic', source_sha256=source_hash,
                          route_fingerprint=client.cache_fingerprint(), messages=messages, response_format=fmt)
        digest = _digest(plan)
        async with sessions() as session:
            await canonical.set_tenant(session, tenant)
            row = (await session.execute(text(f'SELECT result,params,course_id FROM "{schema}".ai_jobs WHERE id=:j'),
                                         {'j': job})).one()
            if not has_pending(row.result) or row.params.get('generation_reservation_released') is not False or row.course_id is not None:
                raise AssertionError('direct_bucket_pending_or_accounting_changed')
            if KEY not in row.result or _contains_private_payload(row.result, raw):
                raise AssertionError('direct_bucket_reference_invalid')
            await journal.lock_owned_session(session)
            receipt = await journal.read_owned_value_in_session(session, private_key(digest), private_plan(plan))
            saved = await journal.read_owned_value_in_session(session, 'v3-stage-result:' + digest, plan)
            if saved is not None:
                raise AssertionError('direct_bucket_result_completed')
        if (not receipt or base64.b64decode(receipt['raw_base64'], validate=True) != raw.encode()
                or receipt.get('body_sha256') != hashlib.sha256(raw.encode()).hexdigest()
                or receipt.get('configured_model') != 'gpt-6-luna' or receipt.get('accepted') is not False
                or receipt.get('complete_http_response') is not True or receipt.get('status') != 200):
            raise AssertionError('direct_bucket_private_receipt_invalid')
        cold_journal = PendingStageJournal(str(tenant), actor, job, sessions, verify_source=verify)
        cold_journal.expected_revision_policy, cold_journal.expected_revision_actor = POLICY, actor
        cold_journal.review_policy_bound, cold_journal.expected_review_policy = True, REVIEW_POLICY
        cold_journal.expected_revision_source, cold_journal.expected_revision_plan = source, journal.expected_revision_plan
        cold_client = DirectLunaResponsesClient(api_key='synthetic-only', tenant_id=tenant, user_id=actor, job_id=job)
        async def forbidden_post(*_args: Any, **_kwargs: Any) -> str:
            raise AssertionError('direct_bucket_cold_transport_called')
        cold_client._post = forbidden_post
        try:
            await stage_once(**(args | {'journal': cold_journal, 'direct_client': cold_client}))
        except ExtractionOutcomeUnknownError:
            pass
        else:
            raise AssertionError('direct_bucket_cold_not_held')
        if calls != [COUNT_ENDPOINT, GENERATION_ENDPOINT]:
            raise AssertionError('direct_bucket_transport_count_invalid')
    finally:
        delivery_id.reset(token)
        client.close()
        if cold_client is not None:
            cold_client.close()
