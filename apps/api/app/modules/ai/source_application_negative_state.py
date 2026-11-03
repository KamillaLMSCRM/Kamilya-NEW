"""Monotonic negative custody from an already compiler-validated audit view."""

from __future__ import annotations

from typing import Any, cast

from app.modules.ai.source_application_fields import APPLICATION_REPAIR_FIELDS
from app.modules.ai.source_application_requirement_effects import requirement_effect, unchanged_requirement
from app.modules.ai.source_application_requirements import normalize_requirement_audit
from app.modules.ai.source_assessment_graph import _hash
from app.modules.ai.source_assessment_plan import SourcePlanError
from app.modules.ai.source_audit_citation_holds import project_negative_citation_holds, unique_literal_interval
from app.modules.ai.source_target_coordinates import TargetCoordinatesError, match_target_coordinates

POLICY = "application-negative-state-v5"
_OPAQUE = frozenset({"id", "application_id", "repair_cohort_id", "owner_handles"})


def _sorted(values: Any) -> list[Any]:
    return sorted(values, key=_hash)


def _coordinates(receipt: dict[str, Any], bases: dict[str, Any]) -> list[dict[str, str]]:
    """Compiler-role lineage is separate from the aspect under refusal.

    Source-goal anchors survive neutral reordering. A changed single goal may
    retain its owner-role lineage; ambiguous multi-goal edits stay unresolved.
    Displayed context, labels and temporary aliases never identify a goal.
    """
    view = receipt["view"]
    result = []
    for target in view["targets"]:
        if len(target["owner_handles"]) != 1:
            raise SourcePlanError("source_applications_negative_coordinate_integrity")
        owner = target["owner_handles"][0]
        kind = receipt["negative_owner_kinds"].get(owner)
        role = kind
        if kind == "timing_case":
            partitions = [row for row in view["relations"]
                if row["kind"] == "timing_partition" and row["owner_handles"] == [owner]]
            if len(partitions) != 1:
                raise SourcePlanError("source_applications_negative_coordinate_integrity")
            partition = partitions[0]
            roles = [name for name, members in (
                ("action", [partition["action_target_id"]]),
                ("purpose", partition["purpose_target_ids"]),
                ("branch", [pair["target_id"] for pair in partition["branch_pairs"]]))
                if target["id"] in members]
            if len(roles) != 1:
                raise SourcePlanError("source_applications_negative_coordinate_integrity")
            role = roles[0]
        if role not in {"decision", "checklist", "action", "purpose", "branch"}:
            raise SourcePlanError("source_applications_negative_coordinate_integrity")
        result.append({"target_id": target["id"], "owner": owner, "role": role,
            "anchor": _hash(bases[target["id"]])})
    try:
        match_target_coordinates(result, result)
    except TargetCoordinatesError as exc:
        raise SourcePlanError("source_applications_negative_coordinate_integrity") from exc
    return result


