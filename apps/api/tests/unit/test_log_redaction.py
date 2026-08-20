from __future__ import annotations

import logging
from pathlib import Path

from app.core import debug_log_buffer
from app.core.log_redaction import SensitiveDataFilter, redact_sensitive_text, scrub_sensitive_data

SYNTHETIC_EMAIL = "person@example.test"
SYNTHETIC_PHONE = "+7 777 123 45 67"
SYNTHETIC_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.synthetic-signature"


def test_redact_sensitive_text_removes_common_credentials_and_pii() -> None:
    raw = (
        f"email={SYNTHETIC_EMAIL} phone={SYNTHETIC_PHONE} "
        f"Authorization: Bearer {SYNTHETIC_JWT} "
        "personnel_number=T-1042 pin=123456 password=hunter2 "
        "url=/access/demo-token?token=secret-capability&code=654321"
    )

    redacted = redact_sensitive_text(raw)

    for secret in (
        SYNTHETIC_EMAIL,
        SYNTHETIC_PHONE,
        SYNTHETIC_JWT,
        "T-1042",
        "123456",
        "hunter2",
        "secret-capability",
        "654321",
    ):
        assert secret not in redacted
    assert "<redacted-email>" in redacted
    assert "<redacted-phone>" in redacted
    assert "<redacted-token>" in redacted


def test_logging_filter_redacts_formatted_message_and_sensitive_extra() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="delivery failed for %s at %s",
        args=(SYNTHETIC_EMAIL, SYNTHETIC_PHONE),
        exc_info=None,
    )
    record.api_token = "top-secret"  # type: ignore[attr-defined]
    record.provider = "resend"  # type: ignore[attr-defined]

    assert SensitiveDataFilter().filter(record) is True

    rendered = record.getMessage()
    assert SYNTHETIC_EMAIL not in rendered
    assert SYNTHETIC_PHONE not in rendered
    assert record.api_token == "<redacted>"  # type: ignore[attr-defined]
    assert record.provider == "resend"  # type: ignore[attr-defined]


def test_logging_filter_redacts_exception_text_before_formatting() -> None:
    try:
        raise RuntimeError(f"provider rejected {SYNTHETIC_EMAIL} {SYNTHETIC_JWT}")
    except RuntimeError:
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="provider failure",
            args=(),
            exc_info=__import__("sys").exc_info(),
        )

    assert SensitiveDataFilter().filter(record) is True
    rendered = logging.Formatter("%(message)s").format(record)
    assert SYNTHETIC_EMAIL not in rendered
    assert SYNTHETIC_JWT not in rendered
    assert "RuntimeError" in rendered


def test_debug_buffer_is_a_redaction_boundary() -> None:
    debug_log_buffer.clear()

    debug_log_buffer._record(  # noqa: SLF001 - boundary regression test
        "INFO",
        f"contact={SYNTHETIC_EMAIL}; phone={SYNTHETIC_PHONE}; token={SYNTHETIC_JWT}",
    )

    message = debug_log_buffer.get_recent(limit=1)[0]["message"]
    assert SYNTHETIC_EMAIL not in message
    assert SYNTHETIC_PHONE not in message
    assert SYNTHETIC_JWT not in message


def test_sentry_event_scrubber_removes_nested_sensitive_values() -> None:
    event = {
        "request": {
            "headers": {"Authorization": f"Bearer {SYNTHETIC_JWT}"},
            "data": {"email": SYNTHETIC_EMAIL, "safe_count": 3},
        },
        "exception": {"values": [{"value": f"failed for {SYNTHETIC_PHONE}"}]},
    }

    scrubbed = scrub_sensitive_data(event)

    rendered = repr(scrubbed)
    assert SYNTHETIC_EMAIL not in rendered
    assert SYNTHETIC_PHONE not in rendered
    assert SYNTHETIC_JWT not in rendered
    assert scrubbed["request"]["data"]["safe_count"] == 3


def test_ai_regeneration_logs_never_include_raw_model_fragments() -> None:
    router_source = (
        Path(__file__).resolve().parents[2] / "app" / "modules" / "ai" / "router.py"
    ).read_text(encoding="utf-8")

    assert "plan_text[:200]" not in router_source
    assert "assess_text[:200]" not in router_source
    assert "bad JSON, using raw text as title. Got:" not in router_source
    assert "bad JSON for quiz, skipping. Got:" not in router_source


def test_source_logs_do_not_emit_document_names_or_provider_response_fragments() -> None:
    app_root = Path(__file__).resolve().parents[2] / "app"
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            app_root / "modules" / "ai" / "ingestion.py",
            app_root / "modules" / "ai" / "tasks.py",
            app_root / "modules" / "ai" / "architect.py",
            app_root / "modules" / "positions" / "jd_router.py",
            app_root / "modules" / "integrations" / "wa_gateway_client.py",
        )
    )

    for forbidden in (
        "start file={filename}",
        "Ingesting document: {file_path}",
        "doc_list_result[:300]",
        "audit failed for {item.filename}",
        "invalid JSON for {item.filename}",
        "error for {item.filename}",
        '"detail": detail',
    ):
        assert forbidden not in sources
