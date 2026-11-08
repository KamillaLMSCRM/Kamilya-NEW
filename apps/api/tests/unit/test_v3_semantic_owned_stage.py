"""New source/teaching formats retain the existing ownership and replay fences."""

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.modules.ai.managed_luna_client import ManagedLunaClient
from app.modules.ai.v3.practical_compact_editorial_contract import (
    compact_editorial_review_format,
    compact_editorial_verification_format,
)
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_rule_editorial_contract import (
    rule_editorial_review_format,
    rule_editorial_verification_format,
)
from app.modules.ai.v3.practical_source_semantics import (
    compile_source_semantics,
    source_completeness_format,
    source_semantics_format,
    source_semantics_verification_format,
)
from app.modules.ai.v3.stage_checkpoint import stage_once
from tests.unit.test_direct_luna_owned_stage import setup
from tests.unit.test_v3_compact_editorial_contract import response as compact_response
from tests.unit.test_v3_rule_editorial_contract import case, response
from tests.unit.test_v3_source_semantics import reading, verification


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["direct", "managed"])
@pytest.mark.parametrize("kind", ["reading", "source_verification", "source_completeness", "review", "verification", "compact_review", "compact_verification"])
async def test_source_and_rule_formats_owned_replay_and_stage_fences(monkeypatch, provider, kind):
    packet, course, checked = case()
    initial = compile_source_semantics(reading(packet), packet)
    view = PracticalModelView(packet)
    if kind == "reading":
        fmt, result = source_semantics_format(packet), reading(packet)
        group = "practical:source-semantics:read:v33:" + packet.fingerprint
    elif kind == "source_verification":
        fmt, result = source_semantics_verification_format(packet, initial), verification(packet, initial)
        group = "practical:source-semantics:verify:v33:" + initial["reading_fingerprint"]
    elif kind == "source_completeness":
        fmt = source_completeness_format(packet, checked)
        result = {"source_fingerprint": packet.fingerprint,
            "verified_reading_fingerprint": checked["verified_reading_fingerprint"], "additional_rules": []}
        group = "practical:source-semantics:complete:v33:" + checked["verified_reading_fingerprint"]
    elif kind.startswith('compact_'):
        result = compact_response(packet, course, checked)
        if kind == 'compact_review':
            fmt = compact_editorial_review_format(packet, course, checked)
            group = 'practical:editorial:review:v33:' + 'a' * 64
        else:
            result['resolutions'] = []
            fmt = compact_editorial_verification_format(packet, course, checked, [])
            group = 'practical:editorial:verify:v33:' + 'a' * 64
    else:
        result = response(packet, course, checked)
        if kind == "review":
            fmt = rule_editorial_review_format(packet, course, checked)
            group = "practical:editorial:review:v33:" + "a" * 64
        else:
            result["resolutions"] = []
            fmt = rule_editorial_verification_format(packet, course, checked, [])
            group = "practical:editorial:verify:v33:" + "a" * 64
    fake, journal, client, _, _ = setup()
    if provider == "managed":
        client = ManagedLunaClient(
            base_url="http://127.0.0.1:18999/v1",
            api_key="synthetic",
            tenant_id=UUID(journal.tenant_id),
            user_id=journal.user_id,
            job_id=journal.job_id,
            credential_revision="synthetic",
            model="gpt-6-luna",
        )
    wire = view.encode(result)
    prepare = AsyncMock(return_value=object())
    invoke = AsyncMock(
        return_value=SimpleNamespace(
            content=wire,
            model="gpt-6-luna",
            usage=SimpleNamespace(input_tokens=12, output_tokens=6, cached_input_tokens=None, reasoning_tokens=None),
        )
    )
    monkeypatch.setattr(client, "prepare", prepare)
    monkeypatch.setattr(client, "invoke", invoke)
    options = dict(
        journal=journal,
        direct_client=client,
        stage="review",
        group_id=group,
        source_sha256="b" * 64,
        route_fingerprint=client.cache_fingerprint(),
        messages=[{"role": "user", "content": "Synthetic source evidence"}],
        response_format=view.schema(fmt),
        direct_max_output_tokens=128,
        response_validator=lambda value: None,
        invoke=AsyncMock(),
    )
    for wrong in ({"stage": "lesson"}, {"stage": "repair"}, {"group_id": "practical:wrong:v33:" + "a" * 64}):
        with pytest.raises(ValueError):
            await stage_once(**{**options, **wrong})
    prepare.assert_not_awaited()
    assert not fake.plans
    assert await stage_once(**options) == wire
    assert await stage_once(**{**options, "journal": copy.copy(journal)}) == wire
    prepare.assert_awaited_once()
    invoke.assert_awaited_once()
