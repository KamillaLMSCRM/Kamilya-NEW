from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.evidence_export import (
    AssignmentEvidence,
    CourseEvidence,
    EmployeeEvidence,
    IndividualEvidenceInput,
    PrintFormEvidence,
    ProcedureEvidence,
    TenantEvidence,
)
from app.modules.training_evidence import export_service


class _Scalars:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class _Database:
    def __init__(self, batches):
        self.batches = iter(batches)

    async def scalars(self, _query):
        return _Scalars(next(self.batches))


@pytest.mark.asyncio
async def test_accepted_signed_copy_becomes_manual_confirmation_and_package_attachment(monkeypatch):
    tenant_id = uuid4()
    learner_id = uuid4()
    reviewer_id = uuid4()
    event_id = uuid4()
    scan_id = uuid4()
    now = datetime.now(UTC)
    content = b"%PDF-1.7 signed"
    import hashlib

    evidence = IndividualEvidenceInput(
        tenant=TenantEvidence(id=str(tenant_id), name="Tenant"),
        employee=EmployeeEvidence(id=str(learner_id), full_name="Learner One"),
        procedure=ProcedureEvidence(type="training", title="Course completion"),
        course=CourseEvidence(title="Safety", release_version=1),
        assignment=AssignmentEvidence(source="manual"),
        print_form=None,
        generated_at=now,
    )
    root = SimpleNamespace(id=event_id, user_id=learner_id)
    scan = SimpleNamespace(
        id=scan_id,
        uploaded_by_user_id=learner_id,
        original_filename="signed.pdf",
        content_type="application/pdf",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        uploaded_at=now,
        storage_key="signed.pdf",
    )
    review = SimpleNamespace(
        id=uuid4(),
        signed_scan_id=scan_id,
        action="accept",
        reviewed_by_user_id=reviewer_id,
        reviewed_at=now,
    )
    reviewer = SimpleNamespace(id=reviewer_id, first_name="Reviewer", last_name="One")
    db = _Database([[scan], [review], [reviewer]])

    async def _server_parts(*_args, **_kwargs):
        return evidence, root, [root]

    async def _unexpected_current_settings(*_args, **_kwargs):
        raise AssertionError("private evidence packages must not use presentation fallback settings")

    monkeypatch.setattr(export_service, "_build_server_parts", _server_parts)
    monkeypatch.setattr(
        export_service,
        "get_training_evidence_form_settings",
        _unexpected_current_settings,
        raising=False,
    )
    monkeypatch.setattr(export_service, "get_storage", lambda: SimpleNamespace(get_bytes=lambda _key: content))

    package_input, accepted = await export_service.build_individual_evidence_package_input(
        db,
        tenant_id,
        event_id,
    )

    assert package_input.confirmation is not None
    assert package_input.confirmation.method == "manual"
    assert package_input.confirmation.evidence_reference == str(scan_id)
    assert package_input.print_form is None
    assert accepted[0][0].review_status == "accepted"
    assert accepted[0][0].uploaded_by == "learner"
    assert accepted[0][1] == content


@pytest.mark.asyncio
async def test_learner_export_uses_current_tenant_form_for_legacy_training_event(monkeypatch):
    tenant_id = uuid4()
    learner_id = uuid4()
    event_id = uuid4()
    enrollment_id = uuid4()
    now = datetime.now(UTC)
    event = SimpleNamespace(
        id=event_id,
        tenant_id=tenant_id,
        user_id=learner_id,
        record_type="original",
        procedure_type="training",
        enrollment_id=enrollment_id,
        payload_snapshot={"procedure": {"title": "Legacy completion"}},
    )
    evidence = IndividualEvidenceInput(
        tenant=TenantEvidence(id=str(tenant_id), name="Legacy tenant"),
        employee=EmployeeEvidence(id=str(learner_id), full_name="Legacy Learner"),
        procedure=ProcedureEvidence(type="training", title="Legacy completion"),
        course=CourseEvidence(title="Safety", release_version=1),
        assignment=AssignmentEvidence(enrollment_id=str(enrollment_id), source="manual"),
        print_form=None,
        generated_at=now,
    )
    fallback = PrintFormEvidence(
        organization_name="Legacy tenant",
        title="Подтверждение прохождения курса",
        confirmation_text="Подтверждаю завершение курса.",
        employee_signature_label="Подпись сотрудника",
        employee_date_label="Дата",
        representative_signature_label="Подпись представителя работодателя",
        representative_date_label="Дата проверки",
    )

    class LearnerDatabase:
        async def scalar(self, _query):
            return event

    async def _server_parts(*_args, **_kwargs):
        return evidence, event, [event]

    async def _current_settings(*_args, **_kwargs):
        return SimpleNamespace(to_print_form=lambda: fallback)

    original_payload = dict(event.payload_snapshot)

    monkeypatch.setattr(export_service, "_build_server_parts", _server_parts)
    monkeypatch.setattr(
        export_service,
        "get_training_evidence_form_settings",
        _current_settings,
        raising=False,
    )

    result = await export_service.build_learner_individual_evidence_input(
        LearnerDatabase(),
        tenant_id,
        learner_id,
        event_id,
    )

    assert result.print_form == fallback
    assert event.payload_snapshot == original_payload


@pytest.mark.asyncio
async def test_learner_export_keeps_completion_time_form_snapshot(monkeypatch):
    tenant_id = uuid4()
    learner_id = uuid4()
    event_id = uuid4()
    enrollment_id = uuid4()
    snapshot = PrintFormEvidence(
        organization_name="Snapshot tenant",
        title="Snapshot form",
        confirmation_text="Snapshot confirmation",
        employee_signature_label="Employee signature",
        employee_date_label="Employee date",
        representative_signature_label="Representative signature",
        representative_date_label="Representative date",
    )
    event = SimpleNamespace(
        id=event_id,
        tenant_id=tenant_id,
        user_id=learner_id,
        record_type="original",
        procedure_type="training",
        enrollment_id=enrollment_id,
    )
    evidence = IndividualEvidenceInput(
        tenant=TenantEvidence(id=str(tenant_id), name="Snapshot tenant"),
        employee=EmployeeEvidence(id=str(learner_id), full_name="Snapshot Learner"),
        procedure=ProcedureEvidence(type="training", title="Snapshot completion"),
        course=CourseEvidence(title="Safety", release_version=1),
        assignment=AssignmentEvidence(enrollment_id=str(enrollment_id), source="manual"),
        print_form=snapshot,
        generated_at=datetime.now(UTC),
    )

    class LearnerDatabase:
        async def scalar(self, _query):
            return event

    async def _server_parts(*_args, **_kwargs):
        return evidence, event, [event]

    async def _unexpected_current_settings(*_args, **_kwargs):
        raise AssertionError("current settings must not replace a completion-time snapshot")

    monkeypatch.setattr(export_service, "_build_server_parts", _server_parts)
    monkeypatch.setattr(
        export_service,
        "get_training_evidence_form_settings",
        _unexpected_current_settings,
    )

    result = await export_service.build_learner_individual_evidence_input(
        LearnerDatabase(),
        tenant_id,
        learner_id,
        event_id,
    )

    assert result.print_form == snapshot
