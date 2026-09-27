import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = Path(__file__).with_name("dev_release_controller.py")
SPEC = importlib.util.spec_from_file_location("dev_release_controller", MODULE_PATH)
controller = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = controller
SPEC.loader.exec_module(controller)

PREVIOUS = "1" * 40
RELEASE = "2" * 40


def packet_data() -> dict:
    return {
        "schema": "kamilya-dev-release-v1",
        "release_id": "REL-DEV-ECC-20260927-001",
        "release_sha": RELEASE,
        "expected_previous_sha": PREVIOUS,
        "repository": "KamillaLMSCRM/Kamilya-NEW",
        "branch": "dev",
        "migration_scope": "none",
        "github": {"workflow": "CI"},
        "vercel": {
            "project_id": "prj_test",
            "project_name": "kamilya-lms-dev",
            "team_id": "team_test",
            "expected_plan": "hobby",
            "public_url": "https://dev.example.test/login",
        },
        "render": {
            "api_service_id": "srv_api",
            "worker_service_id": "srv_worker",
            "expected_plan": "free",
            "api_auto_deploy": "yes",
            "worker_auto_deploy": "no",
            "api_health_url": "https://api.example.test/api/v1/health",
            "worker_health_url": "https://worker.example.test/",
        },
    }


class FakeProviders:
    def __init__(self, *, branch_sha: str = PREVIOUS) -> None:
        self.branch_sha = branch_sha
        self.calls: list[tuple] = []
        self.ci = {"status": "completed", "conclusion": "success", "run_id": 73}
        self.vercel = {
            "status": "READY",
            "deployment_id": "dpl_1",
            "release_sha": RELEASE,
            "plan": "hobby",
        }
        self.vercel_project_data = {
            "project_id": "prj_test",
            "project_name": "kamilya-lms-dev",
            "branch": "dev",
            "plan": "hobby",
        }
        self.render_services = {
            "srv_api": {"plan": "free", "branch": "dev", "auto_deploy": "yes"},
            "srv_worker": {"plan": "free", "branch": "dev", "auto_deploy": "no"},
        }
        self.render_deploys = {
            "srv_api": {
                "status": "live",
                "deployment_id": "dep_api",
                "release_sha": RELEASE,
            },
            "srv_worker": {
                "status": "live",
                "deployment_id": "dep_worker",
                "release_sha": RELEASE,
            },
        }
        self.existing_render: dict[str, dict | None] = {
            "srv_api": None,
            "srv_worker": None,
        }
        self.health = {
            "https://api.example.test/api/v1/health": {
                "status": "ok",
                "deployment_environment": "render-development",
                "release_sha": RELEASE,
            },
            "https://worker.example.test/": "ok",
            "https://dev.example.test/login": {"http_status": 200},
        }

    def remote_branch_sha(self, repository: str, branch: str) -> str:
        self.calls.append(("remote_branch_sha", repository, branch))
        return self.branch_sha

    def push_exact_sha(self, repository: str, branch: str, release_sha: str) -> None:
        self.calls.append(("push_exact_sha", repository, branch, release_sha))
        self.branch_sha = release_sha

    def wait_github_ci(self, repository: str, workflow: str, release_sha: str) -> dict:
        self.calls.append(("wait_github_ci", repository, workflow, release_sha))
        return self.ci

    def wait_vercel(self, project_id: str, team_id: str, release_sha: str) -> dict:
        self.calls.append(("wait_vercel", project_id, team_id, release_sha))
        return self.vercel

    def vercel_project(self, project_id: str, team_id: str) -> dict:
        self.calls.append(("vercel_project", project_id, team_id))
        return self.vercel_project_data

    def render_service(self, service_id: str) -> dict:
        self.calls.append(("render_service", service_id))
        return self.render_services[service_id]

    def trigger_render(self, service_id: str, release_sha: str) -> str:
        self.calls.append(("trigger_render", service_id, release_sha))
        return self.render_deploys[service_id]["deployment_id"]

    def find_render(self, service_id: str, release_sha: str):
        self.calls.append(("find_render", service_id, release_sha))
        return self.existing_render[service_id]

    def wait_render(
        self, service_id: str, deployment_id: str, release_sha: str
    ) -> dict:
        self.calls.append(("wait_render", service_id, deployment_id, release_sha))
        return self.render_deploys[service_id]

    def read_health(self, url: str):
        self.calls.append(("read_health", url))
        return self.health[url]