def _state(receipt: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    if receipt.get("view_sha256") != _hash({k: v for k, v in receipt.items() if k != "view_sha256"}):
        raise SourcePlanError("source_applications_negative_view_integrity")
    view = receipt["view"]
    sources = {row["ref"]: row["text"] for row in view["sources"]}
    spans = {row["id"]: {**{k: row[k] for k in ("ref", "start", "end")},
        "quote": row.get("quote", sources[row["ref"]][row["start"]:row["end"]])}
        for row in view["evidence_spans"]}
    units = {row["unit_id"]: {k: v for k, v in row.items() if k != "unit_id"}
             for row in view["original_units"]}
    bases = {}
    for target in view["targets"]:
        bases[target["id"]] = {"sources": sorted(target["source_refs"]),
            "answer_components": _sorted({"ref": row["ref"],
                "evidence": _sorted(spans[eid] for eid in row["evidence_ids"])}
                for row in target["answer_components"]),
            "dimensions": sorted(target["operative_dimensions"]),
            "units": _sorted(units[uid] for uid in target["unit_ids"])}
    owners = {owner: _sorted(bases[row["id"]] for row in view["targets"] if owner in row["owner_handles"])
              for target in view["targets"] for owner in target["owner_handles"]}
    raw_applications = {row["id"]: row for row in view["applications"]}
    owner_cache: dict[str, Any] = {}
    visiting: set[str] = set()

    def owner_meaning(owner: str) -> Any:
        if owner in owner_cache:
            return owner_cache[owner]
        if owner in visiting:
            raise SourcePlanError("source_applications_negative_dependency_cycle")
        visiting.add(owner)
        try:
            value = {"goals": owners[owner],
                "context": _sorted(normalize(row["context"]) for row in view["targets"]
                    if owner in row["owner_handles"]),
                "applications": _sorted(normalize(row) for row in view["applications"]
                    if owner in row["owner_handles"]),
                "relations": _sorted(relation(row) for row in view["relations"]
                    if owner in row["owner_handles"])}
            owner_cache[owner] = value
            return value
        finally:
            visiting.remove(owner)

    def normalize(value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return {k: normalize(v, k) for k, v in value.items() if k not in _OPAQUE}
        if isinstance(value, list):
            return _sorted(normalize(row, key) for row in value)
        if isinstance(value, str) and key not in {"quote", "text", "description", "reason"}:
            if key in {"predecessor_frame", "predecessor_handle", "frame_handle"} and value in owners:
                return owner_meaning(value)
            if value in spans:
                return spans[value]
            if value in bases:
                return bases[value]
        return value

    def relation(row: dict[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], normalize({**row, "declaration_ids": [normalize(raw_applications[alias])
            for alias in row.get("declaration_ids", [])]}))

    applications = {row["id"]: normalize(row) for row in view["applications"]}
    relations = {row["id"]: relation(row) for row in view["relations"]}
    result: dict[str, list[dict[str, Any]]] = {key: [] for key in
        ("target", "application", "relation", "context", "unit", "source_gap")}

    def add(kind: str, cohort: list[str], payload: Any, target_ids: list[str], refs: list[str], alias: str) -> None:
        result[kind].append({"cohort": cohort, "signature": _hash(payload),
            "target_ids": sorted({receipt["target_map"][tid] for tid in target_ids}),
            "refs": sorted(set(refs)), "alias": alias})

    for row in view["targets"]:
        tid, cohort = row["id"], sorted(row["owner_handles"])
        apps = [applications[alias] for alias in row["application_ids"]]
        native = [relations[alias] for alias in row["relation_ids"]]
        add("target", cohort, {"goal": bases[tid], "context": _sorted(row["context"]),
            "applications": _sorted(apps), "relations": _sorted(native)}, [tid], row["source_refs"], tid)
        result["target"][-1]["coordinate_id"] = tid
        # Audit repair fields name independent semantic aspects. A binding edit
        # cannot discharge an unchanged answer refusal merely by changing the
        # whole target fingerprint. Alias expansion remains source-derived.
        owner_kinds = sorted(receipt["negative_owner_kinds"][owner] for owner in row["owner_handles"])
        own_answer = {"answer_components": bases[tid]["answer_components"],
            "dimensions": bases[tid]["dimensions"]}
        local_goal = {"sources": bases[tid]["sources"], "answer": own_answer, "kind": owner_kinds}
        local_context = normalize(row["context"])
        # Native aliases name permissible raw edits, but their *effects* are
        # measured on this target's compiled meaning. Hashing a raw owner's
        # action/purposes/leaves would let a sibling or cosmetic label erase it.
        structural = _sorted(normalize({k: v for k, v in relation_row.items()
            if k != "declaration_ids"}) for relation_row in view["relations"]
            if relation_row["id"] in row["relation_ids"])
        aspects = {
            "source_refs": sorted(row["source_refs"]),
            "answer_components": own_answer,
            "assessed_focus": own_answer,
            "context": local_context,
            "fixed_source_context": local_context,
            "governing_bindings": {"applications": _sorted(apps)},
            "question_format": local_goal,
            "source_quote_proposition": {"goal": local_goal, "context": local_context,
                "structural_relations": structural},
            "construction_mode": {"goal": local_goal, "context": local_context,
                "applications": _sorted(apps), "relations": _sorted(native)},
        }
        if aspects.keys() != APPLICATION_REPAIR_FIELDS.keys():
            raise SourcePlanError("source_applications_negative_aspect_integrity")
        result["target"][-1]["aspects"] = aspects
        for axis in row["application_ids_by_axis"]:
            add("context", [*cohort, axis], {"own_answer": bases[tid],
                "applications": _sorted(applications[alias] for alias in row["application_ids_by_axis"][axis]),
                "native_relations": _sorted(relations[alias] for alias in row["native_relation_ids_by_axis"][axis])},
                [tid], row["source_refs"], tid + ":" + axis)
            result["context"][-1]["coordinate_id"] = tid
    for collection, kind, semantic in (("applications", "application", applications),
                                       ("relations", "relation", relations)):
        for row in view[collection]:
            refs = [ref for tid in row["target_ids"] for ref in next(
                t for t in view["targets"] if t["id"] == tid)["source_refs"]]
            add(kind, sorted(row["owner_handles"]), semantic[row["id"]], row["target_ids"], refs, row["id"])
            if kind == "application":
                predecessor = semantic[row["id"]].get("predecessor_frame")
                result[kind][-1]["predecessor_effect"] = _hash(predecessor) if isinstance(predecessor, dict) else None
    for unit in view["original_units"]:
        targets = [row for row in view["targets"] if unit["unit_id"] in row["unit_ids"]]
        aliases = {row["id"] for row in targets}
        add("unit", [unit["ref"], unit["source_id"]], {"unit": units[unit["unit_id"]],
            "goals": _sorted(bases[tid] for tid in aliases),
            # The unit critic reviewed the displayed candidate too. Preserve
            # exact goal-to-context pairing; a legitimate context-only repair
            # must reach fresh review without erasing precise target/gap holds.
            "displayed_goals": _sorted({"goal": bases[row["id"]], "context": normalize(row["context"])}
                                       for row in targets),
            "applications": _sorted(applications[row["id"]] for row in view["applications"]
                                    if set(row["target_ids"]) & aliases),
            "relations": _sorted(relations[row["id"]] for row in view["relations"]
                                 if set(row["target_ids"]) & aliases)},
            list(aliases), [unit["ref"]], unit["unit_id"])
    result["coordinates"] = _coordinates(receipt, bases)
    return result


def _gap_state(receipt: dict[str, Any], interval: dict[str, Any]) -> dict[str, Any]:
    """Bind a gap to its literal interval and only intersecting answer coverage.

    Other goals on the same source are not evidence of repairing this gap.
    Clipping evidence to the interval also prevents an unrelated extension of
    a larger quoted clause from releasing a still unchanged missing passage.
    """
    view = receipt["view"]
    source, = [row for row in view["sources"] if row["ref"] == interval["ref"] and row["primary"]]
    start, end = interval["start"], interval["end"]
    if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source["text"])
            or interval["source_sha256"] != _hash(source["text"])
            or interval["quote_sha256"] != _hash(source["text"][start:end])):
        raise SourcePlanError("source_applications_negative_gap_integrity")
    spans = {row["id"]: row for row in view["evidence_spans"]}
    coverage: list[tuple[int, int]] = []
    targets = []
    for target in view["targets"]:
        intersects = False
        for component in target["answer_components"]:
            for alias in component["evidence_ids"]:
                span = spans[alias]
                if span["ref"] != source["ref"] or span["end"] <= start or end <= span["start"]:
                    continue
                left, right = max(start, span["start"]), min(end, span["end"])
                coverage.append((left, right))
                intersects = True
        if intersects:
            targets.append(receipt["target_map"][target["id"]])
    merged: list[tuple[int, int]] = []
    for left, right in sorted(coverage):
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        else:
            merged.append((left, right))
    return {"cohort": [source["ref"], str(start), str(end)],
        "signature": _hash({"interval": interval, "coverage": merged}),
        "target_ids": sorted(targets), "refs": [source["ref"]], "alias": source["ref"],
        "interval": interval}


