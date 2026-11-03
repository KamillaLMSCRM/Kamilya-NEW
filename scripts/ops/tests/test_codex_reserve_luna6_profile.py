"""Closed new CLI profile without changing the existing default model wire."""
import asyncio
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
WARNING = ('Code Mode is unavailable because code-mode host is disabled. '
           'Code mode will fail closed; enable `features.code_mode_host` and install `codex-code-mode-host`.')


def runner(tmp_path, *, timeout=285, model='gpt-6-luna', version='codex-cli 0.166.0', module=None):
    if module is None:
        spec = importlib.util.spec_from_file_location('luna6_profile_runner', ROOT / 'infra/codex-reserve/runner.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    binary = Path(sys.executable)
    return module, module.CodexRunner(binary, tmp_path, hashlib.sha256(binary.read_bytes()).hexdigest(),
        timeout=timeout, model=model, cli_version=version)


def stream(*, warning=True, late=False, message=WARNING, tool=False):
    first = {'type': 'thread.started', 'thread_id': 'synthetic'}
    warn = {'type': 'item.completed', 'item': {'id': 'item_0', 'type': 'error', 'message': message}}
    started = {'type': 'turn.started'}
    answer = {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps({'content': 'answer'})}}
    events = [first]
    if warning and not late:
        events.append(warn)
    events += [started, answer]
    if warning and late:
        events.append(warn)
    if tool:
        events.append({'type': 'item.completed', 'item': {'type': 'command_execution', 'command': 'forbidden'}})
    events.append({'type': 'turn.completed', 'usage': {'input_tokens': 50, 'output_tokens': 10}})
    return b'\n'.join(json.dumps(e).encode() for e in events)


def test_luna6_high_profile_binds_model_and_deadline_before_dispatch(tmp_path):
    module, subject = runner(tmp_path)
    command = subject.command(tmp_path / 'schema.json', reasoning_effort='high')
    assert command[command.index('--model') + 1] == 'gpt-6-luna'
    assert 'model_reasoning_effort="high"' in command and 'features.code_mode=false' in command
    deadlines = []

    async def execute(*_args, **kwargs):
        deadlines.append(kwargs['timeout'])
        return 0, stream(), b''

    subject._run = execute
    value = asyncio.run(subject.complete({'model': 'gpt-6-luna', 'reasoning_effort': 'high',
        'messages': [{'role': 'user', 'content': 'synthetic'}], 'max_tokens': 100}))
    assert value['model'] == 'gpt-6-luna' and value['usage']['total_tokens'] == 60
    assert len(deadlines) == 1 and 280 < deadlines[0] <= 285
    with pytest.raises(module.RunnerError, match='not_configured'):
        runner(tmp_path, timeout=301, module=module)


@pytest.mark.parametrize('change', [{'late': True}, {'message': 'Unknown startup failure'}, {'tool': True}])
def test_new_profile_never_tolerates_runtime_errors_or_tools(tmp_path, change):
    module, subject = runner(tmp_path)
    with pytest.raises(module.RunnerError, match='tool_use_rejected'):
        subject._profile_result(stream(**change))


def test_legacy_profile_remains_bounded_and_rejects_high(tmp_path):
    module, subject = runner(tmp_path, timeout=60, model='gpt-5.6-luna')
    with pytest.raises(module.RunnerError, match='invalid_input'):
        subject.command(tmp_path / 'schema.json', reasoning_effort='high')
    with pytest.raises(module.RunnerError, match='not_configured'):
        runner(tmp_path, timeout=121, model='gpt-5.6-luna', module=module)
    command = subject.command(tmp_path / 'schema.json')
    assert command.count('features.code_mode=false') == 1


def test_new_profile_readiness_rejects_wrong_cli_version(tmp_path):
    module, subject = runner(tmp_path)
    subject._run = AsyncMock(return_value=(0, b'codex-cli 0.146.1', b''))
    with pytest.raises(module.RunnerError, match='protocol_mismatch'):
        asyncio.run(subject.readiness())
    subject._run.assert_awaited_once()


def test_compose_passes_one_matching_fixed_default_profile_without_resource_changes():
    data = yaml.safe_load((ROOT / 'infra/codex-reserve/compose.yml').read_text(encoding='utf-8'))
    connector, egress = data['services']['connector'], data['services']['egress']
    expression = '${CODEX_CONNECTOR_PROFILE:-legacy-luna56}'
    assert connector['environment']['CODEX_CONNECTOR_PROFILE'] == expression
    assert egress['environment'] == {'CODEX_CONNECTOR_PROFILE': expression}
    assert connector.get('ports') is None and egress['ports'] == ['${CODEX_BIND_IP:-127.0.0.1}:18999:18999']
    assert connector['mem_limit'] == '512m' and connector['cpus'] == 0.5 and connector['pids_limit'] == 64
    assert egress['mem_limit'] == '128m' and egress['cpus'] == 0.25 and egress['pids_limit'] == 32
    assert connector['read_only'] is True and egress['read_only'] is True
    assert connector['cap_drop'] == ['ALL'] and egress['cap_drop'] == ['ALL']
    assert not egress.get('volumes') and data['networks']['codex-private']['internal'] is True
