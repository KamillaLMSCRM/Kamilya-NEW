import httpx
import pytest

from app.modules.ai import converter_remote


@pytest.mark.asyncio
async def test_unconfigured_converter_never_opens_http(monkeypatch, tmp_path):
    monkeypatch.setattr(converter_remote, "DOCLING_URL", "")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: pytest.fail("unexpected HTTP client"))
    source = tmp_path / "note.txt"
    source.write_text("source text", encoding="utf-8")
    assert (await converter_remote.DocumentConverter().convert(str(source)))["markdown"] == "source text"
    binary = tmp_path / "doc.pdf"
    binary.write_bytes(b"synthetic")
    with pytest.raises(RuntimeError, match="unavailable"):
        await converter_remote.DocumentConverter().convert(str(binary))


@pytest.mark.asyncio
async def test_explicit_converter_url_is_used(monkeypatch, tmp_path):
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs):
            calls.append(url)
            return httpx.Response(200, json={"markdown": "converted"}, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"synthetic")
    result = await converter_remote.DocumentConverter("https://fixture.invalid/").convert(str(source))
    assert calls == ["https://fixture.invalid/convert"]
    assert result["markdown"] == "converted"


@pytest.mark.asyncio
async def test_configured_url_connection_error_never_logs_url(monkeypatch, tmp_path, caplog):
    secret_url = "https://synthetic-user:synthetic-secret@fixture.invalid/?token=synthetic-token"
    monkeypatch.setattr(converter_remote, "DOCLING_URL", secret_url)
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs):
            calls.append(url)
            raise httpx.ConnectError("sensitive connection detail")
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    source = tmp_path / "note.txt"
    source.write_text("source text", encoding="utf-8")
    assert (await converter_remote.DocumentConverter().convert(str(source)))["markdown"] == "source text"
    assert calls == [secret_url + "/convert"]
    assert "synthetic-secret" not in caplog.text
    assert "synthetic-token" not in caplog.text
    assert "sensitive connection detail" not in caplog.text
