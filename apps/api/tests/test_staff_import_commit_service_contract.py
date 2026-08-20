from pathlib import Path

SERVICE = Path(__file__).parents[1] / "app" / "modules" / "staff_import_sessions" / "commit_service.py"


def test_commit_rechecks_approved_revision_hash_and_locks_session() -> None:
    source = SERVICE.read_text(encoding="utf-8")
    assert "for_update=True" in source
    assert "approved proposal revision mismatch" in source
    assert "approved proposal hash mismatch" in source
    assert "compute_proposal_hash" in source


def test_commit_is_additive_atomic_and_preserves_legacy_roots() -> None:
    source = SERVICE.read_text(encoding="utf-8")
    assert "LEGACY_ROOT_EXTERNAL_KEY" in source
    assert '"deleted": 0' in source
    assert "db.commit" not in source
    assert "MatchAction.SKIP" in source
    assert "MatchAction.CONFLICT" in source
    assert '"rules_recompute_state": "pending"' in source
    assert "apply_rules_for_users" in source


def test_commit_reclassifies_approved_legacy_branch_without_replacing_id() -> None:
    source = SERVICE.read_text(encoding="utf-8")
    assert 'unit.unit_type = "branch"' in source
    assert "unit.legacy_root = False" in source
    assert "units_by_external[proposal.external_key] = unit" in source


def test_position_lock_excludes_nullable_eager_join() -> None:
    source = SERVICE.read_text(encoding="utf-8")
    assert ".with_for_update(of=Position)" in source
    assert "select(Position).where(Position.tenant_id == tenant_id).with_for_update()" not in source