class DevReleaseControllerTests(unittest.TestCase):
    def _packet(self, root: Path, mutate=None) -> tuple[Path, str]:
        data = packet_data()
        if mutate:
            mutate(data)
        path = root / "packet.json"
        encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        path.write_bytes(encoded)
        return path, hashlib.sha256(encoded).hexdigest()

    def test_digest_bound_packet_rejects_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            packet, _ = self._packet(Path(temporary))
            with self.assertRaisesRegex(
                controller.DevReleaseBlocked, "release_packet_digest_mismatch"
            ):
                controller.load_packet(packet, "0" * 64)

    def test_packet_rejects_schema_changes_from_routine_dev_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            packet, digest = self._packet(
                Path(temporary),
                lambda value: value.__setitem__("migration_scope", "schema"),
            )
            with self.assertRaisesRegex(
                controller.DevReleaseBlocked, "schema_gate_required"
            ):
                controller.load_packet(packet, digest)

    def test_execute_runs_one_exact_deterministic_dev_release(self) -> None:
        providers = FakeProviders()
        release = controller.DevReleaseController(packet_data(), providers)

        result = release.execute("REL-DEV-ECC-20260927-001")

        self.assertEqual(result["status"], "RELEASE_OK")
        self.assertEqual(result["release_sha"], RELEASE)
        self.assertEqual(result["previous_release_sha"], PREVIOUS)
        self.assertEqual(result["github_ci"]["run_id"], 73)
        self.assertEqual(result["vercel"]["deployment_id"], "dpl_1")
        self.assertEqual(result["render"]["api"]["deployment_id"], "dep_api")
        self.assertEqual(result["render"]["worker"]["deployment_id"], "dep_worker")
        self.assertEqual(result["health"]["api"]["release_sha"], RELEASE)
        self.assertEqual(result["health"]["worker"], "ok")
        self.assertLess(len(json.dumps(result, sort_keys=True)), 4096)
        self.assertEqual(
            providers.calls[0],
            ("remote_branch_sha", "KamillaLMSCRM/Kamilya-NEW", "dev"),
        )
        self.assertIn(
            ("push_exact_sha", "KamillaLMSCRM/Kamilya-NEW", "dev", RELEASE),
            providers.calls,
        )

    def test_execute_fails_closed_before_push_when_previous_sha_changed(self) -> None:
        providers = FakeProviders(branch_sha="3" * 40)
        release = controller.DevReleaseController(packet_data(), providers)

        with self.assertRaisesRegex(
            controller.DevReleaseBlocked, "expected_previous_sha_mismatch"
        ):
            release.execute("REL-DEV-ECC-20260927-001")

        self.assertNotIn("push_exact_sha", [call[0] for call in providers.calls])

    def test_execute_rejects_paid_or_unknown_provider_plan_before_render_mutation(
        self,
    ) -> None:
        providers = FakeProviders()
        providers.render_services["srv_worker"]["plan"] = "starter"
        release = controller.DevReleaseController(packet_data(), providers)

        with self.assertRaisesRegex(
            controller.DevReleaseBlocked, "render_plan_mismatch"
        ):
            release.execute("REL-DEV-ECC-20260927-001")

        self.assertNotIn("trigger_render", [call[0] for call in providers.calls])

    def test_execute_rejects_vercel_plan_before_push(self) -> None:
        providers = FakeProviders()
        providers.vercel_project_data["plan"] = "pro"
        release = controller.DevReleaseController(packet_data(), providers)

        with self.assertRaisesRegex(
            controller.DevReleaseBlocked, "vercel_plan_mismatch"
        ):
            release.execute("REL-DEV-ECC-20260927-001")

        self.assertNotIn("push_exact_sha", [call[0] for call in providers.calls])

    def test_execute_reuses_exact_autodeploy_instead_of_triggering_duplicate(
        self,
    ) -> None:
        providers = FakeProviders()
        providers.existing_render["srv_api"] = {
            "status": "build_in_progress",
            "deployment_id": "dep_api",
            "release_sha": RELEASE,
        }
        release = controller.DevReleaseController(packet_data(), providers)

        result = release.execute("REL-DEV-ECC-20260927-001")

        self.assertEqual(result["status"], "RELEASE_OK")
        self.assertNotIn(("trigger_render", "srv_api", RELEASE), providers.calls)
        self.assertIn(("trigger_render", "srv_worker", RELEASE), providers.calls)

    def test_reconcile_is_read_only_and_verifies_existing_release(self) -> None:
        providers = FakeProviders(branch_sha=RELEASE)
        release = controller.DevReleaseController(packet_data(), providers)

        result = release.reconcile()

        self.assertEqual(result["status"], "RECONCILED")
        self.assertNotIn("push_exact_sha", [call[0] for call in providers.calls])
        self.assertNotIn("trigger_render", [call[0] for call in providers.calls])
        self.assertLess(len(json.dumps(result, sort_keys=True)), 4096)

    def test_confirmation_mismatch_stops_before_provider_calls(self) -> None:
        providers = FakeProviders()
        release = controller.DevReleaseController(packet_data(), providers)

        with self.assertRaisesRegex(
            controller.DevReleaseBlocked, "execute_confirmation_mismatch"
        ):
            release.execute("WRONG")

        self.assertEqual(providers.calls, [])

    def test_render_list_adapter_unwraps_paginated_deploy_records(self) -> None:
        adapter = object.__new__(controller.LiveProviderAdapter)
        adapter.render_token = "secret-not-printed"
        adapter._http_json = lambda *_args, **_kwargs: [
            {
                "deploy": {
                    "id": "dep_1",
                    "status": "live",
                    "commit": {"id": RELEASE},
                },
                "cursor": "cursor_1",
            }
        ]

        result = adapter._render_deploys("srv_api")

        self.assertEqual(result[0]["id"], "dep_1")
        self.assertEqual(result[0]["commit"]["id"], RELEASE)

    def test_health_failure_names_the_public_endpoint(self) -> None:
        providers = FakeProviders(branch_sha=RELEASE)

        def fail_worker(url: str):
            if url.endswith("worker.example.test/"):
                raise controller.DevReleaseBlocked("public_health_request_failed")
            return providers.health[url]

        providers.read_health = fail_worker
        release = controller.DevReleaseController(packet_data(), providers)

        with self.assertRaisesRegex(
            controller.DevReleaseBlocked, "worker_health_request_failed"
        ):
            release.reconcile()


if __name__ == "__main__":
    unittest.main()
