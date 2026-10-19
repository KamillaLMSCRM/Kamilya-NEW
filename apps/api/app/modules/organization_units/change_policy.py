"""Pure placement-change impact policy; existing learning evidence is immutable."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from copy import deepcopy
from typing import Any, cast

type JSONObject = dict[str, Any]

MANAGED = frozenset({"organization", "department", "position"})


def fingerprint(snapshot: JSONObject) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def hr_managed(row: JSONObject) -> bool:
    metadata = row.get("source_metadata") or {}
    return (
        bool(row.get("hr_managed"))
        or metadata.get("origin") in {"1c", "hr", "hr_sync"}
        or metadata.get("authority") == "hr"
    )


def _index(data: JSONObject, key: str) -> dict[str, JSONObject]:
    return {row["id"]: row for row in data[key]}


def effective_unit(user: JSONObject, positions: dict[str, JSONObject]) -> str | None:
    position_id = cast(str, user.get("position_id"))
    value = user.get("organization_unit_id") or positions.get(position_id, {}).get("department_id")
    return cast(str | None, value)


def ancestor_ids(units: dict[str, JSONObject], unit_id: str | None) -> list[str]:
    result: list[str] = []
    while unit_id is not None:
        if unit_id in result:
            raise ValueError("hierarchy_cycle")
        if unit_id not in units:
            raise ValueError("invalid_hierarchy_reference")
        result.append(unit_id)
        if len(result) > 9:
            raise ValueError("maximum_depth_exceeded")
        unit_id = units[unit_id].get("parent_id")
    return result[::-1]


def _courses(
    data: JSONObject,
    user: JSONObject,
    units: dict[str, JSONObject],
    positions: dict[str, JSONObject],
) -> dict[str, str]:
    published = {c["id"] for c in data["courses"] if c["status"] == "published"}
    path = set(ancestor_ids(units, effective_unit(user, positions)))
    result: dict[str, str] = {}
    # Same assignment precedence as the existing rule kernel: position > department > organization.
    for scope in ("organization", "department", "position"):
        for rule in data["rules"]:
            if rule["scope"] != scope or rule["course_id"] not in published:
                continue
            if scope == "department" and (rule["ref"] not in path or not units[rule["ref"]]["is_active"]):
                continue
            if scope == "position" and rule["ref"] != user.get("position_id"):
                continue
            result[rule["course_id"]] = scope
    return result


def _audiences(data: JSONObject) -> dict[str, set[str]]:
    units, positions = _index(data, "units"), _index(data, "positions")
    students = [u for u in data["users"] if u["role"] == "student"]
    extra = {r["user_id"] for r in data["roles"] if r["role"] == "methodologist"}
    audiences: dict[str, set[str]] = {}
    for actor in data["users"]:
        if actor["role"] != "methodologist" and actor["id"] not in extra:
            continue
        if not actor["is_active"] or actor["status"] != "active":
            continue
        heads = {u["id"] for u in units.values() if u["is_active"] and u.get("head_user_id") == actor["id"]}
        groups = {g["id"] for g in data["cohorts"] if g["is_active"] and g["responsible_user_id"] == actor["id"]}
        if not heads and not groups:
            audiences[actor["id"]] = {s["id"] for s in students}
            continue
        members = {m["user_id"] for m in data["members"] if m["cohort_id"] in groups}
        audiences[actor["id"]] = members | {
            s["id"] for s in students if heads.intersection(ancestor_ids(units, effective_unit(s, positions)))
        }
    return audiences


def build_change(snapshot: JSONObject, command: JSONObject) -> JSONObject:
    """Return a complete, non-mutating plan; the persistence adapter owns atomic apply."""
    before, after = snapshot, deepcopy(snapshot)
    units, positions = _index(after, "units"), _index(after, "positions")
    target_id, new_unit = command["target_id"], command["organization_unit_id"]
    target = (_index(after, "users") if command["kind"] == "employee" else units).get(target_id)
    if target is None or (new_unit is not None and new_unit not in units):
        raise LookupError("resource_not_found")
    if new_unit is not None and not units[new_unit]["is_active"]:
        raise ValueError("inactive_target")
    if new_unit is not None and hr_managed(units[new_unit]):
        raise ValueError("hr_managed")
    if hr_managed(target):
        raise ValueError("hr_managed")
    if command["kind"] == "employee":
        if target["role"] != "student":
            raise ValueError("student_only")
        position = positions.get(command["position_id"])
        if position is None:
            raise LookupError("resource_not_found")
        if not position["is_active"]:
            raise ValueError("inactive_position")
        placement_unit = cast(str, new_unit or position.get("department_id"))
        if hr_managed(position) or hr_managed(units.get(placement_unit, {})):
            raise ValueError("hr_managed")
        old_unit = effective_unit(target, positions)
        old_position_id = cast(str, target.get("position_id"))
        old_position = positions.get(old_position_id, {})
        if hr_managed(old_position) or hr_managed(units.get(cast(str, old_unit), {})):
            raise ValueError("hr_managed")
        old_path = ancestor_ids(units, old_unit)
        target.update(organization_unit_id=new_unit, position_id=command["position_id"])
        new_path = ancestor_ids(units, effective_unit(target, positions))
        affected = {target_id}
    else:
        if not target["is_active"]:
            raise ValueError("inactive_target")
        old_path = ancestor_ids(units, target_id)
        if target.get("is_head_office") and new_unit is not None:
            raise ValueError("head_office_must_be_root")
        subtree = {u for u in units if target_id in ancestor_ids(units, u)}
        if any(hr_managed(units[u]) for u in subtree):
            raise ValueError("hr_managed")
        target["parent_id"] = new_unit
        for u in units:
            ancestor_ids(units, u)
        duplicate = [
            u
            for u in units.values()
            if u["id"] != target_id
            and u["is_active"]
            and u.get("parent_id") == new_unit
            and u["unit_type"] == target["unit_type"]
            and " ".join(unicodedata.normalize("NFKC", u["name"]).casefold().split())
            == " ".join(unicodedata.normalize("NFKC", target["name"]).casefold().split())
        ]
        if duplicate:
            raise ValueError("duplicate_sibling")
        new_path = ancestor_ids(units, target_id)
        affected = {
            u["id"] for u in after["users"] if u["role"] == "student" and effective_unit(u, positions) in subtree
        }
    old_units, old_users = _index(before, "units"), _index(before, "users")
    users = _index(after, "users")
    additions: list[dict[str, str]] = []
    retain: list[dict[str, str]] = []
    no_longer = completed = protected = 0
    course_details: dict[str, JSONObject] = {}
    course_names = {c["id"]: c["title"] for c in before["courses"]}
    for uid in sorted(affected):
        old_rules = _courses(before, old_users[uid], old_units, positions)
        new_rules = _courses(after, users[uid], units, positions)
        rows = [r for r in before["enrollments"] if r["user_id"] == uid]
        # Historical cancelled/superseded occurrences remain immutable evidence,
        # not current access. A completed occurrence still satisfies the rule.
        existing = {r["course_id"] for r in rows if r["status"] in {"enrolled", "in_progress", "completed"}}
        completed += sum(r["status"] == "completed" for r in rows)
        protected += sum(r["source"] not in MANAGED and r["status"] != "completed" for r in rows)
        no_longer += len(old_rules.keys() - new_rules.keys())
        retain.extend(
            {"enrollment_id": r["id"], "original_source": r["source"]}
            for r in rows
            if r["course_id"] not in new_rules and r["source"] in MANAGED and r["status"] != "completed"
        )
        if users[uid]["is_active"] and users[uid]["status"] == "active":
            additions.extend(
                {"user_id": uid, "course_id": cid, "source": new_rules[cid]}
                for cid in sorted(new_rules.keys() - existing)
            )
            for cid in new_rules.keys() - existing:
                detail = course_details.setdefault(
                    cid, {"course_id": cid, "title": course_names[cid], "added": 0, "retained_previous": 0}
                )
                detail["added"] += 1
        for cid in (old_rules.keys() - new_rules.keys()) & existing:
            detail = course_details.setdefault(
                cid, {"course_id": cid, "title": course_names[cid], "added": 0, "retained_previous": 0}
            )
            detail["retained_previous"] += 1
    old_access, new_access = _audiences(before), _audiences(after)
    reporting = []
    for uid, old in sorted(old_access.items()):
        new = new_access[uid]
        if old != new:
            reporting.append(
                {
                    "user_id": uid,
                    "full_name": users[uid]["full_name"],
                    "before_count": len(old),
                    "after_count": len(new),
                    "gained": len(new - old),
                    "lost": len(old - new),
                }
            )
    return {
        "view": {
            "kind": command["kind"],
            "target_id": target_id,
            "from_path": [old_units[u]["name"] for u in old_path],
            "to_path": [units[u]["name"] for u in new_path],
            "affected_employees": len(affected),
            "training": {
                "added": len(additions),
                "no_longer_required": no_longer,
                "preserved_completed": completed,
                "preserved_other_sources": protected,
                "courses": [course_details[cid] for cid in sorted(course_details)],
            },
            "reporting": reporting,
            "warnings": [
                "Все прежние назначения сохранены; утратившие обязательность курсы автоматически не удаляются."
            ],
        },
        "additions": additions,
        "retained": retain,
        "affected_user_ids": sorted(affected),
    }
