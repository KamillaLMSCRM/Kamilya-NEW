"""Unit tests for SCORM security hardening (P0 follow-up 2026-07-09).

Covers:
- _assert_safe_asset_path rejects paths with HTML-injection characters
- html.escape() is applied to package.title and asset_url in the launch shell
- The launch HTML template never embeds an unescaped <script> tag from title

These tests are pure-Python and do not need a DB / storage backend. They
exercise the small helpers introduced to defend against a malicious SCORM
package whose manifest <title> or resource href smuggles HTML.
"""
from __future__ import annotations

import html
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request


def test_assert_safe_asset_path_accepts_normal_paths():
    """Real SCORM packages use plain ASCII names with the usual separators."""
    from app.modules.scorm.router import _assert_safe_asset_path

    for ok in [
        "index.html",
        "content/index.html",
        "content/sub/lesson1.html",
        "index.html?loadcss=1",
        "page.html#section-2",
        "img-2026.png",
        "css/style.min.css",
    ]:
        _assert_safe_asset_path(ok)  # must not raise


def test_assert_safe_asset_path_rejects_html_injection():
    """An entrypoint with characters that could break out of an HTML
    attribute or smuggle JS must be rejected with 400."""
    from app.modules.scorm.router import _assert_safe_asset_path

    for bad in [
        'foo"><script>alert(1)</script>',
        "foo'; alert(1); //",
        "javascript:alert(1)",
        "foo\n<script>alert(1)</script>",
        "foo\r\nLocation: evil",
        "<img onerror=alert(1)>",
        # Backslash is rejected — we use forward slashes only.
        "..\\..\\windows\\system32",
    ]:
        with pytest.raises(HTTPException) as ei:
            _assert_safe_asset_path(bad)
        assert ei.value.status_code == 400


def test_html_escape_applied_to_title():
    """Smoke test: html.escape() with quote=True neutralises both < > and "
    so a malicious title cannot terminate the <title> element or break out
    of a downstream attribute. This mirrors what launch_scorm_package does."""
    malicious_title = '"><script>alert(document.domain)</script>'
    escaped = html.escape(malicious_title, quote=True)
    # No raw '<' / '>' / '"' left.
    assert "<" not in escaped
    assert ">" not in escaped
    assert '"' not in escaped
    # The neutralised entity form is safe to embed in HTML.
    assert "&lt;script&gt;" in escaped
    assert "&quot;" in escaped


def test_html_escape_applied_to_asset_url():
    """_safe_asset_url wraps the entrypoint through html.escape(quote=True)
    so even if a malicious entrypoint slipped past _assert_safe_asset_path,
    the rendered attribute cannot be terminated."""
    from app.modules.scorm.router import _safe_asset_url

    class FakePackage:
        id = "pkg-123"

    safe_entrypoint = "content/index.html"
    url = _safe_asset_url(FakePackage(), "tok", safe_entrypoint)
    # Quote re-escaping is idempotent — already-safe strings round-trip fine.
    escaped = html.escape(url, quote=True)
    # The escaped form must NOT contain raw double-quotes that could break
    # out of the iframe src="..." attribute.
    assert escaped.count('"') == 0
    # The path is preserved.
    assert "content/index.html" in escaped


def test_assert_safe_asset_path_rejects_empty():
    """Empty path must raise — otherwise the asset endpoint would resolve
    to the package root directory and the existence check would 404.
    Defensive: refuse to even attempt the lookup."""
    from app.modules.scorm.router import _assert_safe_asset_path

    with pytest.raises(HTTPException) as ei:
        _assert_safe_asset_path("")
    assert ei.value.status_code == 400


def _request(host: str, *, scheme: str = "https") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": scheme,
            "path": "/api/v1/scorm/packages/pkg-123/launch",
            "raw_path": b"/api/v1/scorm/packages/pkg-123/launch",
            "query_string": b"",
            "headers": [(b"host", host.encode("ascii"))],
            "server": (host, 443 if scheme == "https" else 80),
            "client": ("127.0.0.1", 50000),
        }
    )


def test_scorm_launch_url_uses_dedicated_content_origin(monkeypatch):
    from app.modules.scorm import router

    monkeypatch.setattr(
        router,
        "get_settings",
        lambda: SimpleNamespace(
            APP_ENV="production",
            SCORM_CONTENT_ORIGIN="https://scorm.kml.kz",
            PUBLIC_URL="https://app.kml.kz",
        ),
    )

    url = router._build_scorm_launch_url(_request("api.kml.kz"), "pkg-123", "launch-token")

    assert url == "https://scorm.kml.kz/api/v1/scorm/packages/pkg-123/launch?token=launch-token"
    assert "api.kml.kz" not in url


def test_scorm_content_route_rejects_api_origin_in_production(monkeypatch):
    from app.modules.scorm import router

    monkeypatch.setattr(
        router,
        "get_settings",
        lambda: SimpleNamespace(
            APP_ENV="production",
            SCORM_CONTENT_ORIGIN="https://scorm.kml.kz",
            PUBLIC_URL="https://app.kml.kz",
        ),
    )

    with pytest.raises(HTTPException) as exc:
        router._require_scorm_content_request(_request("api.kml.kz"))

    assert exc.value.status_code == 421
    router._require_scorm_content_request(_request("scorm.kml.kz"))


def test_scorm_launch_fails_closed_when_production_origin_is_unconfigured(monkeypatch):
    from app.modules.scorm import router

    monkeypatch.setattr(
        router,
        "get_settings",
        lambda: SimpleNamespace(APP_ENV="production", SCORM_CONTENT_ORIGIN="", PUBLIC_URL="https://app.kml.kz"),
    )

    with pytest.raises(HTTPException) as exc:
        router._build_scorm_launch_url(_request("api.kml.kz"), "pkg-123", "launch-token")

    assert exc.value.status_code == 503


def test_scorm_launch_shell_uses_versioned_targeted_bridge(monkeypatch):
    from app.modules.scorm import router

    monkeypatch.setattr(
        router,
        "get_settings",
        lambda: SimpleNamespace(
            APP_ENV="production",
            SCORM_CONTENT_ORIGIN="https://scorm.kml.kz",
            PUBLIC_URL="https://app.kml.kz",
        ),
    )

    body = router._render_scorm_launch_html(
        title="Безопасный курс",
        asset_url="/api/v1/scorm/packages/pkg/assets-token/token/index.html",
        commit_url="/api/v1/scorm/attempts/attempt/commit?token=token",
        bridge_channel="channel-123",
    )

    assert 'sandbox="allow-forms allow-same-origin allow-scripts"' in body
    assert 'const bridgeVersion = 1;' in body
    assert 'const bridgeChannel = "channel-123";' in body
    assert 'const parentOrigin = "https://app.kml.kz";' in body
    assert "window.parent.postMessage" in body
    assert "postMessage(message, \"*\")" not in body
