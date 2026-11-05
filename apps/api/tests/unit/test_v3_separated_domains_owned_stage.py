"""Versioned explanation-domain formats use the existing owned stage routes."""
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.modules.ai.managed_luna_client import ManagedLunaClient
from app.modules.ai.v3.practical_arbitration import arbitration_format, arbitration_messages
from app.modules.ai.v3.practical_atomic_audit import atomic_audit_format, atomic_audit_messages
from app.modules.ai.v3.practical_curriculum import curriculum_format
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.stage_checkpoint import stage_once
from tests.unit.test_direct_luna_owned_stage import setup
from tests.unit.test_v3_practical_claim_evidence import response as audit_response
from tests.unit.test_v3_practical_materiality import decision, issue, row, value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['direct', 'managed'])
@pytest.mark.parametrize('kind', ['audit', 'arbiter'])
async def test_explanation_domain_owned_stage_fences_and_cold_replay(case, monkeypatch, provider, kind):
    _, packet, course = case
    fake, journal, client, _, _ = setup()
    if provider == 'managed':
        client = ManagedLunaClient(base_url='http://127.0.0.1:18999/v1', api_key='synthetic',
            tenant_id=UUID(journal.tenant_id), user_id=journal.user_id, job_id=journal.job_id,
            credential_revision='synthetic', model='gpt-6-luna')
    view = PracticalModelView(packet)
    if kind == 'audit':
        opts = {'typed_findings': True, 'strict_owners': True, 'claim_evidence': True, 'separate_domains': True}
        fmt = atomic_audit_format(packet, course, **opts)
        messages = atomic_audit_messages(packet, course, model_view=view, **opts)
        result = audit_response(packet, course)
        group = 'practical:source-audit:' + 'a' * 64
        wrong_group = 'practical:arbitrate:' + 'a' * 64
    else:
        item = issue(packet, 'explain', 'question', 'q1', 'EXPLANATION_VALIDITY')
        opts = {'selectors': True, 'typed_findings': True, 'materiality_review': True, 'separate_domains': True}
        fmt = arbitration_format(packet, course, decision(item), **opts)
        messages = arbitration_messages(packet, course, decision(item), model_view=view, **opts)
        result = value(packet, course, [row(item, verdict='MATERIAL_ERROR')])
        group = 'practical:arbitrate:' + 'a' * 64
        wrong_group = 'practical:source-audit:' + 'a' * 64
    wire = view.encode(result)
    prepare = AsyncMock(return_value=object())
    invoke = AsyncMock(return_value=SimpleNamespace(content=wire, model='gpt-6-luna',
        usage=SimpleNamespace(input_tokens=12, output_tokens=6, cached_input_tokens=None, reasoning_tokens=None)))
    monkeypatch.setattr(client, 'prepare', prepare)
    monkeypatch.setattr(client, 'invoke', invoke)
    args = dict(journal=journal, direct_client=client, stage='review', group_id=group,
        source_sha256='b' * 64, route_fingerprint=client.cache_fingerprint(), messages=messages,
        response_format=view.schema(fmt), direct_max_output_tokens=128,
        response_validator=lambda response: None, invoke=AsyncMock())
    for wrong in ({'stage': 'lesson'}, {'stage': 'repair'}, {'group_id': wrong_group},
                  {'response_format': view.schema(curriculum_format(packet))}):
        with pytest.raises(ValueError):
            await stage_once(**{**args, **wrong})
    prepare.assert_not_awaited()
    invoke.assert_not_awaited()
    assert not fake.plans
    assert await stage_once(**args) == wire
    assert await stage_once(**{**args, 'journal': copy.copy(journal)}) == wire
    prepare.assert_awaited_once()
    invoke.assert_awaited_once()
    assert any(isinstance(stored, dict) and stored.get('response') == wire and stored.get('direct_metadata')
               for stored in fake.values.values())
