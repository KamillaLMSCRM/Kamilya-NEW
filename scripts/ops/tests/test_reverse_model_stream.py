import io
import queue
import socket
import threading

import pytest

from scripts.ops import reverse_model_stream as relay


class Fragmented(io.BytesIO):
    def read(self, count=-1):
        return super().read(min(count, 2))


def frame(kind, ident, data=b''):
    return relay.HEADER.pack(kind, ident, len(data)) + data


def test_partial_frames_and_binary_unicode():
    payload = 'тест 🚀'.encode() + b'\0\xff'
    assert relay.read_frame(Fragmented(frame(relay.DATA, 42, payload))) == (relay.DATA, 42, payload)


@pytest.mark.parametrize('data', [frame(99, 1), relay.HEADER.pack(relay.DATA, 1, 65537),
    frame(relay.DATA, 0, b'x'), frame(relay.OPEN, 1, b'x'), frame(relay.DATA, 1)])
def test_malformed_frame_fails_closed(data):
    with pytest.raises(relay.ProtocolError):
        relay.read_frame(io.BytesIO(data))


def test_local_handshake_nonce_and_eof():
    output = io.BytesIO()
    relay.local_client(io.BytesIO(frame(relay.READY, 0, b'nonce')), output, expected_nonce='nonce')
    assert relay.read_frame(io.BytesIO(output.getvalue())) == (relay.READY, 0, b'nonce')
    with pytest.raises(relay.ProtocolError):
        relay.local_client(io.BytesIO(frame(relay.READY, 0, b'wrong')), io.BytesIO(), expected_nonce='nonce')


def test_unknown_connection_rejected():
    incoming = frame(relay.READY, 0, b'n') + frame(relay.DATA, 2, b'x')
    with pytest.raises(relay.ProtocolError):
        relay.local_client(io.BytesIO(incoming), io.BytesIO(), expected_nonce='n')


def test_connection_limit_and_closed_id_race():
    session = relay._Session(io.BytesIO(), io.BytesIO())
    left, right = socket.socketpair()
    session.add(1, left)
    session.close_one(1)
    session.receive(relay.DATA, 1, b'in flight')
    session.receive(relay.CLOSE, 1, b'')
    with pytest.raises(relay.ProtocolError):
        session.receive(relay.DATA, 2, b'unknown')
    right.close()


def test_eight_connection_cap_and_monotonic_ids():
    session = relay._Session(io.BytesIO(), io.BytesIO())
    peers = []
    for ident in range(1, 9):
        local, peer = socket.socketpair()
        peers.append(peer)
        session.add(ident, local)
    overflow, peer = socket.socketpair()
    with pytest.raises(relay.ProtocolError):
        session.add(9, overflow)
    peer.close()
    session.close_one(1)
    invalid, peer = socket.socketpair()
    with pytest.raises(relay.ProtocolError):
        session.add(10, invalid)
    peer.close()
    session.stop()
    for peer in peers:
        peer.close()


def test_two_connections_isolated_and_eof_cleans_up():
    transport_a, transport_b = socket.socketpair()
    transport_a.settimeout(3)
    transport_b.settimeout(3)
    incoming = transport_a.makefile('rb')
    outgoing = transport_a.makefile('wb', buffering=0)
    peer_read = transport_b.makefile('rb')
    peer_write = transport_b.makefile('wb', buffering=0)
    peers = queue.Queue()
    endpoints = []
    def factory(address, timeout):
        assert address == relay.UPSTREAM and timeout == 5
        local, peer = socket.socketpair()
        peer.settimeout(3)
        peers.put(peer)
        endpoints.append(local)
        return local
    failures = []
    def run():
        try:
            relay.local_client(incoming, outgoing, expected_nonce='test', lifetime_seconds=10, _socket_factory=factory)
        except Exception as exc:
            failures.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    peer_write.write(frame(relay.READY, 0, b'test'))
    assert relay.read_frame(peer_read) == (relay.READY, 0, b'test')
    peer_write.write(frame(relay.OPEN, 1) + frame(relay.OPEN, 2))
    a, b = peers.get(timeout=3), peers.get(timeout=3)
    peer_write.write(frame(relay.DATA, 1, b'alpha') + frame(relay.DATA, 2, b'beta'))
    assert a.recv(5) == b'alpha'
    assert b.recv(4) == b'beta'
    a.sendall(b'one')
    b.sendall(b'two')
    received = {relay.read_frame(peer_read), relay.read_frame(peer_read)}
    assert received == {(relay.DATA, 1, b'one'), (relay.DATA, 2, b'two')}
    transport_b.shutdown(socket.SHUT_RDWR)
    thread.join(3)
    assert not thread.is_alive() and not failures
    assert a.recv(1) == b'' and b.recv(1) == b''
    a.close(); b.close()
    peer_read.close(); peer_write.close(); incoming.close(); outgoing.close()
    transport_a.close(); transport_b.close()


def test_remote_listener_handshake_and_half_close(monkeypatch):
    transport_a, transport_b = socket.socketpair()
    remote_socket, app = socket.socketpair()
    upstream_socket, upstream = socket.socketpair()
    app.settimeout(3)
    upstream.settimeout(3)
    class Listener:
        def __init__(self):
            self.pending = queue.Queue()
            self.pending.put(remote_socket)
            self.closed = False
        def bind(self, address):
            assert address == relay.LISTEN
        def listen(self, count):
            assert count == relay.MAX_CONNECTIONS
        def settimeout(self, value):
            pass
        def accept(self):
            if self.closed:
                raise OSError('closed')
            try:
                return self.pending.get(timeout=0.05), ('synthetic', 0)
            except queue.Empty:
                raise socket.timeout()
        def close(self):
            self.closed = True
    listener = Listener()
    monkeypatch.setattr(relay.socket, 'socket', lambda *args: listener)
    streams = [transport_a.makefile('rb'), transport_a.makefile('wb', buffering=0),
               transport_b.makefile('rb'), transport_b.makefile('wb', buffering=0)]
    failures = []
    def run(fn, *args, **kwargs):
        try:
            fn(*args, **kwargs)
        except Exception as exc:
            failures.append(exc)
    r = threading.Thread(target=run, args=(relay.remote_server, *streams[:2]),
                         kwargs={'session_nonce':'nonce', 'lifetime_seconds':5})
    l = threading.Thread(target=run, args=(relay.local_client, *streams[2:]),
                         kwargs={'expected_nonce':'nonce', 'lifetime_seconds':5,
                                 '_socket_factory':lambda address, timeout: upstream_socket})
    r.start(); l.start()
    app.sendall(b'request')
    app.shutdown(socket.SHUT_WR)
    assert upstream.recv(7) == b'request'
    assert upstream.recv(1) == b''
    upstream.sendall('ответ'.encode())
    upstream.shutdown(socket.SHUT_WR)
    assert app.recv(32) == 'ответ'.encode()
    assert app.recv(1) == b''
    transport_b.shutdown(socket.SHUT_RDWR)
    transport_a.shutdown(socket.SHUT_RDWR)
    r.join(3); l.join(3)
    assert not r.is_alive() and not l.is_alive()
    assert all(isinstance(exc, OSError) for exc in failures)
    assert listener.closed
    app.close(); upstream.close()
    for stream in streams:
        stream.close()
    transport_a.close(); transport_b.close()
