"""A DEV broker TLS read timeout releases a stalled socket for a fresh connection."""
import datetime
import importlib
import ipaddress
import socket
import ssl
import threading
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from kombu import Connection
from kombu.transport.redis import Channel
from redis.connection import ConnectionPool, SSLConnection
from redis.exceptions import TimeoutError as RedisTimeoutError

module = importlib.import_module("app.core.celery_app")


def test_verified_tls_stall_times_out_then_fresh_connection_succeeds(tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "local test CA")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                           critical=False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / "ca.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert_path, key_path)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(2)
    listener.settimeout(5)
    port = listener.getsockname()[1]
    release = threading.Event()
    server_errors = []

    def read_command(stream):
        header = stream.readline(64)
        assert header.startswith(b"*") and header.endswith(b"\r\n")
        count = int(header[1:-2])
        assert 0 < count <= 4
        command = []
        for _ in range(count):
            length_line = stream.readline(64)
            assert length_line.startswith(b"$") and length_line.endswith(b"\r\n")
            size = int(length_line[1:-2])
            assert 0 <= size <= 128
            value = stream.read(size)
            assert len(value) == size and stream.read(2) == b"\r\n"
            command.append(value)
        return command

    def serve():
        try:
            for first in (True, False):
                raw, _ = listener.accept()
                with raw, server_context.wrap_socket(raw, server_side=True) as peer:
                    peer.settimeout(5)
                    with peer.makefile("rb") as stream:
                        assert read_command(stream) == [b"PING"]
                        if first:
                            assert release.wait(5)
                        else:
                            peer.sendall(b"+PONG\r\n")
                            assert read_command(stream) == [b"SMEMBERS", b"pidbox"]
                            peer.sendall(b"*0\r\n")
        except Exception as exc:
            server_errors.append(exc)
        finally:
            listener.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    monkeypatch.setattr(module, "settings", SimpleNamespace(DEPLOYMENT_ENVIRONMENT="vm-development-worker",
                                                           REDIS_URL=f"rediss://127.0.0.1:{port}/0"))
    options = module._broker_transport_options()
    kombu_connection = Connection(f"rediss://127.0.0.1:{port}/0", transport_options=options,
                                  ssl={"ssl_cert_reqs": ssl.CERT_REQUIRED, "ssl_ca_certs": str(cert_path),
                                       "ssl_check_hostname": True})
    channel = object.__new__(Channel)
    channel.connection = SimpleNamespace(client=kombu_connection, default_port=6379)
    for option in Channel.from_transport_options:
        if option in options:
            setattr(channel, option, options[option])
    params = channel._connparams()
    assert params["socket_timeout"] == 10 and params["socket_connect_timeout"] == 10
    assert params["socket_keepalive"] is True and params["ssl_cert_reqs"] == ssl.CERT_REQUIRED
    cls = params.pop("connection_class")
    assert issubclass(cls, SSLConnection)
    # Scale only the test copy; preserve the real TLS and Redis implementation.
    params.update(socket_timeout=0.2, socket_connect_timeout=2, lib_name=None, lib_version=None)
    first_pool = ConnectionPool(connection_class=cls, **params)
    second_pool = ConnectionPool(connection_class=cls, **params)
    try:
        first = first_pool.get_connection()
        # Kombu sets a health interval: sending SMEMBERS first triggers a PING.
        with pytest.raises(RedisTimeoutError):
            first.send_command("SMEMBERS", "pidbox")
        release.set()
        second = second_pool.get_connection()
        second.send_command("SMEMBERS", "pidbox")
        assert second.read_response() == []
    finally:
        release.set()
        first_pool.disconnect()
        second_pool.disconnect()
        thread.join(timeout=6)
    assert not thread.is_alive()
    assert not server_errors
