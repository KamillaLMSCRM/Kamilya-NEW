import io
from types import SimpleNamespace

import pytest

from scripts.dev import run_dev_asus_bridge as bridge
from scripts.ops import reverse_model_stream as relay


def test_paramiko_none_return_writer_still_completes_framed_handshake():
    class Channel:
        def __init__(self):
            self.data = bytearray()
        def sendall(self, data):
            self.data.extend(data)
    channel = Channel()
    wire = relay.HEADER.pack(relay.READY, 0, 5) + b'nonce'
    relay.local_client(io.BytesIO(wire), bridge.ChannelWriter(channel), expected_nonce='nonce')
    assert bytes(channel.data) == wire


@pytest.mark.parametrize('field,value', [('container','kamilya-blue-api-1'),
    ('image','sha256:'+'b'*64), ('release','master'), ('lifetime',7201)])
def test_plan_rejects_ambient_or_unbounded_targets(field, value):
    args = SimpleNamespace(container='a'*64,image='ghcr.io/kamillalmscrm/kamilya-api@sha256:'+'b'*64,
                           release='c'*40,lifetime=60,probe_only=True)
    setattr(args, field, value)
    with pytest.raises(ValueError):
        bridge.plan_for(args)


def test_remote_payload_is_dev_scoped_and_bounded():
    plan = {'release':'c'*40,'lifetime_seconds':60}
    text = bridge.payload(plan, 'test-nonce').decode()
    assert "'vm-development-worker'" in text
    assert "os.getenv('RELEASE_SHA')" in text
    assert 'lifetime_seconds=60' in text
    assert 'api_key' not in text and 'password' not in text
