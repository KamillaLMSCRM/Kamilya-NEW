"""The gate is inert without the exact isolated-DEV execution contract."""
import importlib.util
from pathlib import Path
from uuid import UUID, uuid4

import pytest


@pytest.fixture
def gate():
    path = Path(__file__).resolve().parents[1] / 'v3_retained_author_replay_dev_gate.py'
    spec = importlib.util.spec_from_file_location('retained_author_gate', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_offline_default_never_executes(gate, monkeypatch, capsys):
    monkeypatch.setattr(gate, 'execute_candidate', lambda *_args: pytest.fail('unexpected execution'))
    assert gate.main([]) == 0
    output = capsys.readouterr().out
    assert 'OFFLINE_ONLY' in output and '0186' in output


def test_partial_execution_contract_is_rejected(gate, monkeypatch):
    monkeypatch.setattr(gate, 'execute_candidate', lambda *_args: pytest.fail('unexpected execution'))
    assert gate.main(['--execute', '--expected-public-revision', '0186']) == 2


def test_fixture_stage_group_matches_configured_output_limit(gate):
    assert gate.AUTHOR_OUTPUT_TOKENS == 16384
    assert gate.AUTHOR_GROUP == f'practical:author:editorial:v31:output={gate.AUTHOR_OUTPUT_TOKENS}'


@pytest.mark.asyncio
async def test_exercise_requires_explicit_enable(gate):
    with pytest.raises(RuntimeError, match='gate_not_enabled'):
        await gate.exercise(None, None, '', None, None, '', '', [])


def test_asyncpg_actor_is_normalized_before_strict_rejection_constructor(gate):
    from asyncpg.pgproto.pgproto import UUID as AsyncpgUUID
    from app.modules.ai.managed_response_rejection import ManagedResponseRejectedError

    tenant, actor = uuid4(), AsyncpgUUID(str(uuid4()))
    kwargs = dict(raw=b'{}', tenant_id=tenant, job_id=str(uuid4()), stage='a' * 64,
        route_fingerprint='b' * 64, wire_request_sha256='c' * 64,
        phase='structured_shape', cause=ValueError('synthetic'))
    with pytest.raises(ValueError, match='managed_rejection_invalid'):
        ManagedResponseRejectedError(user_id=actor, **kwargs)
    normalized = gate.fixture_actor_uuid(actor)
    assert type(normalized) is UUID and str(normalized) == str(actor)
    ManagedResponseRejectedError(user_id=normalized, **kwargs)


@pytest.mark.asyncio
async def test_fixture_failure_diagnostics_do_not_include_exception_values(gate, monkeypatch):
    async def fail(*_args):
        gate._STAGE = 'fixture_job'
        raise ValueError('private SQL or customer value')
    monkeypatch.setattr(gate, '_exercise', fail)
    with pytest.raises(ValueError):
        await gate.exercise(None, None, '', None, None, '', '', [])
    assert gate._FAILURE_DIAGNOSTIC == {'stage': 'fixture_job', 'error_class': 'ValueError'}
