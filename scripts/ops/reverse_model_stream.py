"""Bounded, binary reverse stream for a single owner-controlled SSH session."""
from __future__ import annotations

import argparse
import socket
import struct
import sys
import threading

LISTEN = ('127.0.0.1', 18890)
UPSTREAM = ('10.66.66.20', 8888)
MAX_FRAME = 65536
MAX_CONNECTIONS = 8
READY, OPEN, DATA, EOF, CLOSE = range(1, 6)
HEADER = struct.Struct('!BII')


class ProtocolError(ValueError):
    pass


def _read_exact(stream, length):
    parts = []
    while length:
        chunk = stream.read(length)
        if not chunk:
            raise EOFError('stream ended')
        parts.append(chunk)
        length -= len(chunk)
    return b''.join(parts)


def read_frame(stream):
    kind, ident, size = HEADER.unpack(_read_exact(stream, HEADER.size))
    if kind not in (READY, OPEN, DATA, EOF, CLOSE) or size > MAX_FRAME:
        raise ProtocolError('invalid frame')
    if (kind == READY) != (ident == 0):
        raise ProtocolError('invalid frame identifier')
    if kind in (OPEN, EOF, CLOSE) and size or kind in (READY, DATA) and not size:
        raise ProtocolError('invalid frame length')
    return kind, ident, _read_exact(stream, size)


class _Session:
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer
        self.write_lock = threading.Lock()
        self.lock = threading.RLock()
        self.stopped = threading.Event()
        self.sockets = {}
        self.last_id = 0
        self.listener = None
        self.error = None

    def send(self, kind, ident, data=b''):
        if len(data) > MAX_FRAME:
            raise ProtocolError('oversize output')
        with self.write_lock:
            frame = HEADER.pack(kind, ident, len(data)) + data
            while frame:
                count = self.writer.write(frame)
                if not count:
                    raise OSError('stream write failed')
                frame = frame[count:]
            self.writer.flush()

    def close_one(self, ident, *, notify=False):
        with self.lock:
            item = self.sockets.pop(ident, None)
            if item is None:
                return
        try:
            item[0].shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        item[0].close()
        if notify and not self.stopped.is_set():
            self.send(CLOSE, ident)

    def stop(self):
        self.stopped.set()
        if self.listener is not None:
            self.listener.close()
        with self.lock:
            ids = list(self.sockets)
        for ident in ids:
            self.close_one(ident)

    def pump(self, ident, sock):
        try:
            while not self.stopped.is_set():
                try:
                    data = sock.recv(MAX_FRAME)
                except socket.timeout:
                    continue
                with self.lock:
                    item = self.sockets.get(ident)
                    if item is None:
                        return
                    if not data:
                        item[1] = True
                        self.send(EOF, ident)
                        if item[2]:
                            self.close_one(ident)
                        return
                    self.send(DATA, ident, data)
        except OSError:
            try:
                self.close_one(ident, notify=True)
            except OSError:
                self.stop()

    def add(self, ident, sock):
        with self.lock:
            if self.stopped.is_set() or ident != self.last_id + 1 or len(self.sockets) >= MAX_CONNECTIONS:
                sock.close()
                raise ProtocolError('invalid connection sequence or limit')
            sock.settimeout(5)
            self.last_id = ident
            self.sockets[ident] = [sock, False, False]
        threading.Thread(target=self.pump, args=(ident, sock), daemon=True).start()

    def receive(self, kind, ident, data):
        with self.lock:
            item = self.sockets.get(ident)
            if item is None:
                # Frames sent before the peer observed CLOSE are harmless in flight.
                if 0 < ident <= self.last_id and kind in (DATA, EOF, CLOSE):
                    return
                raise ProtocolError('unknown connection')
            if kind == DATA:
                if item[2]:
                    raise ProtocolError('data after eof')
                try:
                    item[0].sendall(data)
                except OSError:
                    self.close_one(ident, notify=True)
            elif kind == EOF:
                if item[2]:
                    raise ProtocolError('duplicate eof')
                item[2] = True
                try:
                    item[0].shutdown(socket.SHUT_WR)
                except OSError:
                    self.close_one(ident, notify=True)
                    return
                if item[1]:
                    self.close_one(ident)
            elif kind == CLOSE:
                self.close_one(ident)
            else:
                raise ProtocolError('unexpected frame')


