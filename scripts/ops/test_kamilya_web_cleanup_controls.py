"""Unprivileged Linux tests for the native web cleanup control guards."""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "kamilya_web_cleanup_controls", ROOT / "infra/deploy/kamilya-web-deploy.py"
)
assert SPEC and SPEC.loader
helper = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = helper
SPEC.loader.exec_module(helper)


@unittest.skipIf(sys.platform == "win32", "Linux descriptor and FIFO semantics required")
class RootControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    @staticmethod
    def _with_uid(info, uid):
        values = list(info)
        values[4] = uid
        return os.stat_result(values)

    def _read_with_uid(self, path, uid=0):
        real_fstat = os.fstat

        def fixture_fstat(fd):
            info = real_fstat(fd)
            return self._with_uid(info, uid)

        with mock.patch.object(helper.os, "fstat", side_effect=fixture_fstat):
            return helper.read_root_control(path)

    def test_read_root_control_accepts_fixture_file_with_emulated_root_owner(self):
        path = self.root / "control"
        path.write_bytes(b"approved\n")
        path.chmod(0o600)
        self.assertEqual(self._read_with_uid(path), b"approved\n")

    def test_read_root_control_rejects_real_symlink(self):
        target = self.root / "target"
        target.write_bytes(b"not a control")
        target.chmod(0o600)
        link = self.root / "control"
        link.symlink_to(target)
        with self.assertRaisesRegex(helper.DeployError, "cleanup_control_unreadable"):
            helper.read_root_control(link)

    def test_read_root_control_rejects_fifo_without_blocking(self):
        path = self.root / "control.fifo"
        os.mkfifo(path, 0o600)
        with self.assertRaisesRegex(helper.DeployError, "cleanup_control_permissions"):
            self._read_with_uid(path)

    def test_read_root_control_rejects_wrong_owner_mode_and_size(self):
        cases = (("owner", 0o600, 0, 1234), ("mode", 0o644, 0, 0), ("size", 0o600, 2049, 0))
        for label, mode, size, uid in cases:
            with self.subTest(label=label):
                path = self.root / label
                path.write_bytes(b"x" * size)
                path.chmod(mode)
                with self.assertRaisesRegex(helper.DeployError, "cleanup_control_(permissions|size)"):
                    self._read_with_uid(path, uid)

    def test_require_root_directory_rejects_wrong_owner_mode_and_non_directory(self):
        path = self.root / "parent"
        path.mkdir()
        real_lstat = Path.lstat

        def lstat_with_uid(target):
            info = real_lstat(target)
            return self._with_uid(info, 1234 if target == path else info.st_uid)

        with mock.patch.object(Path, "lstat", lstat_with_uid):
            with self.assertRaisesRegex(helper.DeployError, "cleanup_control_parent_permissions"):
                helper.require_root_directory(path)
        path.chmod(0o755)
        with mock.patch.object(Path, "lstat", lambda target: self._with_uid(real_lstat(target), 0)):
            with self.assertRaisesRegex(helper.DeployError, "cleanup_control_parent_permissions"):
                helper.require_root_directory(path, 0o700)
        file_path = self.root / "file"
        file_path.write_bytes(b"x")
        with self.assertRaisesRegex(helper.DeployError, "cleanup_control_parent_permissions"):
            helper.require_root_directory(file_path)


