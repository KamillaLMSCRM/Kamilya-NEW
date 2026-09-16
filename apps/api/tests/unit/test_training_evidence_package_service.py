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
        print_form=PrintFormEvidence(
            organization_name="Tenant",
            title="Confirmation",
            confirmation_text="I completed the course.",
            employee_signature_label="Signature",
            employee_date_label="Date",
            representative_signature_label="Representative",
            representative_date_label="Review date",
        ),
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

    monkeypatch.setattr(export_service, "_build_server_parts", _server_parts)
    monkeypatch.setattr(export_service, "get_storage", lambda: SimpleNamespace(get_bytes=lambda _key: content))

    package_input, accepted = await export_service.build_individual_evidence_package_input(
        db,
        tenant_id,
        event_id,
    )

    assert package_input.confirmation is not None
    assert package_input.confirmation.method == "manual"
    assert package_input.confirmation.evidence_reference == str(scan_id)
    assert accepted[0][0].review_status == "accepted"
    assert accepted[0][0].uploaded_by == "learner"
    assert accepted[0][1] == content
