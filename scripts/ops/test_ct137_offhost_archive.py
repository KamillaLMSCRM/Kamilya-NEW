import pytest

import ct137_landing_release as landing
from ct137_archive_store import ArchiveError, require_names


SHA = "a" * 40
PREVIOUS = "b" * 40
DIGEST = "c" * 64


def test_landing_release_stops_before_upload_if_archive_cannot_be_verified(monkeypatch):
    calls = []
    monkeypatch.setattr(landing, "command", lambda *_: calls.append("preflight"))
    monkeypatch.setattr(landing.transport, "stream", lambda *_: calls.append("stage"))

    def unavailable(*_):
        calls.append("archive")
        raise ArchiveError("offhost_archive_publish_unverified")

    with pytest.raises(ArchiveError, match="offhost_archive_publish_unverified"):
        landing.execute(object(), SHA, PREVIOUS, DIGEST, {}, publish=unavailable)
    assert calls == ["preflight", "archive"]


def test_landing_release_archives_exact_source_before_upload(monkeypatch, tmp_path):
    calls = []

    def remote(client, script, timeout):
        if "doas -n" in script:
            calls.append("deploy")
            return f"DEPLOY_OK release={SHA} digest={DIGEST}"
        calls.append("readback")
        return ""

    def publish(kind, sha, files):
        calls.append("archive")
        assert kind == "landing" and sha == SHA
        assert set(files) == {"source.tar.gz", "source.sha256"}
        return {"release_sha": sha}

    class Response:
        status = 200
        headers = {"X-Kamilya-Landing-Release": SHA}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(landing, "command", remote)
    monkeypatch.setattr(landing.transport, "stream", lambda *_: calls.append("stage"))
    monkeypatch.setattr(landing.urllib.request, "urlopen", lambda *_args, **_kw: Response())
    files = {"source.tar.gz": (tmp_path / "source.tar.gz", DIGEST),
             "source.sha256": (tmp_path / "source.sha256", DIGEST)}
    receipt = landing.execute(object(), SHA, PREVIOUS, DIGEST, files, publish=publish)
    assert calls == ["readback", "archive", "readback", "stage", "deploy", "readback"]
    assert receipt["offhost_archive"]["release_sha"] == SHA


def test_archive_rejects_missing_metadata_and_unexpected_files():
    require_names("web", SHA, {f"frontend-native-{SHA}.tar.gz", "bundle.sha256", "manifest.json"})
    require_names("landing", SHA, {"source.tar.gz", "source.sha256"})
    with pytest.raises(ArchiveError, match="archive_manifest_invalid"):
        require_names("web", SHA, {f"frontend-native-{SHA}.tar.gz", "bundle.sha256"})
    with pytest.raises(ArchiveError, match="archive_package_files_invalid"):
        require_names("landing", SHA, {"source.tar.gz", "source.sha256", ".env"})
