from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.staff_import_session import StaffImportSession
from app.modules.staff_import_legacy_adapter import LegacyStaffRow, adapt_legacy_rows
from app.modules.staff_import_sessions import (
    ImportSession,
    ImportSessionConflict,
    ImportSessionState,
    MatchAction,
    bind_proposal_revision,
)
from app.modules.staff_import_sessions.commit_service import ImportCommitConflictError, commit_approved_import_session
from app.modules.staff_import_sessions.repository_matching import reconcile_proposal_with_database

SOURCE_SHA = "d" * 64


class _Scalars:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return self

    def all(self):
        return self.values


class _MatchingSession:
    def __init__(self, *, units, positions, users):
        self.results = [units, positions, users]

    async def execute(self, _statement):
        return _Scalars(self.results.pop(0))


def _fixture(*, active: bool, match_by_email: bool = False):
    tenant_id = uuid4()
    proposal = adapt_legacy_rows(
        tenant_id=tenant_id,
        source_file_name="same.xlsx",
        source_file_sha256=SOURCE_SHA,
        rows=[
            LegacyStaffRow(
                row_number=2,
                personnel_number="001",
                first_name="First",
                last_name="Testov",
                department="Dept A",
                position="Operator",
                email="first@example.test",
            )
        ],
    )
    department_id = uuid4()
    position_id = uuid4()
    department = SimpleNamespace(
        id=department_id,
        tenant_id=tenant_id,
        name=proposal.departments[0].department_name,
        unit_type="department",
        parent_id=None,
        external_key=proposal.departments[0].external_key,
        is_active=True,
        legacy_root=True,
        source_metadata={},
    )
    position = SimpleNamespace(
        id=position_id,
        tenant_id=tenant_id,
        name=proposal.positions[0].position_name,
        department_id=department_id,
        external_key=proposal.positions[0].external_key,
        source_metadata={},
    )
    user = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        first_name="First",
        last_name="Testov",
        personnel_number=None if match_by_email else "001",
        email="first@example.test",
        phone=None,
        position_id=position_id,
        organization_unit_id=department_id,
        is_active=active,
        status="active" if active else "terminated",
        role="student",
    )
    return tenant_id, proposal, department, position, user


@pytest.mark.parametrize("match_by_email", [False, True], ids=["personnel-number", "email"])
def test_inactive_identity_match_is_a_blocking_conflict_with_source_refs_and_existing_conflicts_preserved(
    match_by_email: bool,
) -> None:
    tenant_id, proposal, department, position, user = _fixture(active=False, match_by_email=match_by_email)
    prior_conflict = ImportSessionConflict(
        conflict_code="prior_issue",
        scope="source_row",
        message="Existing unrelated issue.",
        blocking=False,
    )
    proposal = proposal.model_copy(update={"conflicts": [prior_conflict]})

    result = asyncio.run(
        reconcile_proposal_with_database(
            _MatchingSession(units=[department], positions=[position], users=[user]),
            tenant_id=tenant_id,
            proposal=proposal,
        )
    )

    staff = result.staff[0]
    inactive_conflict = next(
        item for item in result.conflicts if item.conflict_code == "inactive_staff_requires_explicit_reactivation"
    )
    assert staff.action is MatchAction.CONFLICT
    assert inactive_conflict.blocking is True
    assert inactive_conflict.proposal_ids == [staff.external_key]
    assert inactive_conflict.source_refs == staff.source_refs
    assert any(item.conflict_code == "prior_issue" for item in result.conflicts)


def test_active_staff_still_reconciles_as_unchanged_by_legacy_external_key() -> None:
    tenant_id, proposal, department, position, user = _fixture(active=True)

    result = asyncio.run(
        reconcile_proposal_with_database(
            _MatchingSession(units=[department], positions=[position], users=[user]),
            tenant_id=tenant_id,
            proposal=proposal,
        )
    )

    assert result.staff[0].action is MatchAction.UNCHANGED
    assert not result.conflicts


