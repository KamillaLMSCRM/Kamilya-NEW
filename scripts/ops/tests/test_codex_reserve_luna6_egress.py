"""Fake-stream profile checks; no sockets or real timeout waits."""
import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

PATH = Path(__file__).resolve().parents[3] / 'infra/codex-reserve/egress.py'
spec = importlib.util.spec_from_file_location('luna6_egress_test', PATH)
egress = importlib.util.module_from_spec(spec)
spec.loader.exec_module(egress)


class Reader:
    def __init__(self, upstream=False):
        self.upstream = upstream
        self.sent = False

    async def readuntil(self, _separator):
        return b'CONNECT chatgpt.com:443 HTTP/1.1\r\n\r\n'

    async def read(self, _size):
        if not self.upstream:
            await asyncio.Event().wait()
        if not self.sent:
            self.sent = True
            await asyncio.sleep(0)
            return b'provider-response'
        return b''


class Writer:
    def __init__(self):
        self.data = []
        self.closed = False

    def write(self, data): self.data.append(data)
    async def drain(self): pass
    def close(self): self.closed = True
    async def wait_closed(self): pass


def test_profiles_and_invalid_values():
    assert egress.profile_limits('legacy-luna56') == (120, 135, 150)
    assert egress.profile_limits('luna6') == (300, 305, 310)
    assert egress.Egress().total_seconds == 120 and egress.Ingress().total_seconds == 150
    for profile in ('other', '', None, []):
        with pytest.raises(ValueError, match='connector_profile_invalid'):
            egress.Egress(profile)
        with pytest.raises(ValueError, match='connector_profile_invalid'):
            egress.Ingress(profile)
    with pytest.raises(ValueError):
        egress.destination('CONNECT 127.0.0.1:443 HTTP/1.1')
    assert egress.MAX_TUNNEL_BYTES == 20 * 1024 * 1024


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,expected', [('egress', 300), ('ingress', 310)])
async def test_luna6_outer_budget_and_stream_cleanup(monkeypatch, kind, expected):
    real_timeout = asyncio.timeout
    real_wait_for = asyncio.wait_for
    seen = []
    waits = []
    def clock(seconds):
        seen.append(seconds)
        return real_timeout(seconds)
    monkeypatch.setattr(egress.asyncio, 'timeout', clock)
    async def wait_for(value, timeout):
        waits.append(timeout)
        return await real_wait_for(value, timeout)
    monkeypatch.setattr(egress.asyncio, 'wait_for', wait_for)
    upstream, client = Writer(), Writer()
    monkeypatch.setattr(egress.asyncio, 'open_connection', AsyncMock(return_value=(Reader(True), upstream)))
    monkeypatch.setattr(egress, 'resolve_public', AsyncMock(return_value='8.8.8.8'))
    obj = egress.Egress('luna6') if kind == 'egress' else egress.Ingress('luna6')
    await obj.handle(Reader(), client)
    assert expected in seen and b'provider-response' in client.data
    if kind == 'ingress':
        assert 305 in waits and 5 in waits and 3 in waits
    assert obj.active == 0 and client.closed and upstream.closed


@pytest.mark.asyncio
async def test_luna6_total_timeout_cancels_pumps_and_closes(monkeypatch):
    real_timeout = asyncio.timeout
    def clock(seconds):
        return real_timeout(0 if seconds == 300 else seconds)
    monkeypatch.setattr(egress.asyncio, 'timeout', clock)
    upstream, client = Writer(), Writer()
    monkeypatch.setattr(egress.asyncio, 'open_connection', AsyncMock(return_value=(Reader(), upstream)))
    monkeypatch.setattr(egress, 'resolve_public', AsyncMock(return_value='8.8.8.8'))
    obj = egress.Egress('luna6')
    await obj.handle(Reader(), client)
    assert obj.active == 0 and client.closed and upstream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['egress', 'ingress'])
async def test_luna6_connection_limit_never_opens_upstream(monkeypatch, kind):
    connection = AsyncMock(side_effect=AssertionError('unexpected connection'))
    monkeypatch.setattr(egress.asyncio, 'open_connection', connection)
    obj = egress.Egress('luna6') if kind == 'egress' else egress.Ingress('luna6')
    obj.active = 8
    writer = Writer()
    await obj.handle(Reader(), writer)
    connection.assert_not_awaited()
    assert obj.active == 8 and writer.closed