def _gap_interval(receipt: dict[str, Any], ref: str, quote: str) -> dict[str, Any]:
    source, = [row for row in receipt["view"]["sources"] if row["ref"] == ref and row["primary"]]
    located = unique_literal_interval(source["text"], quote)
    if located is None:
        raise SourcePlanError("source_applications_negative_gap_integrity")
    return {"ref": ref, "start": located[0], "end": located[1],
        "source_sha256": _hash(source["text"]), "quote_sha256": _hash(quote)}


def _target_signature(row: dict[str, Any], fields: list[str]) -> str:
    if not fields or not set(fields) <= row["aspects"].keys():
        raise SourcePlanError("source_applications_negative_aspect_integrity")
    return _hash({field: row["aspects"][field] for field in sorted(fields)})


def capture_application_negative_state(
    receipt: dict[str, Any], wire: dict[str, Any], *, citation_holds: list[dict[str, Any]] | None = None,
    requirement_wire: Any = None,
) -> dict[str, Any]:
    """Capture existing negatives only; this receipt grants no repair permission."""
    state = _state(receipt)
    typed = normalize_requirement_audit(requirement_wire, receipt) if requirement_wire is not None else None
    if typed is not None:
        projected, expected_holds = project_negative_citation_holds(typed["legacy_wire"], receipt)
        if projected != wire or expected_holds != (citation_holds or []):
            raise SourcePlanError("source_applications_requirement_projection_identity")
    requirements = {row["target_id"]: row["requirements"] for row in typed["requirements"]} if typed else {}
    selected: list[dict[str, Any]] = []
    for collection, kind, idkey in (("target_verdicts", "target", "target_id"),
                                   ("application_verdicts", "application", "claim_id"),
                                   ("relation_verdicts", "relation", "relation_id")):
        for vote in wire[collection]:
            if not vote["admit"]:
                for row in state[kind]:
                    if row["alias"] != vote[idkey]:
                        continue
                    negative = {"kind": kind, **{k: v for k, v in row.items() if k != "aspects"}}
                    if kind == "target":
                        if typed is not None:
                            for requirement in requirements[vote["target_id"]]:
                                effect = requirement_effect(requirement["subject"], receipt, state, vote["target_id"])
                                selected.append(negative | {"kind": "target_requirement", "requirement": requirement,
                                    "requirement_effect": effect, "signature": effect["signature"]})
                        else:
                            # Compatibility API only. The V4 builder always
                            # supplies the strict original requirement wire.
                            fields = sorted(vote["repair_fields"])
                            for field in fields:
                                selected.append(negative | {"repair_fields": [field],
                                    "signature": _target_signature(row, [field])})
                    else:
                        selected.append(negative)
    if typed is None:
        # Historical direct API only. Strict ingress covers every raw context
        # refusal with precise target requirements. An aggregate axis signature
        # permits unrelated same-axis resets and blocks literal-context repairs.
        for vote in wire["context_verdicts"]:
            for axis in vote["axes"]:
                if axis["status"] in {"missing", "ambiguous"}:
                    selected.extend({"kind": "context", **row} for row in state["context"]
                        if row["alias"] == vote["target_id"] + ":" + axis["axis"])
    for vote in wire["unit_verdicts"]:
        if vote["review_state"] != "complete":
            selected.extend({"kind": "unit", **row} for row in state["unit"] if row["alias"] == vote["unit_id"])
    for gap in wire["source_gaps"]:
        interval = _gap_interval(receipt, gap["ref"], gap["missing_source_text"])
        selected.append({"kind": "source_gap", **_gap_state(receipt, interval)})
    for hold in citation_holds or []:
        # The citation adapter withholds a uniquely located punctuation error;
        # it cannot grant a new-goal permission or silently erase its negative.
        interval = _gap_interval(receipt, hold["ref"], hold["canonical_text"])
        if (interval["start"], interval["end"]) != (hold["start"], hold["end"]):
            raise SourcePlanError("source_applications_negative_gap_integrity")
        selected.append({"kind": "source_gap", **_gap_state(receipt, interval)})
    selected = list({_hash(row): row for row in selected}.values())
    record = {"policy": POLICY, "negatives": selected, "coordinates": state["coordinates"],
        "requirement_audit_sha256": typed["receipt_sha256"] if typed else None, "semantic_approval": False}
    return {**record, "receipt_sha256": _hash(record)}


