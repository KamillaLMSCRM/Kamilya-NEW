import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).with_name("release_plane_bundle.py")
SPEC = importlib.util.spec_from_file_location("release_plane_bundle", MODULE_PATH)
assert SPEC and SPEC.loader
bundle = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bundle
SPEC.loader.exec_module(bundle)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    for source, _, _ in bundle.FILES.values():
        path = repo / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"content:{source}\n", encoding="utf-8")
    return repo


def test_build_and_verify_are_deterministic(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    first = bundle.build(repo, tmp_path / "first", "a" * 40, "RPLANE-TEST-0001", "b" * 64)
    second = bundle.build(repo, tmp_path / "second", "a" * 40, "RPLANE-TEST-0001", "b" * 64)
    assert first == second
    assert bundle.verify(tmp_path / "first") == first
    assert first["files"]["runner_service"]["payload"].endswith(".service")
    assert first["files"]["host_config_schema"]["payload"].endswith(".json")


def test_verify_rejects_modified_payload(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    output = tmp_path / "bundle"
    manifest = bundle.build(repo, output, "a" * 40, "RPLANE-TEST-0002", "b" * 64)
    key = next(iter(manifest["files"]))
    (output / manifest["files"][key]["payload"]).write_text("tampered", encoding="utf-8")
    with pytest.raises(bundle.BundleError, match="payload_hash_mismatch"):
        bundle.verify(output)


def test_verify_rejects_manifest_identity_tampering(tmp_path: Path) -> None:
    output = tmp_path / "bundle"
    bundle.build(_repo(tmp_path), output, "a" * 40, "RPLANE-TEST-0003", "b" * 64)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["release_sha"] = "c" * 40
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(bundle.BundleError, match="bundle_identity_mismatch"):
        bundle.verify(output)


def test_bundle_hash_is_canonical_manifest_identity(tmp_path: Path) -> None:
    result = bundle.build(_repo(tmp_path), tmp_path / "bundle", "a" * 40, "RPLANE-TEST-0004", "b" * 64)
    identity = {key: value for key, value in result.items() if key != "bundle_sha256"}
    assert result["bundle_sha256"] == hashlib.sha256(bundle._canonical(identity)).hexdigest()
