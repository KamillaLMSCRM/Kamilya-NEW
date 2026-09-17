"""Database-free contracts for current placement in evidence projections."""

from uuid import uuid4

from app.modules.training_evidence.export_schemas import ServerEmployeeEvidence


def test_server_evidence_exposes_current_unit_path_as_non_historical_projection():
    unit_id = uuid4()
    employee = ServerEmployeeEvidence(
        id=str(uuid4()),
        full_name="Employee",
        department="Sector A",
        organization_unit_id=unit_id,
        organization_unit_path=["Central office", "Retail", "Sector A"],
    )

    assert employee.organization_unit_id == unit_id
    assert employee.organization_unit_path[-1] == "Sector A"
    assert employee.department == "Sector A"
