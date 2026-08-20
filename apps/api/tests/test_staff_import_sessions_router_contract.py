from pathlib import Path

ROUTER = Path(__file__).parents[1] / "app" / "modules" / "staff_import_sessions" / "router.py"
MAIN = Path(__file__).parents[1] / "app" / "main.py"


def test_adaptive_import_routes_are_registered_and_preview_only() -> None:
    source = ROUTER.read_text(encoding="utf-8")
    main = MAIN.read_text(encoding="utf-8")
    assert 'prefix="/admin/staff/import/sessions"' in source
    assert '@router.post("/analyze"' in source
    assert '@router.post("/{session_id}/mapping"' in source
    assert '@router.post("/{session_id}/corrections"' in source
    assert '@router.get("/{session_id}"' in source
    assert '@router.post("/{session_id}/approve"' in source
    assert '@router.post("/{session_id}/commit"' in source
    assert "staff_import_sessions_router" in main
    assert "commit_import(" not in source
    assert "commit_approved_import_session" in source
    assert "source_object_key" in source
    assert "get_storage().get_bytes" in source
    assert "stored source workbook failed integrity verification" in source
    assert "apply_proposal_corrections" in source
    assert "record.proposal_revision != body.revision" in source


def test_upload_is_bounded_and_does_not_log_source_rows() -> None:
    source = ROUTER.read_text(encoding="utf-8")
    assert "MAX_IMPORT_BYTES" in source
    assert "sha256(content).hexdigest()" in source
    assert "invalid_source_row" in source
    assert "logger.info(content" not in source
    assert "logger.debug(content" not in source
    assert "get_storage().delete_bytes" in source


def test_approved_mapping_becomes_a_hint_not_an_approval_bypass() -> None:
    source = ROUTER.read_text(encoding="utf-8")
    assert "ensure_approved_mapping_profile" in source
    assert "mapping_id: Annotated[UUID | None, Form()]" in source
    assert "StaffImportMapping.id == mapping_id" in source
    assert "StaffImportMapping.tenant_id == user.tenant_id" in source
    assert "cleanup_expired_import_sources" in source
    assert "import session expired; upload the workbook again" in source
    assert "cleanup_expired_import_sources_task.apply_async" in source
    assert "eta=record.expires_at" in source
    assert "mode is ImportMode.FULL_RECONCILIATION" in source
    assert "status.HTTP_409_CONFLICT" in source
    assert "approve_import_session" in source
    assert "save_proposal" in source
