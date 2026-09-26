from pathlib import Path
from uuid import uuid4

from app.modules.cohorts.schemas import CohortCreate, CohortSummary, CohortUpdate
from app.modules.organization_units.schemas import (
    OrganizationUnitCreate,
    OrganizationUnitResponse,
    OrganizationUnitUpdate,
)

ROOT = Path(__file__).resolve().parents[1]


def test_responsibility_wire_contracts_preserve_explicit_owners() -> None:
    owner_id = uuid4()
    assert CohortCreate(name="Managers", responsible_user_id=owner_id).responsible_user_id == owner_id
    assert CohortUpdate(responsible_user_id=None).model_fields_set == {"responsible_user_id"}
    assert "responsible_user_name" in CohortSummary.model_fields

    created = OrganizationUnitCreate(
        name="Operations",
        unit_type="department",
        head_user_id=owner_id,
    )
    assert created.head_user_id == owner_id
    assert OrganizationUnitUpdate(head_user_id=None).model_fields_set == {
        "head_user_id"
    }
    assert "head_user_id" in OrganizationUnitResponse.model_fields


def test_migration_adds_tenant_guarded_group_responsibility() -> None:
    source = (
        ROOT / "alembic" / "versions" / "0164_training_reporting_responsibility.py"
    ).read_text(encoding="utf-8")
    assert 'revision = "0164"' in source
    assert 'down_revision = "0163"' in source
    assert "responsible_user_id" in source
    assert "cohort responsible user tenant mismatch" in source
    assert "cohort responsible user must be active methodologist" in source
    assert "BEFORE INSERT OR UPDATE OF tenant_id,responsible_user_id" in source
