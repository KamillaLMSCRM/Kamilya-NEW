import hashlib
from pathlib import Path

import pytest

from scripts.ops import vm126_dev_worker_env_receiver as receiver
from scripts.ops import vm126_dev_worker_runtime as runtime
from scripts.ops import vm126_dev_worker_stage as stage
from scripts.ops.test_vm126_dev_worker_env import RELEASE, native_payload


@pytest.fixture(autouse=True)
def synthetic_project(monkeypatch):
    monkeypatch.setattr(receiver, 'DATABASE_PROJECT_FINGERPRINT', hashlib.sha256(b'devproject').hexdigest())


def source():
    values = dict(line.split('=', 1) for line in native_payload().decode().splitlines())
    values['DEPLOYMENT_ENVIRONMENT'] = 'render-development-worker'
    return values


def test_explicit_local_payload_and_v6_receiver_are_bound():
    body = receiver.build_payload_from_render_values(source(), RELEASE, native_mode=True, local_deepseek=True)
    assert b'AI_QA_LOCAL_DEEPSEEK_DEV_ENABLED=true\n' in body
    assert receiver.validate_payload(body, RELEASE, hashlib.sha256(body).hexdigest())
    data = Path(receiver.__file__).read_bytes()
    assert hashlib.sha256(data).hexdigest() == stage.RECEIVER_SHA_V6 == runtime.RECEIVER_SHA_V6
    values = dict(line.split('=', 1) for line in body.decode().splitlines())
    assert runtime.receiver_identity(values, data) is False


def test_existing_native_payload_does_not_acquire_local_route():
    body = receiver.build_payload_from_render_values(source(), RELEASE, native_mode=True)
    assert b'AI_QA_LOCAL_DEEPSEEK_DEV_ENABLED' not in body


@pytest.mark.parametrize('value', [True, 1, 'false', 'yes'])
def test_local_flag_cannot_be_added_to_legacy_or_malformed_mode(value):
    body = native_payload() + f'AI_QA_LOCAL_DEEPSEEK_DEV_ENABLED={value}\n'.encode()
    with pytest.raises(ValueError, match='local_deepseek_mode_invalid'):
        receiver.validate_payload(body, RELEASE, hashlib.sha256(body).hexdigest())


def test_builder_local_requires_native_mode():
    with pytest.raises(ValueError, match='local_deepseek_mode_invalid'):
        receiver.build_payload_from_render_values(source(), RELEASE, local_deepseek=True)
