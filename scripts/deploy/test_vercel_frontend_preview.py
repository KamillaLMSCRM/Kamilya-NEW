from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import urllib.error


MODULE_PATH = Path(__file__).with_name("vercel_frontend_preview.py")
SPEC = importlib.util.spec_from_file_location("vercel_frontend_preview", MODULE_PATH)
assert SPEC and SPEC.loader
preview = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preview)


RELEASE = "1" * 40
DEV = "2" * 40
PACKET_SHA = "a" * 64


def packet_data() -> dict:
    return {
        "schema": "kamilya-vercel-frontend-preview-v1",
        "release_id": "REL-METHOD-GUIDE59-PREVIEW-20261016",
        "release_sha": RELEASE,
        "repository": "KamillaLMSCRM/Kamilya-NEW",
        "github": {"run_id": 73, "workflow": "CI", "event": "push"},
        "vercel": {
            "team_id": "team_test",
            "team_slug": "kamillalmscrms-projects",
            "project_id": "prj_test",
            "project_name": "kamilya-lms-dev",
            "github_repo_id": "123456",
            "production_branch": "dev",
            "root_directory": "apps/web",
            "expected_plan": "hobby",
            "stable_alias": "kamilya-lms-dev.vercel.app",
            "preview_api_url": "https://kamilya-lms-api.onrender.com/api",
        },
        "baseline": {
            "origin_dev_sha": DEV,
            "stable_alias_deployment_id": "dpl_stable",
            "render_api_service_id": "srv_api",
            "render_api_deployment_id": "dep-api",
            "render_worker_service_id": "srv_worker",
            "render_worker_deployment_id": "dep-worker",
        },
    }


class FakeProviders:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.origin_dev = DEV
        self.ci = {
            "head_sha": RELEASE,
            "name": "CI",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
        }
        self.project = {
            "team_id": "team_test",
            "team_slug": "kamillalmscrms-projects",
            "plan": "hobby",
            "project_id": "prj_test",
            "project_name": "kamilya-lms-dev",
            "root_directory": "apps/web",
            "production_branch": "dev",
            "repository": "KamillaLMSCRM/Kamilya-NEW",
            "github_repo_id": "123456",
            "git_type": "github",
        }
        self.api_url = "https://kamilya-lms-api.onrender.com/api"
        self.guard = True
        self.stable = {
            "id": "dpl_stable",
            "readyState": "READY",
            "target": "production",
            "url": "kamilya-lms-dev.vercel.app",
            "meta": {"githubCommitSha": DEV},
            "aliasAssigned": True,
        }
        self.render = {
            "srv_api": {
                "id": "dep-api",
                "status": "live",
                "commit": {"id": DEV},
            },
            "srv_worker": {
                "id": "dep-worker",
                "status": "live",
                "commit": {"id": DEV},
            },
        }
        self.created = {
            "id": "dpl_preview",
            "readyState": "QUEUED",
            "target": None,
            "url": "kamilya-preview.vercel.app",
            "gitSource": {"sha": RELEASE},
            "aliasAssigned": False,
        }
        self.preview = dict(self.created)
        self.find = [dict(self.created)]
        self.raise_unknown = False

    def remote_branch_sha(self, repository: str, branch: str) -> str:
        self.calls.append(("remote_branch_sha", repository, branch))
        return self.origin_dev

    def github_ci(self, repository: str, run_id: int) -> dict:
        self.calls.append(("github_ci", repository, run_id))
        return self.ci

    def source_api_guard(self, release_sha: str) -> bool:
        self.calls.append(("source_api_guard", release_sha))
        return self.guard

    def vercel_project(self, project_id: str, team_id: str) -> dict:
        self.calls.append(("vercel_project", project_id, team_id))
        return self.project

    def preview_api_url(self, project_id: str, team_id: str) -> str:
        self.calls.append(("preview_api_url", project_id, team_id))
        return self.api_url

    def deployment(self, identity: str, team_id: str) -> dict:
        self.calls.append(("deployment", identity, team_id))
        if identity == "kamilya-lms-dev.vercel.app":
            return self.stable
        return self.preview

    def render_deployment(self, service_id: str) -> dict:
        self.calls.append(("render_deployment", service_id))
        return self.render[service_id]

    def create_preview(self, packet: dict) -> dict:
        self.calls.append(("create_preview", packet["release_sha"]))
        if self.raise_unknown:
            raise preview.ProviderRequestUnknown("vercel_create_outcome_unknown")
        return self.created

    def find_previews(self, packet: dict) -> list[dict]:
        self.calls.append(("find_previews", packet["release_sha"]))
        return self.find


class ControllerCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state = self.root / ".release-evidence" / "preview.json"
        self.providers = FakeProviders()
        self.controller = preview.PreviewController(
            packet_data(),
            self.providers,
            self.state,
            PACKET_SHA,
            timeout_seconds=2,
            poll_seconds=0.01,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_preflight_verifies_exact_ci_project_api_and_protected_identities(self) -> None:
        result = self.controller.preflight()

        self.assertEqual(result["status"], "PREFLIGHT_OK")
        self.assertEqual(result["release_sha"], RELEASE)
        self.assertEqual(result["provider_contract"], "EXISTING_HOBBY_PROJECT")
        self.assertEqual(result["before"]["origin_dev_sha"], DEV)
        self.assertEqual(
            result["before"]["stable_alias"]["deployment_id"], "dpl_stable"
        )

    def test_preflight_rejects_ci_for_another_sha(self) -> None:
        self.providers.ci["head_sha"] = "3" * 40

        with self.assertRaisesRegex(preview.PreviewBlocked, "github_ci_sha_mismatch"):
            self.controller.preflight()

        self.assertNotIn("vercel_project", [call[0] for call in self.providers.calls])

    def test_preflight_rejects_non_hobby_or_wrong_project_contract(self) -> None:
        self.providers.project["plan"] = "pro"

        with self.assertRaisesRegex(
            preview.PreviewBlocked, "vercel_project_contract_mismatch"
        ):
            self.controller.preflight()

        self.assertNotIn("create_preview", [call[0] for call in self.providers.calls])

    def test_preflight_rejects_wrong_preview_api_url(self) -> None:
        self.providers.api_url = "https://api.kml.kz/api"

        with self.assertRaisesRegex(preview.PreviewBlocked, "preview_api_url_mismatch"):
            self.controller.preflight()

    def test_preflight_requires_exact_source_dev_api_guard(self) -> None:
        self.providers.guard = False

        with self.assertRaisesRegex(
            preview.PreviewBlocked, "source_dev_api_guard_missing"
        ):
            self.controller.preflight()

    def test_create_posts_once_and_persists_deployment_id(self) -> None:
        result = self.controller.create("REL-METHOD-GUIDE59-PREVIEW-20261016")

        self.assertEqual(result["status"], "CREATED")
        self.assertEqual(result["deployment_id"], "dpl_preview")
        saved = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(saved["operation"], "created")
        self.assertEqual(saved["deployment_id"], "dpl_preview")
        self.assertEqual(
            [call[0] for call in self.providers.calls].count("create_preview"), 1
        )

    def test_create_confirmation_stops_before_any_provider_call(self) -> None:
        with self.assertRaisesRegex(
            preview.PreviewBlocked, "create_confirmation_mismatch"
        ):
            self.controller.create("WRONG")

        self.assertEqual(self.providers.calls, [])

    def test_existing_state_forbids_duplicate_create(self) -> None:
        self.state.parent.mkdir(parents=True)
        self.state.write_text("{}", encoding="utf-8")

        with self.assertRaisesRegex(
            preview.PreviewBlocked, "state_exists_resume_or_reconcile_required"
        ):
            self.controller.create("REL-METHOD-GUIDE59-PREVIEW-20261016")

        self.assertEqual(self.providers.calls, [])

    def test_unknown_create_outcome_is_persisted_and_not_retried(self) -> None:
        self.providers.raise_unknown = True

        with self.assertRaisesRegex(
            preview.ProviderRequestUnknown, "vercel_create_outcome_unknown"
        ):
            self.controller.create("REL-METHOD-GUIDE59-PREVIEW-20261016")

        saved = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(saved["operation"], "create_outcome_unknown")
        self.assertNotIn("deployment_id", saved)
        self.assertEqual(
            [call[0] for call in self.providers.calls].count("create_preview"), 1
        )

    def test_reconcile_recovers_one_exact_preview_after_unknown_outcome(self) -> None:
        self.providers.raise_unknown = True
        with self.assertRaises(preview.ProviderRequestUnknown):
            self.controller.create("REL-METHOD-GUIDE59-PREVIEW-20261016")
        self.providers.preview["readyState"] = "BUILDING"
        generated_alias = (
            "kamilya-lms-dev-feature-guide-kamillalmscrms-projects.vercel.app"
        )
        self.providers.find[0]["alias"] = [generated_alias]
        self.providers.preview["alias"] = [generated_alias]

        result = self.controller.reconcile()

        self.assertEqual(result["status"], "BUILDING")
        saved = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(saved["deployment_id"], "dpl_preview")
        self.assertEqual(
            [call[0] for call in self.providers.calls].count("create_preview"), 1
        )

    def test_unknown_outcome_does_not_adopt_stable_alias_deployment(self) -> None:
        self.providers.raise_unknown = True
        with self.assertRaises(preview.ProviderRequestUnknown):
            self.controller.create("REL-METHOD-GUIDE59-PREVIEW-20261016")
        self.providers.find[0]["alias"] = ["kamilya-lms-dev.vercel.app"]

        with self.assertRaisesRegex(
            preview.PreviewBlocked, "unknown_outcome_preview_not_unique"
        ):
            self.controller.reconcile()

    def test_reconcile_unknown_outcome_requires_one_unique_match(self) -> None:
        self.providers.raise_unknown = True
        with self.assertRaises(preview.ProviderRequestUnknown):
            self.controller.create("REL-METHOD-GUIDE59-PREVIEW-20261016")
        self.providers.find = [dict(self.providers.created), dict(self.providers.created)]

        with self.assertRaisesRegex(
            preview.PreviewBlocked, "unknown_outcome_preview_not_unique"
        ):
            self.controller.reconcile()

    def test_wait_ready_proves_protected_identities_unchanged(self) -> None:
        self.controller.create("REL-METHOD-GUIDE59-PREVIEW-20261016")
        self.providers.preview["readyState"] = "READY"

        result = self.controller.wait()

        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["protected_identities"], "UNCHANGED")
        saved = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(saved["terminal_status"], "READY")
        self.assertEqual(saved["before"], saved["after"])

    def test_wait_terminal_error_is_preserved_and_blocked(self) -> None:
        self.controller.create("REL-METHOD-GUIDE59-PREVIEW-20261016")
        self.providers.preview["readyState"] = "ERROR"

        with self.assertRaisesRegex(
            preview.PreviewBlocked, "vercel_preview_terminal_error"
        ):
            self.controller.wait()

        saved = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(saved["terminal_status"], "ERROR")

    def test_wait_rejects_any_stable_alias_change(self) -> None:
        self.controller.create("REL-METHOD-GUIDE59-PREVIEW-20261016")
        self.providers.preview["readyState"] = "READY"
        self.providers.stable["id"] = "dpl_changed"

        with self.assertRaisesRegex(
            preview.PreviewBlocked, "stable_alias_deployment_changed"
        ):
            self.controller.wait()

    def test_production_target_is_forbidden(self) -> None:
        self.providers.created["target"] = "production"

        with self.assertRaisesRegex(
            preview.PreviewBlocked, "vercel_preview_target_mismatch"
        ):
            self.controller.create("REL-METHOD-GUIDE59-PREVIEW-20261016")

    def test_generated_preview_aliases_are_allowed(self) -> None:
        self.providers.created["aliasAssigned"] = True
        self.providers.created["alias"] = [
            "kamilya-lms-dev-feature-guide-kamillalmscrms-projects.vercel.app"
        ]

        result = self.controller.create("REL-METHOD-GUIDE59-PREVIEW-20261016")

        self.assertEqual(result["status"], "CREATED")
        self.assertEqual(result["deployment_id"], "dpl_preview")

    def test_stable_dev_alias_on_preview_is_forbidden(self) -> None:
        self.providers.created["aliasAssigned"] = True
        self.providers.created["alias"] = ["kamilya-lms-dev.vercel.app"]

        with self.assertRaisesRegex(
            preview.PreviewBlocked, "vercel_preview_stable_alias_assigned"
        ):
            self.controller.create("REL-METHOD-GUIDE59-PREVIEW-20261016")


