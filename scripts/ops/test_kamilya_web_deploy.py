"""Security and input contracts for infra/deploy/kamilya-web-deploy.py."""

from __future__ import annotations

import importlib.util
import io
import os
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("kamilya_web_deploy", ROOT / "infra/deploy/kamilya-web-deploy.py")
assert SPEC and SPEC.loader
deploy = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = deploy
SPEC.loader.exec_module(deploy)


def member(name: str, kind: bytes = tarfile.REGTYPE, link: str = "", size: int = 0) -> tarfile.TarInfo:
    item = tarfile.TarInfo(name)
    item.type = kind
    item.linkname = link
    item.size = size
    return item


def valid_members() -> list[tarfile.TarInfo]:
    return [
        member(".next", tarfile.DIRTYPE),
        member(".next/BUILD_ID", size=40),
        member("node_modules", tarfile.DIRTYPE),
        member("package.json", size=2),
        member("next.config.js", size=1),
        member("security-headers.js", size=1),
    ]


class InputValidationTests(unittest.TestCase):
    def test_hex_values_are_lowercase_and_exact_length(self) -> None:
        self.assertEqual(deploy.require_hex("a" * 40, "sha", 40), "a" * 40)
        for value in ("A" * 40, "a" * 39, "a" * 40 + ";id", "../" + "a" * 37):
            with self.assertRaises(deploy.DeployError):
                deploy.require_hex(value, "sha", 40)

    def test_fixed_incoming_path_cannot_be_overridden(self) -> None:
        sha = "3c0519310d2c435de740eb5aad098b07bf012b1f"
        self.assertEqual(str(deploy.archive_for(sha)).replace("\\", "/"), f"/home/kamilya-admin/incoming/frontend-native-{sha}.tar.gz")
        self.assertEqual(str(deploy.sidecar_for(sha)).replace("\\", "/"), f"/home/kamilya-admin/incoming/frontend-native-{sha}.manifest.json")
        self.assertIn("doas install -o root -g root -m 0750", deploy.INSTALL_COMMAND)

    def test_deploy_cli_has_only_required_values(self) -> None:
        parsed = deploy.parse_args(["deploy", "a" * 40, "b" * 40, "c" * 64])
        self.assertEqual((parsed.sha, parsed.expected_old, parsed.archive_sha256), ("a" * 40, "b" * 40, "c" * 64))
        with self.assertRaises(SystemExit):
            deploy.parse_args(["deploy", "a" * 40, "b" * 40, "c" * 64, "--archive", "/tmp/x"])