@unittest.skipIf(sys.platform == "win32", "Linux ownership and mode semantics required")
class EnvelopeAndRollbackTests(unittest.TestCase):
    current = "b" * 40
    rollback = "c" * 40
    release = "a" * 40

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.real_fstat = os.fstat
        self.releases = self.base / "releases"
        self.releases.mkdir()
        self.backups = self.base / "deploy-backups"
        self.backups.mkdir()
        self.backups.chmod(0o700)
        rollback_dir = self.releases / self.rollback
        rollback_dir.mkdir()
        (rollback_dir / "package.json").write_text("{}")
        self.incoming = self.base / "incoming"
        self.incoming.mkdir()
        self.incoming.chmod(0o700)
        self.patches = [
            mock.patch.object(helper, "BASE", self.base),
            mock.patch.object(helper, "RELEASES", self.releases),
            mock.patch.object(helper, "INCOMING", self.incoming),
            mock.patch.object(helper, "require_root_directory"),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def _read_fstat_root(self, fd):
        info = self.real_fstat(fd)
        values = list(info)
        values[4] = 0
        return os.stat_result(values)

    def _control_read(self):
        return mock.patch.object(helper.os, "fstat", side_effect=self._read_fstat_root)

    def plan(self):
        return {
            "release_sha": self.release,
            "current_sha": self.current,
            "rollback_sha": self.rollback,
            "tree_sha256": "d" * 64,
            "regular_file_bytes": 123,
            "recovery_archive_sha256": "e" * 64,
            "recovery_manifest_sha256": "f" * 64,
        }

    def write_envelope(self, payload):
        content = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
        digest = helper.hashlib.sha256(content).hexdigest()
        envelope = self.incoming / f"cleanup-envelope-{digest}.json"
        envelope.write_bytes(content)
        envelope.chmod(0o600)
        return digest

    def test_cleanup_envelope_rejects_malformed_mismatched_and_missing_fields(self):
        plan = self.plan()
        for label, payload, expected in (
            ("malformed", b"{", "cleanup_envelope_invalid"),
            ("unexpected-field", {**plan, "unexpected": True}, "cleanup_envelope_fields"),
            ("missing-digest", {key: value for key, value in plan.items() if key != "recovery_manifest_sha256"}, "cleanup_envelope_fields"),
        ):
            with self.subTest(label=label):
                content = payload if isinstance(payload, bytes) else (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
                digest = helper.hashlib.sha256(content).hexdigest()
                path = self.incoming / f"cleanup-envelope-{digest}.json"
                path.write_bytes(content)
                path.chmod(0o600)
                with self.assertRaisesRegex(helper.DeployError, expected):
                    helper.read_cleanup_envelope(digest)
                path.unlink()

    def test_cleanup_envelope_accepts_exact_fields_and_digest(self):
        plan = self.plan()
        digest = self.write_envelope(plan)
        envelope, path = helper.read_cleanup_envelope(digest)
        self.assertEqual(envelope, plan)
        self.assertEqual(path.name, f"cleanup-envelope-{digest}.json")

    def test_require_cleanup_rollback_rejects_absent_and_mismatched_marker(self):
        for label, marker_value, expected in (
            ("absent", None, "cleanup_rollback_mismatch"),
            ("mismatch", self.rollback[:-1] + "d", "cleanup_rollback_mismatch"),
        ):
            with self.subTest(label=label):
                marker = self.backups / f"20260910-{self.current}.marker"
                if marker_value is not None:
                    marker.write_text(marker_value)
                    marker.chmod(0o600)
                with self._control_read(), self.assertRaisesRegex(helper.DeployError, expected):
                    helper.require_cleanup_rollback(self.current, self.rollback)

    def test_require_cleanup_rollback_rejects_non_ascii_marker(self):
        marker = self.backups / f"20260910-{self.current}.marker"
        marker.write_bytes(self.rollback.encode() + "✓".encode())
        marker.chmod(0o600)
        with self._control_read(), self.assertRaisesRegex(helper.DeployError, "cleanup_rollback_invalid"):
            helper.require_cleanup_rollback(self.current, self.rollback)

    def test_require_cleanup_rollback_accepts_matching_marker_and_release(self):
        marker = self.backups / f"20260910-{self.current}.marker"
        marker.write_text(self.rollback + "\n")
        marker.chmod(0o600)
        with self._control_read():
            helper.require_cleanup_rollback(self.current, self.rollback)


if __name__ == "__main__":
    unittest.main(verbosity=2)