class _CommitDB:
    def __init__(self, *, position, users):
        self.position = position
        self.users = users
        self.added = []
        self.flushes = 0
        self.user_query_locked = False

    async def execute(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        if entity.__name__ == "Department":
            return _Scalars([])
        if entity.__name__ == "Position":
            return _Scalars([self.position])
        if entity.__name__ == "User":
            self.user_query_locked = "FOR UPDATE" in str(statement).upper()
            return _Scalars(self.users)
        raise AssertionError(f"Unexpected query entity: {entity}")

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        self.flushes += 1


def test_commit_rechecks_locked_inactive_user_before_any_session_or_user_mutation(monkeypatch) -> None:
    tenant_id, proposal, _department, position, user = _fixture(active=False)
    user.personnel_number = "ＡＡ  01"
    proposal = proposal.model_copy(
        update={
            "departments": [],
            "positions": [proposal.positions[0].model_copy(update={"department_external_key": None})],
            "staff": [
                proposal.staff[0].model_copy(
                    update={
                        "personnel_number": "AA 01",
                        "department_external_key": None,
                        "branch_external_key": None,
                    }
                )
            ],
        }
    )
    actor_id, session_id, domain, record = _approved_commit_context(tenant_id, proposal, "inactive")
    monkeypatch.setattr(
        "app.modules.staff_import_sessions.commit_service.get_import_session",
        lambda *args, **kwargs: _return_async(record),
    )
    db = _CommitDB(position=position, users=[user])
    before = (
        user.first_name,
        user.last_name,
        user.personnel_number,
        user.position_id,
        user.organization_unit_id,
        user.status,
        user.role,
    )

    with pytest.raises(ImportCommitConflictError, match="inactive_staff_requires_explicit_reactivation"):
        asyncio.run(
            commit_approved_import_session(
                db,
                tenant_id=tenant_id,
                session_id=session_id,
                actor_id=actor_id,
                revision=domain.proposal.revision,
            )
        )

    assert record.state == ImportSessionState.APPROVED.value
    assert db.added == []
    assert db.flushes == 0
    assert db.user_query_locked is True
    assert user.is_active is False
    assert (
        user.first_name,
        user.last_name,
        user.personnel_number,
        user.position_id,
        user.organization_unit_id,
        user.status,
        user.role,
    ) == before


def test_commit_rejects_inactive_email_only_match(monkeypatch) -> None:
    tenant_id, proposal, _department, position, user = _fixture(active=False, match_by_email=True)
    proposal = proposal.model_copy(
        update={
            "departments": [],
            "positions": [proposal.positions[0].model_copy(update={"department_external_key": None})],
            "staff": [
                proposal.staff[0].model_copy(update={"department_external_key": None, "branch_external_key": None})
            ],
        }
    )
    actor_id, session_id, domain, record = _approved_commit_context(tenant_id, proposal, "email-only")
    monkeypatch.setattr(
        "app.modules.staff_import_sessions.commit_service.get_import_session",
        lambda *args, **kwargs: _return_async(record),
    )
    db = _CommitDB(position=position, users=[user])

    with pytest.raises(ImportCommitConflictError, match="inactive_staff_requires_explicit_reactivation"):
        asyncio.run(
            commit_approved_import_session(
                db,
                tenant_id=tenant_id,
                session_id=session_id,
                actor_id=actor_id,
                revision=domain.proposal.revision,
            )
        )

    assert user.personnel_number is None
    assert user.is_active is False
    assert user.status == "terminated"
    assert user.role == "student"
    assert record.state == ImportSessionState.APPROVED.value
    assert db.added == []
    assert db.flushes == 0
    assert db.user_query_locked is True


@pytest.mark.parametrize("ambiguity", ["normalized_personnel", "personnel_vs_email"])
def test_commit_rejects_ambiguous_locked_identities_before_any_writes(monkeypatch, ambiguity: str) -> None:
    tenant_id, proposal, _department, position, user = _fixture(active=True)
    proposal = proposal.model_copy(
        update={
            "departments": [],
            "positions": [proposal.positions[0].model_copy(update={"department_external_key": None})],
            "staff": [
                proposal.staff[0].model_copy(update={"department_external_key": None, "branch_external_key": None})
            ],
        }
    )
    if ambiguity == "personnel_vs_email":
        user.email = "other@example.test"
    duplicate = SimpleNamespace(
        **{
            **vars(user),
            "id": uuid4(),
            "personnel_number": " 001 " if ambiguity == "normalized_personnel" else "OTHER",
            "email": "other@example.test" if ambiguity == "normalized_personnel" else "FIRST@example.test",
        }
    )
    actor_id, session_id, domain, record = _approved_commit_context(tenant_id, proposal, ambiguity)
    monkeypatch.setattr(
        "app.modules.staff_import_sessions.commit_service.get_import_session",
        lambda *args, **kwargs: _return_async(record),
    )
    db = _CommitDB(position=position, users=[user, duplicate])
    before = [
        (
            item.id,
            item.first_name,
            item.last_name,
            item.position_id,
            item.organization_unit_id,
            item.status,
            item.role,
            item.is_active,
        )
        for item in (user, duplicate)
    ]
    expected_error = (
        "ambiguous normalized staff personnel number"
        if ambiguity == "normalized_personnel"
        else "staff personnel number and email identify different users"
    )

    with pytest.raises(ImportCommitConflictError, match=expected_error):
        asyncio.run(
            commit_approved_import_session(
                db,
                tenant_id=tenant_id,
                session_id=session_id,
                actor_id=actor_id,
                revision=domain.proposal.revision,
            )
        )

    assert record.state == ImportSessionState.APPROVED.value
    assert db.added == []
    assert db.flushes == 0
    assert db.user_query_locked is True
    assert [
        (
            item.id,
            item.first_name,
            item.last_name,
            item.position_id,
            item.organization_unit_id,
            item.status,
            item.role,
            item.is_active,
        )
        for item in (user, duplicate)
    ] == before


def _approved_commit_context(tenant_id, proposal, key):
    actor_id = uuid4()
    session_id = uuid4()
    domain = bind_proposal_revision(
        ImportSession(
            session_id=str(session_id),
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role="methodologist",
            state=ImportSessionState.APPROVED,
        ),
        proposal,
    )
    record = StaffImportSession(
        id=session_id,
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_role="methodologist",
        state=ImportSessionState.APPROVED.value,
        mode=domain.mode.value,
        idempotency_key=f"inactive-staff-guard-{key}",
        source_file_name=proposal.source_file_name,
        source_file_sha256=proposal.source_file_sha256,
        source_format="xlsx",
        source_size_bytes=1,
        parser_version="test",
        proposal_json=domain.proposal.model_dump(mode="json"),
        proposal_revision=domain.proposal.revision,
        proposal_hash=domain.proposal.revision_hash,
        reviewed_revision=domain.proposal.revision,
        approved_revision=domain.proposal.revision,
        full_reconciliation_confirmation=False,
    )
    return actor_id, session_id, domain, record


async def _return_async(value):
    return value