class PacketAndAdapterCase(unittest.TestCase):
    def test_packet_digest_and_closed_schema(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "packet.json"
            path.write_text(json.dumps(packet_data()), encoding="utf-8")
            digest = preview.packet_digest(path)

            loaded = preview.load_packet(path, digest)
            self.assertEqual(loaded["release_sha"], RELEASE)

            changed = packet_data()
            changed["unexpected"] = True
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(
                preview.PreviewBlocked, "packet_unknown_or_missing_fields"
            ):
                preview.load_packet(path, preview.packet_digest(path))

    def test_state_must_be_under_release_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with self.assertRaisesRegex(
                preview.PreviewBlocked, "state_file_not_under_release_evidence"
            ):
                preview._state_path(root / "preview.json", root)

    def test_create_request_uses_exact_github_sha_and_omits_target(self) -> None:
        adapter = object.__new__(preview.LiveProviders)
        adapter.vercel_token = "synthetic"
        captured: dict = {}

        def fake_http(url, token, **kwargs):
            captured.update({"url": url, "token": token, **kwargs})
            return {
                "id": "dpl_preview",
                "readyState": "QUEUED",
                "target": None,
            }

        adapter._http_json = fake_http

        adapter.create_preview(packet_data())

        self.assertEqual(captured["method"], "POST")
        self.assertTrue(captured["create"])
        self.assertNotIn("target", captured["body"])
        self.assertNotIn("buildMachine", captured["body"])
        self.assertNotIn("env", captured["body"])
        self.assertEqual(
            captured["body"]["gitSource"],
            {
                "type": "github",
                "repoId": "123456",
                "org": "KamillaLMSCRM",
                "repo": "Kamilya-NEW",
                "ref": RELEASE,
                "sha": RELEASE,
            },
        )

    def test_live_adapter_reads_only_canonical_secret_names(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            env = root / ".env"
            env.write_text(
                "vercel_token=vercel-secret\nRENDER_API_KEY=render-secret\n",
                encoding="utf-8",
            )
            helper = root / "scripts" / "ops" / "with_project_github_token.py"
            helper.parent.mkdir(parents=True)
            helper.write_text("# synthetic\n", encoding="utf-8")

            adapter = preview.LiveProviders(root, env, 10)

            self.assertEqual(adapter.vercel_token, "vercel-secret")
            self.assertEqual(adapter.render_token, "render-secret")
            self.assertEqual(adapter.request_timeout_seconds, 10)

            capped = preview.LiveProviders(root, env, 1200)
            self.assertEqual(capped.request_timeout_seconds, 30)

    def test_create_http_transport_failure_has_unknown_outcome_and_no_retry(self) -> None:
        adapter = object.__new__(preview.LiveProviders)
        adapter.request_timeout_seconds = 1
        request_count = 0

        def fail_once(*_args, **_kwargs):
            nonlocal request_count
            request_count += 1
            raise TimeoutError("synthetic")

        with mock.patch.object(preview.urllib.request, "urlopen", fail_once):
            with self.assertRaisesRegex(
                preview.ProviderRequestUnknown, "vercel_create_outcome_unknown"
            ):
                adapter._http_json(
                    "https://api.vercel.com/v13/deployments",
                    "synthetic",
                    method="POST",
                    body={"name": "test"},
                    create=True,
                )

        self.assertEqual(request_count, 1)

    def test_create_http_rejection_is_known_failure_not_unknown_outcome(self) -> None:
        adapter = object.__new__(preview.LiveProviders)
        adapter.request_timeout_seconds = 1
        rejection = urllib.error.HTTPError(
            "https://api.vercel.com/v13/deployments", 400, "bad request", {}, None
        )

        with mock.patch.object(preview.urllib.request, "urlopen", side_effect=rejection):
            with self.assertRaisesRegex(preview.PreviewBlocked, "provider_http_400"):
                adapter._http_json(
                    "https://api.vercel.com/v13/deployments",
                    "synthetic",
                    method="POST",
                    body={"name": "test"},
                    create=True,
                )

    def test_create_http_5xx_has_unknown_outcome(self) -> None:
        adapter = object.__new__(preview.LiveProviders)
        adapter.request_timeout_seconds = 1
        rejection = urllib.error.HTTPError(
            "https://api.vercel.com/v13/deployments", 503, "upstream", {}, None
        )

        with mock.patch.object(preview.urllib.request, "urlopen", side_effect=rejection):
            with self.assertRaisesRegex(
                preview.ProviderRequestUnknown, "vercel_create_outcome_unknown"
            ):
                adapter._http_json(
                    "https://api.vercel.com/v13/deployments",
                    "synthetic",
                    method="POST",
                    body={"name": "test"},
                    create=True,
                )


if __name__ == "__main__":
    unittest.main()
