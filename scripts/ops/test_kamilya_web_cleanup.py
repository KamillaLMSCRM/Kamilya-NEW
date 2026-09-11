"""Destructive cleanup guards exercised only against disposable fixtures."""
import contextlib
import hashlib
import os
import sys
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("cleanup_helper", ROOT / "infra/deploy/kamilya-web-deploy.py")
helper = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = helper
SPEC.loader.exec_module(helper)


class CleanupTests(unittest.TestCase):
    old, current, rollback = "a" * 40, "b" * 40, "c" * 40

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.releases = self.base / "releases"
        self.releases.mkdir()
        self.incoming = self.base / "incoming"
        self.incoming.mkdir()
        self.incoming.chmod(0o700)
        for sha in (self.old, self.current, self.rollback):
            path = self.releases / sha
            path.mkdir()
            (path / "package.json").write_text('{"name":"fixture"}')
        for name, value in (("BASE", self.base), ("RELEASES", self.releases), ("INCOMING", self.incoming)):
            item = patch.object(helper, name, value)
            item.start(); self.addCleanup(item.stop)
        for name in ("require_baseline", "require_cleanup_dependencies", "require_cleanup_rollback", "require_cleanup_parent"):
            item = patch.object(helper, name)
            item.start(); self.addCleanup(item.stop)

    def test_current_and_rollback_are_never_candidates(self):
        for target in (self.current, self.rollback):
            with self.assertRaisesRegex(helper.DeployError, "cleanup_protected_release"):
                helper.cleanup_plan(target, self.current, self.rollback)
            self.assertTrue((self.releases / target).exists())

    def test_path_traversal_rejected(self):
        with self.assertRaises(helper.DeployError):
            helper.cleanup_plan("../" + self.old, self.current, self.rollback)

    def test_fingerprint_detects_same_size_content_change(self):
        first = helper.cleanup_plan(self.old, self.current, self.rollback)
        (self.releases / self.old / "package.json").write_text('{"name":"changed"}')
        second = helper.cleanup_plan(self.old, self.current, self.rollback)
        self.assertNotEqual(first["tree_sha256"], second["tree_sha256"])

    def test_cleanup_envelope_is_digest_bound_and_exact(self):
        incoming = self.incoming
        with patch.object(helper, "INCOMING", incoming):
            payload = {
                "release_sha": self.old,
                "current_sha": self.current,
                "rollback_sha": self.rollback,
                "tree_sha256": "d" * 64,
                "regular_file_bytes": 123,
                "recovery_archive_sha256": "e" * 64,
                "recovery_manifest_sha256": "f" * 64,
            }
            content = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
            digest = hashlib.sha256(content).hexdigest()
            path = incoming / f"cleanup-envelope-{digest}.json"
            path.write_bytes(content)
            path.chmod(0o600)
            with patch.object(helper, "require_cleanup_incoming"), patch.object(helper, "read_control_file", return_value=content):
                envelope, resolved = helper.read_cleanup_envelope(digest)
            self.assertEqual(envelope, payload)
            self.assertEqual(resolved, path)
            path.write_bytes(content + b"x")
            with patch.object(helper, "require_cleanup_incoming"), patch.object(helper, "read_control_file", return_value=content + b"x"), self.assertRaisesRegex(helper.DeployError, "cleanup_envelope_digest_mismatch"):
                helper.read_cleanup_envelope(digest)

    def test_recovery_record_must_match_exact_deployed_artifact(self):
        envelope = {
            "release_sha": self.old,
            "recovery_archive_sha256": "e" * 64,
            "recovery_manifest_sha256": "f" * 64,
        }
        exact = (json.dumps(envelope, sort_keys=True, separators=(",", ":")) + "\n").encode()
        with patch.object(helper, "RECOVERY_RECORDS", self.base), patch.object(
            helper, "require_root_directory"
        ), patch.object(helper, "read_root_control", return_value=exact):
            helper.require_recovery_record(envelope)
        changed = exact.replace(("e" * 64).encode(), ("d" * 64).encode())
        with patch.object(helper, "RECOVERY_RECORDS", self.base), patch.object(
            helper, "require_root_directory"
        ), patch.object(helper, "read_root_control", return_value=changed), self.assertRaisesRegex(
            helper.DeployError, "recovery_record_mismatch"
        ):
            helper.require_recovery_record(envelope)