class ArchiveSafetyTests(unittest.TestCase):
    def test_traversal_absolute_windows_and_duplicate_paths_fail(self) -> None:
        for bad in ("../package.json", "/package.json", "node_modules\\evil", "a//b"):
            with self.subTest(bad=bad), self.assertRaises(deploy.DeployError):
                deploy.validate_archive_members([member(bad)])
        with self.assertRaises(deploy.DeployError):
            deploy.validate_archive_members([member("package.json"), member("package.json")])

    def test_devices_and_members_below_symlinks_fail(self) -> None:
        for kind in (tarfile.CHRTYPE, tarfile.FIFOTYPE):
            with self.subTest(kind=kind), self.assertRaises(deploy.DeployError):
                deploy.validate_archive_members([member("bad", kind)])
        with self.assertRaises(deploy.DeployError):
            deploy.validate_archive_members([member("node_modules", tarfile.SYMTYPE, "safe"), member("node_modules/child")])

    def test_confined_node_modules_hardlink_is_allowed_and_escape_rejected(self) -> None:
        layout = deploy.validate_archive_members([
            member("node_modules", tarfile.DIRTYPE),
            member("node_modules/target", size=1),
            member("node_modules/link", tarfile.LNKTYPE, "node_modules/target"),
        ])
        self.assertTrue(layout.members["node_modules/link"].islnk())
        with self.assertRaises(deploy.DeployError):
            deploy.validate_archive_members([member("node_modules/link", tarfile.LNKTYPE, "../etc")])

    def test_relative_confined_symlink_chain_is_allowed(self) -> None:
        layout = deploy.validate_archive_members([
            member("node_modules", tarfile.DIRTYPE),
            member("node_modules/store", tarfile.DIRTYPE),
            member("node_modules/store/pkg", tarfile.DIRTYPE),
            member("node_modules/a", tarfile.SYMTYPE, "store/pkg"),
            member("node_modules/b", tarfile.SYMTYPE, "a"),
        ])
        self.assertIn("node_modules/b", layout.members)

    def test_escaping_dangling_and_cyclic_symlinks_fail(self) -> None:
        cases = [
            [member("node_modules", tarfile.DIRTYPE), member("node_modules/a", tarfile.SYMTYPE, "../../etc")],
            [member("node_modules", tarfile.DIRTYPE), member("node_modules/a", tarfile.SYMTYPE, "missing")],
            [member("node_modules", tarfile.DIRTYPE), member("node_modules/a", tarfile.SYMTYPE, "b"), member("node_modules/b", tarfile.SYMTYPE, "a")],
        ]
        for members in cases:
            with self.assertRaises(deploy.DeployError):
                deploy.validate_archive_members(members)

    def test_required_ready_build_shape_and_forbidden_content(self) -> None:
        layout = deploy.validate_archive_members(valid_members())
        deploy.require_artifact_shape(layout)
        for forbidden in (".git/config", ".env", ".env.production"):
            with self.subTest(forbidden=forbidden), self.assertRaises(deploy.DeployError):
                deploy.require_artifact_shape(deploy.validate_archive_members(valid_members() + [member(forbidden)]))

    def test_top_level_allowlist_and_bomb_caps_fail_closed(self) -> None:
        with self.assertRaises(deploy.DeployError):
            deploy.require_artifact_shape(deploy.validate_archive_members(valid_members() + [member("surprise/file")]))
        original_members, original_expanded = deploy.MAX_MEMBERS, deploy.MAX_EXPANDED_BYTES
        try:
            deploy.MAX_MEMBERS = 2
            with self.assertRaises(deploy.DeployError):
                deploy.validate_archive_members([member("a"), member("b"), member("c")])
            deploy.MAX_EXPANDED_BYTES = 2
            with self.assertRaises(deploy.DeployError):
                deploy.expanded_size(deploy.validate_archive_members([member("a", size=3)]))
        finally:
            deploy.MAX_MEMBERS, deploy.MAX_EXPANDED_BYTES = original_members, original_expanded

    def test_snapshot_refuses_oversized_source_before_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.write_bytes(b"1234")
            with self.assertRaises(deploy.DeployError):
                deploy.snapshot_file(source, None, root / "snapshots", "test-", 3)


