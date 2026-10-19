from copy import deepcopy

import pytest

from app.modules.organization_units.change_policy import ancestor_ids, build_change, fingerprint, hr_managed


def example():
    return {
        "units": [
            {"id": "a", "name": "A", "parent_id": None, "is_active": True, "unit_type": "branch", "head_user_id": "m"},
            {"id": "b", "name": "B", "parent_id": None, "is_active": True, "unit_type": "branch", "head_user_id": None},
            {"id": "c", "name": "C", "parent_id": "a", "is_active": True, "unit_type": "department", "head_user_id": None},
        ],
        "positions": [{"id": "p", "name": "Shared", "department_id": "c", "is_active": True}],
        "users": [
            {"id": "s", "full_name": "Synthetic", "role": "student", "organization_unit_id": None, "position_id": "p", "is_active": True, "status": "active"},
            {"id": "m", "full_name": "Method", "role": "methodologist", "is_active": True, "status": "active"},
        ],
        "courses": [{"id": x, "title": x, "status": "published"} for x in ["old", "new", "completed", "manual", "common"]],
        "rules": [{"scope": "department", "ref": "a", "course_id": "old"}, {"scope": "department", "ref": "b", "course_id": "new"}, {"scope": "organization", "ref": None, "course_id": "common"}],
        "enrollments": [{"id": x, "user_id": "s", "course_id": x, "source": source, "status": status} for x, source, status in [("old", "department", "in_progress"), ("completed", "position", "completed"), ("manual", "manual", "enrolled")]],
        "cohorts": [], "members": [], "roles": [],
    }


def employee_command():
    return {"kind": "employee", "target_id": "s", "organization_unit_id": "b", "position_id": "p", "reason": "Synthetic transfer"}


def test_employee_transfer_adds_only_and_preserves_all_existing_provenance():
    data = example()
    before = deepcopy(data)
    result = build_change(data, employee_command())
    assert data == before
    assert result["view"]["from_path"] == ["A", "C"]
    assert result["view"]["to_path"] == ["B"]
    assert result["view"]["training"] == {"added": 2, "no_longer_required": 1, "preserved_completed": 1, "preserved_other_sources": 1,
        "courses": [{"course_id": "common", "title": "common", "added": 1, "retained_previous": 0},
                    {"course_id": "new", "title": "new", "added": 1, "retained_previous": 0},
                    {"course_id": "old", "title": "old", "added": 0, "retained_previous": 1}]}
    assert {(x["course_id"], x["source"]) for x in result["additions"]} == {("new", "department"), ("common", "organization")}
    assert result["view"]["reporting"] == [{"user_id": "m", "full_name": "Method", "before_count": 1, "after_count": 0, "gained": 0, "lost": 1}]


@pytest.mark.parametrize("status,requires_new", [
    ("cancelled", True), ("superseded", True), ("completed", False),
    ("enrolled", False), ("in_progress", False),
])
def test_historical_occurrence_never_blocks_missing_current_training(status, requires_new):
    data = example()
    data["enrollments"].append({"id": "history", "user_id": "s", "course_id": "new",
        "source": "manual", "status": status})
    original = deepcopy(data)
    result = build_change(data, employee_command())
    assert any(row["course_id"] == "new" for row in result["additions"]) is requires_new
    assert data == original


def test_unit_move_includes_position_fallback_members_and_cohort_union():
    data = example()
    data["cohorts"] = [{"id": "g", "responsible_user_id": "m", "is_active": True}]
    data["members"] = [{"cohort_id": "g", "user_id": "s"}]
    result = build_change(data, {"kind": "unit", "target_id": "c", "organization_unit_id": "b", "reason": "Move branch"})
    assert result["view"]["affected_employees"] == 1
    assert result["view"]["training"]["added"] == 2
    assert result["view"]["reporting"] == []


def test_inactive_transfer_changes_reporting_but_does_not_assign_training():
    data = example()
    data["users"][0]["is_active"] = False
    result = build_change(data, employee_command())
    assert result["additions"] == []
    assert result["view"]["reporting"][0]["lost"] == 1


@pytest.mark.parametrize("mutate,command,error", [
    (lambda d: d["units"][1].update(is_active=False), employee_command(), "inactive_target"),
    (lambda d: None, {"kind": "unit", "target_id": "a", "organization_unit_id": "c", "reason": "Cycle"}, "hierarchy_cycle"),
    (lambda d: d["units"][2].update(is_head_office=True), {"kind": "unit", "target_id": "c", "organization_unit_id": "b", "reason": "Move"}, "head_office_must_be_root"),
    (lambda d: d["users"][0].update(role="methodologist"), employee_command(), "student_only"),
    (lambda d: d["units"][2].update(source_metadata={"origin": "1c"}), employee_command(), "hr_managed"),
])
def test_invalid_or_hr_owned_changes_fail_closed(mutate, command, error):
    data = example()
    mutate(data)
    with pytest.raises(ValueError, match=error):
        build_change(data, command)


def test_missing_foreign_target_is_not_found_and_snapshot_fingerprints_are_order_stable():
    data = example()
    command = employee_command() | {"organization_unit_id": "foreign"}
    with pytest.raises(LookupError):
        build_change(data, command)
    assert fingerprint(data) == fingerprint(deepcopy(data))
    data["enrollments"][0]["status"] = "completed"
    assert fingerprint(data) != fingerprint(example())


def test_depth_eight_is_allowed_but_depth_nine_is_rejected():
    units = {str(i): {"parent_id": str(i-1) if i else None} for i in range(10)}
    assert len(ancestor_ids(units, "8")) == 9
    with pytest.raises(ValueError, match="maximum_depth_exceeded"):
        ancestor_ids(units, "9")


def test_external_import_key_alone_is_not_hr_authority():
    assert not hr_managed({"external_key": "csv-42", "source_metadata": {"origin": "spreadsheet"}})
    assert hr_managed({"source_metadata": {"authority": "hr"}})
    assert hr_managed({"hr_managed": True})


@pytest.mark.parametrize("location", ["employee", "source_position", "destination_position", "destination_unit"])
def test_hr_ownership_at_every_transfer_endpoint_blocks_manual_move(location):
    data = example()
    command = employee_command()
    if location == "employee":
        data["users"][0]["hr_managed"] = True
    elif location == "source_position":
        data["positions"].append({"id": "plain", "name": "Plain", "department_id": "b", "is_active": True})
        command["position_id"] = "plain"
        data["positions"][0]["source_metadata"] = {"origin": "1c"}
    elif location == "destination_position":
        data["positions"].append({"id": "hr", "name": "HR", "department_id": "b", "is_active": True, "source_metadata": {"origin": "1c"}})
        command["position_id"] = "hr"
    else:
        data["units"][1]["source_metadata"] = {"origin": "1c"}
    with pytest.raises(ValueError, match="hr_managed"):
        build_change(data, command)


def test_unit_move_rejects_unicode_equivalent_sibling_name():
    data = example()
    data["units"][2]["name"] = "  Ｃ  "
    data["units"].append({"id": "duplicate", "name": "C", "parent_id": "b", "is_active": True,
                          "unit_type": "department", "head_user_id": None})
    with pytest.raises(ValueError, match="duplicate_sibling"):
        build_change(data, {"kind": "unit", "target_id": "c", "organization_unit_id": "b", "reason": "Move"})