@unittest.skipIf(sys.platform == "win32", "fd-relative cleanup requires Linux")
class CleanupExecutionTests(CleanupTests):
    def _envelope(self):
        plan = helper.cleanup_plan(self.old, self.current, self.rollback)
        return {
            **plan,
            "recovery_archive_sha256": "e" * 64,
            "recovery_manifest_sha256": "f" * 64,
        }, plan

    def _execution_patches(self, envelope, envelope_path, receipts):
        return (
            patch.object(helper, "RECEIPTS", receipts),
            patch.object(helper, "read_cleanup_envelope", return_value=(envelope, envelope_path)),
            patch.object(helper, "require_recovery_record"),
            patch.object(helper, "require_root_directory"),
            patch.object(helper, "deployment_lock", return_value=contextlib.nullcontext()),
            patch.object(helper.os, "chown"),
        )

    def test_cleanup_writes_started_then_completed_receipt_and_removes_only_target(self):
        envelope, plan = self._envelope()
        envelope_path = self.incoming / "envelope.json"
        envelope_path.write_text("fixture")
        receipts = self.base / "receipts"
        patches = self._execution_patches(envelope, envelope_path, receipts)
        for item in patches:
            item.start(); self.addCleanup(item.stop)
        result = helper.cleanup("1" * 64)
        self.assertEqual(result["status"], "CLEANED")
        self.assertFalse((self.releases / self.old).exists())
        self.assertTrue((self.releases / self.current).is_dir())
        self.assertTrue((self.releases / self.rollback).is_dir())
        receipt = receipts / ("1" * 64 + ".json")
        self.assertEqual(json.loads(receipt.read_text())["status"], "CLEANED")
        self.assertEqual(result["tree_sha256"], plan["tree_sha256"])

    def test_delete_failure_leaves_durable_failed_after_start_receipt(self):
        envelope, _ = self._envelope()
        envelope_path = self.incoming / "envelope.json"
        envelope_path.write_text("fixture")
        receipts = self.base / "receipts"
        patches = self._execution_patches(envelope, envelope_path, receipts)
        for item in patches:
            item.start(); self.addCleanup(item.stop)
        original = helper.shutil.rmtree

        def fail_remove(*args, **kwargs):
            raise OSError("fixture delete failure")

        fail_remove.avoids_symlink_attacks = original.avoids_symlink_attacks
        with patch.object(helper.shutil, "rmtree", fail_remove), self.assertRaisesRegex(
            helper.DeployError, "cleanup_delete_failed"
        ):
            helper.cleanup("2" * 64)
        receipt = receipts / ("2" * 64 + ".json")
        self.assertEqual(json.loads(receipt.read_text())["status"], "FAILED_AFTER_START")
        self.assertTrue((self.releases / self.old).is_dir())

    def test_post_delete_reserve_failure_leaves_durable_postcheck_receipt(self):
        envelope, _ = self._envelope()
        envelope_path = self.incoming / "envelope.json"
        envelope_path.write_text("fixture")
        receipts = self.base / "receipts"
        patches = self._execution_patches(envelope, envelope_path, receipts)
        for item in patches:
            item.start(); self.addCleanup(item.stop)
        enough = helper.MINIMUM_RESERVE_BYTES + 1
        with patch.object(
            helper.shutil,
            "disk_usage",
            side_effect=(SimpleNamespace(free=enough), SimpleNamespace(free=enough - 2)),
        ), self.assertRaisesRegex(helper.DeployError, "cleanup_reserve_breached"):
            helper.cleanup("3" * 64)
        receipt = receipts / ("3" * 64 + ".json")
        self.assertEqual(json.loads(receipt.read_text())["status"], "CLEANED_POSTCHECK_FAILED")
        self.assertFalse((self.releases / self.old).exists())
        self.assertTrue((self.releases / self.current).is_dir())
        self.assertTrue((self.releases / self.rollback).is_dir())

if __name__ == "__main__":
    unittest.main(verbosity=2)