class IdentityTests(unittest.TestCase):
    SHA = "3c0519310d2c435de740eb5aad098b07bf012b1f"

    def tar_with(self, extra: dict[str, bytes]) -> tarfile.TarFile:
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w:gz") as output:
            files = {
                ".next/BUILD_ID": self.SHA.encode(),
                "package.json": b'{"name":"web"}',
                "next.config.js": b"x",
                "security-headers.js": b"x",
            }
            files.update(extra)
            for directory in (".next", "node_modules"):
                item = tarfile.TarInfo(directory)
                item.type = tarfile.DIRTYPE
                output.addfile(item)
            for name, contents in files.items():
                item = tarfile.TarInfo(name)
                item.size = len(contents)
                output.addfile(item, io.BytesIO(contents))
        stream.seek(0)
        return tarfile.open(fileobj=stream, mode="r:gz")

    def test_optional_build_sha_is_verified_without_embedded_manifest(self) -> None:
        with self.tar_with({}) as archive:
            layout = deploy.validate_archive_members(archive.getmembers())
            deploy.validate_identity(archive, layout, self.SHA)

    def test_package_git_head_and_hex_build_id_cannot_disagree(self) -> None:
        wrong = "e463527cd8f5e67e987c44d8d769f337714bd25f"
        with self.tar_with({"package.json": (b'{"gitHead":"' + wrong.encode() + b'"}')}) as archive:
            layout = deploy.validate_archive_members(archive.getmembers())
            with self.assertRaises(deploy.DeployError):
                deploy.validate_identity(archive, layout, self.SHA)
        with self.tar_with({".next/BUILD_ID": wrong.encode()}) as archive:
            layout = deploy.validate_archive_members(archive.getmembers())
            with self.assertRaises(deploy.DeployError):
                deploy.validate_identity(archive, layout, self.SHA)

    def test_sidecar_binds_sha_digest_and_runtime(self) -> None:
        digest = "4" * 64
        payload = {
            "release_sha": self.SHA, "product_version": "0.3.1", "node_version": "20.19.0",
            "platform": "linux", "arch": "x64", "libc": "musl", "api_url": "https://api.kml.kz/api", "sha256": digest,
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            path.write_text(__import__("json").dumps(payload), encoding="utf-8")
            deploy.validate_sidecar(path, self.SHA, digest)
            payload["release_sha"] = "e463527cd8f5e67e987c44d8d769f337714bd25f"
            path.write_text(__import__("json").dumps(payload), encoding="utf-8")
            with self.assertRaises(deploy.DeployError):
                deploy.validate_sidecar(path, self.SHA, digest)


@unittest.skipUnless(os.name != "nt", "requires Unix symlink semantics; run unprivileged on CT137")
class RollbackTests(unittest.TestCase):
    def test_rollback_restores_symlink_marker_and_nginx_state(self) -> None:
        old = "e463527cd8f5e67e987c44d8d769f337714bd25f"
        new = "3c0519310d2c435de740eb5aad098b07bf012b1f"
        original = {name: getattr(deploy, name) for name in ("BASE", "RELEASES", "CURRENT", "MARKER", "NGINX")}
        original_run, original_baseline = deploy.run_checked, deploy.require_baseline
        original_wait, original_chown = deploy.wait_for_application_routes, deploy.os.chown
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                deploy.BASE = root
                deploy.RELEASES = root / "releases"
                deploy.RELEASES.mkdir()
                old_release, new_release = deploy.RELEASES / old, deploy.RELEASES / new
                old_release.mkdir(); new_release.mkdir()
                deploy.CURRENT = root / "current"
                os.symlink(new_release, deploy.CURRENT)
                deploy.MARKER = root / "marker"
                deploy.MARKER.write_text(new + "\n", encoding="ascii")
                deploy.NGINX = root / "nginx.conf"
                deploy.NGINX.write_text("new nginx", encoding="utf-8")
                nginx_backup, marker_backup = root / "backup.nginx", root / "backup.marker"
                nginx_backup.write_text("old nginx", encoding="utf-8")
                marker_backup.write_text(old + "\n", encoding="ascii")
                deploy.run_checked = lambda *args: None
                deploy.require_baseline = lambda expected: self.assertEqual(expected, old)
                deploy.wait_for_application_routes = lambda routes: self.assertEqual(routes, ("/login",))
                deploy.os.chown = lambda *args: None
                deploy.rollback(old, nginx_backup, marker_backup, new_release)
                self.assertEqual(deploy.CURRENT.resolve(), old_release)
                self.assertEqual(deploy.MARKER.read_text(encoding="ascii"), old + "\n")
                self.assertEqual(deploy.NGINX.read_text(encoding="utf-8"), "old nginx")
                self.assertFalse(new_release.exists())
                self.assertEqual(len(list(deploy.RELEASES.glob(new + ".failed.*"))), 1)
        finally:
            deploy.run_checked, deploy.require_baseline = original_run, original_baseline
            deploy.wait_for_application_routes, deploy.os.chown = original_wait, original_chown
            for name, value in original.items():
                setattr(deploy, name, value)


class SourceContractTests(unittest.TestCase):
    def test_no_build_dependency_install_or_landing_port(self) -> None:
        source = (ROOT / "infra/deploy/kamilya-web-deploy.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("pnpm install", source)
        self.assertNotIn("next build", source)
        self.assertNotIn("docker", source)
        self.assertNotIn("3001", source)
        self.assertIn("safe_extract", source)
        self.assertIn("snapshot_archive", source)
        self.assertIn("if copied > max_bytes", source)
        self.assertIn("validate_archive_members(tar)", source)
        self.assertIn("wait_for_application_routes((\"/login\", \"/admin/settings/ai\"))", source)
        status_source = source[source.index("def status"):source.index("def tree_fingerprint")]
        self.assertNotIn("deployment_lock", status_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
