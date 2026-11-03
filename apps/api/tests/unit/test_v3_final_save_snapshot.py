"""Pure snapshot tests; not evidence of database durability or ownership."""
import socket
from copy import deepcopy

import httpx
import pytest

from app.modules.ai.v3.final_save_contract import FinalSaveContractError
from app.modules.ai.v3.final_save_snapshot import make_snapshot, validate_snapshot
from tests.unit.test_v3_final_save_readback import fixture


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("network forbidden")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(httpx, "AsyncClient", deny)
    monkeypatch.setattr(httpx, "Client", deny)


def test_snapshot_is_detached_and_validates_cold_copy():
    data = fixture()
    snapshot = make_snapshot(data["state"], data["intent"])
    saved = deepcopy(snapshot)
    data["state"].source_analysis["changed"] = True
    data["intent"]["delivery_id"] = "changed"
    assert snapshot == saved
    assert validate_snapshot(saved, expected_intent_digest=saved["intent"]["intent_digest"])


@pytest.mark.parametrize("field", ["intent", "output", "policy", "extra", "expected"])
def test_tampering_cannot_validate(field):
    data = fixture()
    snapshot = make_snapshot(data["state"], data["intent"])
    expected = data["intent"]["intent_digest"]
    if field == "intent":
        snapshot["intent"]["delivery_id"] = "foreign"
    elif field == "output":
        snapshot["output"]["content"]["title"] = "changed"
    elif field == "policy":
        snapshot["policy"] = "other"
    elif field == "extra":
        snapshot["extra"] = True
    else:
        expected = "0" * 64
    assert not validate_snapshot(snapshot, expected_intent_digest=expected)


def test_scope_and_output_drift_refuse_new_snapshot():
    data = fixture()
    data["state"].job_id = "other"
    with pytest.raises(FinalSaveContractError):
        make_snapshot(data["state"], data["intent"])
    data = fixture()
    data["state"].content.title = "changed"
    with pytest.raises(FinalSaveContractError):
        make_snapshot(data["state"], data["intent"])
