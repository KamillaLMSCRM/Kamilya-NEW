"""Unit contracts for regulated procedure binding."""

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.training_evidence.schemas import EvidenceEventCreate


def test_manual_event_contract_accepts_procedure_id_without_client_timestamp():
    payload = EvidenceEventCreate(
        user_id=uuid4(),
        procedure_type="acknowledgement",
        training_procedure_id=uuid4(),
        payload_snapshot={"procedure": {"title": "caller value"}},
    )

    assert payload.training_procedure_id is not None
    assert "occurred_at" not in EvidenceEventCreate.model_fields
    assert "record_type" not in EvidenceEventCreate.model_fields


def test_manual_event_contract_keeps_system_types_distinct_from_procedures():
    with pytest.raises(ValidationError):
        EvidenceEventCreate(
            user_id=uuid4(),
            procedure_type="unsupported_type",
            payload_snapshot={"source": "test"},
        )

    system_payload = EvidenceEventCreate(
        user_id=uuid4(),
        procedure_type="knowledge_check",
        training_procedure_id=uuid4(),
        payload_snapshot={"source": "test"},
    )
    assert system_payload.training_procedure_id is not None


def test_0089_migration_is_linear_and_contains_database_gate():
    path = Path(__file__).parents[2] / "alembic" / "versions" / "0089_training_evidence_procedure_gate.py"
    source = path.read_text(encoding="utf-8")

    assert 'revision = "0089"' in source
    assert 'down_revision = "0088"' in source
    assert "training_procedure_id" in source
    assert "procedure_status" in source
    assert "procedure_status <> 'active'" in source
    assert "ck_training_evidence_event_procedure_binding" in source
    assert "training_evidence_events_validate_procedure" in source