def compare_application_negative_state(before: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    """A changed peer or opaque alias cannot discharge an unchanged negative."""
    if (before.get("policy") != POLICY or before.get("receipt_sha256") != _hash(
            {k: v for k, v in before.items() if k != "receipt_sha256"})):
        raise SourcePlanError("source_applications_negative_state_integrity")
    state = _state(receipt)
    try:
        lineage = match_target_coordinates(before.get("coordinates"), state["coordinates"])
    except TargetCoordinatesError as exc:
        raise SourcePlanError("source_applications_negative_coordinate_integrity") from exc
    successors = {row["old_target_id"]: row["new_target_id"] for row in lineage["matches"]}
    old_coordinates = {row["target_id"] for row in before["coordinates"]}
    targets: set[str] = set()
    refs: set[str] = set()
    matched = []
    unresolved_coordinates = []
    for negative in before["negatives"]:
        candidates = ([_gap_state(receipt, negative["interval"])] if negative["kind"] == "source_gap"
            else state["target" if negative["kind"] == "target_requirement" else negative["kind"]])
        if negative["kind"] in {"target", "context", "target_requirement"}:
            coordinate = negative.get("coordinate_id")
            if not isinstance(coordinate, str) or coordinate not in old_coordinates:
                raise SourcePlanError("source_applications_negative_coordinate_integrity")
            if coordinate in lineage["unresolved_old"]:
                refs.update(negative["refs"])
                unresolved_coordinates.append({"kind": negative["kind"], "old_target_id": coordinate})
                continue
            successor = successors.get(coordinate)
            candidates = [row for row in candidates if row["coordinate_id"] == successor]
        for row in candidates:
            if negative["kind"] == "target_requirement":
                effect = requirement_effect(negative["requirement"]["subject"], receipt, state, row["alias"])
                if not unchanged_requirement(negative["requirement_effect"], effect):
                    continue
                signature = negative["signature"]
            else:
                signature = (_target_signature(row, negative["repair_fields"])
                    if negative["kind"] == "target" else row["signature"])
            if row["cohort"] != negative["cohort"] or signature != negative["signature"]:
                continue
            if negative["kind"] in {"unit", "source_gap"}:
                refs.update(row["refs"])
            else:
                targets.update(row["target_ids"])
            matched.append({"kind": negative["kind"], "cohort": row["cohort"], "signature": signature})
    return {"policy": POLICY, "target_ids": sorted(targets), "unresolved_source_refs": sorted(refs),
        "unchanged_negatives": matched, "coordinate_lineage": lineage,
        "unresolved_coordinates": unresolved_coordinates, "semantic_approval": False}
