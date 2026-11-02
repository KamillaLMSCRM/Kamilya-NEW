"""The DEV TLS broker cannot leave the consumer blocked on an idle PING."""
import importlib
import ssl
from types import SimpleNamespace

import pytest
from kombu import Connection
from kombu.transport.redis import Channel

module = importlib.import_module("app.core.celery_app")


def options_for_settings():
    factory = getattr(module, "_broker_transport_options", None)
    return factory() if factory else dict(module.celery_app.conf.broker_transport_options)


@pytest.mark.parametrize("environment", ["vm-development-worker", "render-development-worker", "render-development"])
def test_dev_tls_deadlines_reach_actual_kombu_redis_connection(monkeypatch, environment):
    monkeypatch.setattr(module, "settings", SimpleNamespace(DEPLOYMENT_ENVIRONMENT=environment,
                                                           REDIS_URL="rediss://localhost:6380/1"))
    options = options_for_settings()
    # Exercise the installed transport's mapping, without opening a connection.
    connection = Connection("rediss://localhost:6380/1", ssl={"ssl_cert_reqs": ssl.CERT_REQUIRED},
                            transport_options=options)
    channel = object.__new__(Channel)
    channel.connection = SimpleNamespace(client=connection, default_port=6379)
    for key in Channel.from_transport_options:
        if key in options:
            setattr(channel, key, options[key])
    params = channel._connparams()
    assert params["socket_timeout"] == 10
    assert params["socket_connect_timeout"] == 10
    assert params["socket_keepalive"] is True
    assert params["ssl_cert_reqs"] == ssl.CERT_REQUIRED
    assert params["db"] == 1
    assert options["visibility_timeout"] == 3600
    assert not options.get("retry_on_timeout")


@pytest.mark.parametrize(("environment", "url"), [
    ("kz-production", "rediss://localhost:6380/1"),
    ("production", "redis://localhost:6379/0"),
    ("local", "rediss://localhost:6380/1"),
    ("vm-development-worker", "redis://localhost:6379/1"),
])
def test_other_broker_contracts_are_unchanged(monkeypatch, environment, url):
    monkeypatch.setattr(module, "settings", SimpleNamespace(DEPLOYMENT_ENVIRONMENT=environment, REDIS_URL=url))
    assert options_for_settings() == {"visibility_timeout": 3600}