def _run(session, handler, lifetime_seconds):
    if not isinstance(lifetime_seconds, (int, float)) or lifetime_seconds <= 0:
        raise ValueError('invalid lifetime')
    def consume():
        try:
            while not session.stopped.is_set():
                handler(*read_frame(session.reader))
        except EOFError:
            pass
        except (OSError, ProtocolError) as exc:
            session.error = exc
        finally:
            session.stop()
    threading.Thread(target=consume, daemon=True).start()
    session.stopped.wait(lifetime_seconds)
    session.stop()
    if session.error:
        raise session.error


def _nonce(value):
    if not isinstance(value, str) or not value or len(value.encode('utf-8')) > MAX_FRAME:
        raise ValueError('invalid nonce')
    return value.encode('utf-8')


def remote_server(reader, writer, *, session_nonce, lifetime_seconds=7200):
    session = _Session(reader, writer)
    nonce = _nonce(session_nonce)
    session.send(READY, 0, nonce)
    def accept_loop():
        try:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            session.listener = listener
            listener.bind(LISTEN)
            listener.listen(MAX_CONNECTIONS)
            listener.settimeout(0.25)
            while not session.stopped.is_set():
                try:
                    conn, _ = listener.accept()
                except socket.timeout:
                    continue
                with session.lock:
                    if len(session.sockets) >= MAX_CONNECTIONS:
                        conn.close()
                        continue
                    ident = session.last_id + 1
                    if ident > 0xffffffff:
                        conn.close()
                        raise ProtocolError('connection identifiers exhausted')
                    # OPEN must precede the socket pump's first DATA.
                    session.send(OPEN, ident)
                    session.add(ident, conn)
        except (OSError, ProtocolError) as exc:
            if not session.stopped.is_set():
                session.error = exc
                session.stop()
        finally:
            if session.listener is not None:
                session.listener.close()
    ready = False
    def handle(kind, ident, data):
        nonlocal ready
        if not ready:
            if (kind, ident, data) != (READY, 0, nonce):
                raise ProtocolError('handshake mismatch')
            ready = True
            threading.Thread(target=accept_loop, daemon=True).start()
        else:
            session.receive(kind, ident, data)
    _run(session, handle, lifetime_seconds)


def local_client(reader, writer, *, expected_nonce, lifetime_seconds=7200, _socket_factory=None):
    session = _Session(reader, writer)
    nonce = _nonce(expected_nonce)
    factory = _socket_factory or socket.create_connection
    ready = False
    def handle(kind, ident, data):
        nonlocal ready
        if not ready:
            if (kind, ident, data) != (READY, 0, nonce):
                raise ProtocolError('handshake mismatch')
            session.send(READY, 0, nonce)
            ready = True
        elif kind == OPEN:
            if ident != session.last_id + 1 or len(session.sockets) >= MAX_CONNECTIONS:
                raise ProtocolError('invalid connection sequence or limit')
            try:
                sock = factory(UPSTREAM, timeout=5)
            except OSError:
                with session.lock:
                    session.last_id = ident
                session.send(CLOSE, ident)
                return
            sock.settimeout(None)
            session.add(ident, sock)
        else:
            session.receive(kind, ident, data)
    _run(session, handle, lifetime_seconds)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('remote', 'local'))
    parser.add_argument('--nonce', required=True)
    args = parser.parse_args()
    if args.mode == 'remote':
        remote_server(sys.stdin.buffer, sys.stdout.buffer, session_nonce=args.nonce)
    else:
        local_client(sys.stdin.buffer, sys.stdout.buffer, expected_nonce=args.nonce)
