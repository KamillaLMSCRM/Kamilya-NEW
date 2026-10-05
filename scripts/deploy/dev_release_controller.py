#!/usr/bin/env python3
"""Deterministic, digest-bound controller for one Kamilya DEV release.

The public seam is intentionally small: load one immutable packet, then either
reconcile the exact DEV identity read-only or execute that exact release.  All
provider details live behind the injected adapter used by the controller.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
RELEASE_ID_RE = re.compile(r"^REL-[A-Z0-9][A-Z0-9-]{7,95}$")
PACKET_SCHEMA = "kamilya-dev-release-v1"
ACTIVATION_SCHEMA = "kamilya-dev-release-v2"
PURGE_ACTIVATION_SCHEMA = "kamilya-dev-release-v3"
DOCUMENT_ACTIVATION_SCHEMA = "kamilya-dev-release-v4"
CORRECTION_ACTIVATION_SCHEMA = "kamilya-dev-release-v5"
ACTIVATION_REVISIONS = {
    ACTIVATION_SCHEMA: "0172",
    PURGE_ACTIVATION_SCHEMA: "0173",
    DOCUMENT_ACTIVATION_SCHEMA: "0175",
    CORRECTION_ACTIVATION_SCHEMA: "0178",
}
API_WORKBENCH_KEY = "METHODOLOGIST_WORKBENCH_ENABLED"
WEB_WORKBENCH_KEY = "NEXT_PUBLIC_METHODOLOGIST_WORKBENCH_ENABLED"
API_DOCUMENT_DRAFT_KEY = "METHODOLOGIST_DOCUMENT_DRAFT_ENABLED"
WEB_DOCUMENT_DRAFT_KEY = "NEXT_PUBLIC_METHODOLOGIST_DOCUMENT_DRAFT_ENABLED"
API_CORRECTION_KEY = "METHODOLOGIST_LESSON_CORRECTION_ENABLED"
WEB_CORRECTION_KEY = "NEXT_PUBLIC_METHODOLOGIST_LESSON_CORRECTION_ENABLED"
DEV_PROJECT_REF_SHA256 = "5b535773cb7222384bbb54ad3f8c2e741fa6176bec4ce586abcd82d17ee0062e"


class DevReleaseBlocked(RuntimeError):
    """Fail-closed outcome safe to expose as a compact reason code."""


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise DevReleaseBlocked("project_env_missing")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        name, value = raw.split("=", 1)
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if name and value:
            values[name] = value
    return values


def _required_secret(values: Mapping[str, str], *names: str) -> str:
    for name in names:
        value = values.get(name)
        if value:
            return value
    raise DevReleaseBlocked(f"provider_secret_missing_{names[0].lower()}")


class ProviderAdapter(Protocol):
    repo_root: Path

    def remote_branch_sha(self, repository: str, branch: str) -> str: ...

    def push_exact_sha(
        self, repository: str, branch: str, release_sha: str
    ) -> None: ...

    def wait_github_ci(
        self, repository: str, workflow: str, release_sha: str
    ) -> Mapping[str, Any]: ...

    def wait_vercel(
        self, project_id: str, team_id: str, release_sha: str
    ) -> Mapping[str, Any]: ...

    def vercel_project(self, project_id: str, team_id: str) -> Mapping[str, Any]: ...

    def render_service(self, service_id: str) -> Mapping[str, Any]: ...

    def trigger_render(self, service_id: str, release_sha: str) -> str: ...

    def find_render(
        self, service_id: str, release_sha: str
    ) -> Mapping[str, Any] | None: ...

    def wait_render(
        self, service_id: str, deployment_id: str, release_sha: str
    ) -> Mapping[str, Any]: ...

    def read_health(self, url: str) -> Any: ...

    def verify_source_ci(self, run_id: int, release_sha: str, repository: str) -> Mapping[str, Any]: ...

    def workbench_flags(self, packet: Mapping[str, Any]) -> Mapping[str, bool]: ...

    def set_workbench_flags(self, packet: Mapping[str, Any], enabled: bool) -> list[str]: ...

    def document_draft_flags(self, packet: Mapping[str, Any]) -> Mapping[str, bool]: ...

    def set_document_draft_flags(self, packet: Mapping[str, Any], enabled: bool) -> list[str]: ...

    def correction_flags(self, packet: Mapping[str, Any]) -> Mapping[str, bool]: ...

    def set_correction_flags(self, packet: Mapping[str, Any], enabled: bool) -> list[str]: ...


class LiveProviderAdapter:
    """Production adapters for the existing free Kamilya DEV resources."""

    def __init__(
        self,
        *,
        repo_root: Path,
        env_file: Path,
        timeout_seconds: int = 1200,
        poll_seconds: float = 5.0,
    ) -> None:
        self.repo_root = repo_root.resolve()
        values = _read_env_file(env_file)
        self.vercel_token = _required_secret(values, "vercel_token", "VERCEL_TOKEN")
        self.render_token = _required_secret(values, "RENDER_API_KEY")
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds
        self.github_helper = self.repo_root / "scripts/ops/with_project_github_token.py"
        if not self.github_helper.is_file():
            raise DevReleaseBlocked("canonical_github_helper_missing")

    def _project_command(self, command: list[str], *, timeout: int = 60):
        completed = subprocess.run(
            [
                sys.executable,
                str(self.github_helper),
                "--repo",
                str(self.repo_root),
                "--",
                *command,
            ],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )
        if completed.returncode != 0:
            raise DevReleaseBlocked("project_command_failed")
        return completed

    def _gh(self, args: list[str]) -> Any:
        try:
            completed = self._project_command(["gh", "api", *args])
        except DevReleaseBlocked as exc:
            raise DevReleaseBlocked("github_api_failed") from exc
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise DevReleaseBlocked("github_api_json_invalid") from exc

    def _http_json(
        self,
        url: str,
        token: str,
        *,
        method: str = "GET",
        body: Mapping[str, Any] | None = None,
    ) -> Any:
        encoded = None
        if body is not None:
            encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=encoded,
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "Kamilya-DEV-Release-Controller/1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            raise DevReleaseBlocked("provider_http_failed") from exc
        try:
            return json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DevReleaseBlocked("provider_json_invalid") from exc

    def _wait(self, probe, terminal, reason: str) -> Any:
        deadline = time.monotonic() + self.timeout_seconds
        last = None
        while time.monotonic() < deadline:
            last = probe()
            if terminal(last):
                return last
            time.sleep(self.poll_seconds)
        raise DevReleaseBlocked(reason)

    def remote_branch_sha(self, repository: str, branch: str) -> str:
        result = self._gh([f"repos/{repository}/git/ref/heads/{branch}"])
        try:
            return str(result["object"]["sha"])
        except (KeyError, TypeError) as exc:
            raise DevReleaseBlocked("github_branch_identity_invalid") from exc

    def push_exact_sha(self, repository: str, branch: str, release_sha: str) -> None:
        del repository  # Origin identity is validated by the canonical helper.
        try:
            self._project_command(
                [
                    "git",
                    "-c",
                    "credential.helper=",
                    "-c",
                    "credential.helper=!gh auth git-credential",
                    "push",
                    "--porcelain",
                    "origin",
                    f"{release_sha}:refs/heads/{branch}",
                ],
                timeout=120,
            )
        except DevReleaseBlocked as exc:
            raise DevReleaseBlocked("github_push_failed") from exc

    def wait_github_ci(
        self, repository: str, workflow: str, release_sha: str
    ) -> Mapping[str, Any]:
        endpoint = (
            f"repos/{repository}/actions/runs?head_sha={release_sha}"
            "&branch=dev&event=push&per_page=20"
        )

        def probe() -> Mapping[str, Any]:
            response = self._gh([endpoint])
            runs = (
                response.get("workflow_runs", [])
                if isinstance(response, Mapping)
                else []
            )
            matches = [
                run
                for run in runs
                if run.get("name") == workflow and run.get("head_sha") == release_sha
            ]
            if not matches:
                return {"status": "waiting", "conclusion": None, "run_id": None}
            run = max(matches, key=lambda item: int(item.get("id", 0)))
            return {
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
                "run_id": run.get("id"),
            }

        result = self._wait(
            probe,
            lambda item: item.get("status") == "completed",
            "github_ci_timeout",
        )
        return result

    def vercel_project(self, project_id: str, team_id: str) -> Mapping[str, Any]:
        team = self._http_json(
            f"https://api.vercel.com/v2/teams/{urllib.parse.quote(team_id)}",
            self.vercel_token,
        )
        project = self._http_json(
            "https://api.vercel.com/v9/projects/"
            f"{urllib.parse.quote(project_id)}?teamId={urllib.parse.quote(team_id)}",
            self.vercel_token,
        )
        return {
            "project_id": project.get("id"),
            "project_name": project.get("name"),
            "branch": (project.get("link") or {}).get("productionBranch"),
            "plan": (team.get("billing") or {}).get("plan"),
        }

    def wait_vercel(
        self, project_id: str, team_id: str, release_sha: str
    ) -> Mapping[str, Any]:
        query = urllib.parse.urlencode(
            {
                "projectId": project_id,
                "teamId": team_id,
                "sha": release_sha,
                "branch": "dev",
                "limit": 20,
            }
        )

        def probe() -> Mapping[str, Any]:
            response = self._http_json(
                f"https://api.vercel.com/v7/deployments?{query}", self.vercel_token
            )
            deployments = response.get("deployments", [])
            if not deployments:
                return {
                    "status": "WAITING",
                    "deployment_id": None,
                    "release_sha": release_sha,
                }
            deployment = max(
                deployments, key=lambda item: int(item.get("createdAt", 0) or 0)
            )
            return {
                "status": deployment.get("readyState"),
                "deployment_id": deployment.get("uid") or deployment.get("id"),
                "release_sha": release_sha,
            }

        result = dict(
            self._wait(
                probe,
                lambda item: item.get("status")
                in {"READY", "ERROR", "CANCELED", "BLOCKED"},
                "vercel_deployment_timeout",
            )
        )
        result["plan"] = self.vercel_project(project_id, team_id)["plan"]
        return result

    def verify_source_ci(self, run_id: int, release_sha: str, repository: str) -> Mapping[str, Any]:
        run = self._gh([f"repos/{repository}/actions/runs/{run_id}"])
        if run.get("name") != "CI":
            raise DevReleaseBlocked("configuration_source_ci_workflow_mismatch")
        return {
            "status": run.get("status"), "conclusion": run.get("conclusion"),
            "release_sha": run.get("head_sha"), "branch": run.get("head_branch"),
            "event": run.get("event"), "run_id": run.get("id"),
        }

    def _render_flag_url(self, service: str) -> str:
        return f"https://api.render.com/v1/services/{urllib.parse.quote(service, safe='')}/env-vars/{API_WORKBENCH_KEY}"

    def _render_env_inventory_url(self, service: str) -> str:
        return f"https://api.render.com/v1/services/{urllib.parse.quote(service, safe='')}/env-vars"

    def _vercel_flag_url(self, packet: Mapping[str, Any]) -> str:
        cfg = _require_mapping(packet, "vercel")
        return f"https://api.vercel.com/v10/projects/{urllib.parse.quote(str(cfg['project_id']), safe='')}/env?teamId={urllib.parse.quote(str(cfg['team_id']), safe='')}"

    def _vercel_workbench_value(self, packet: Mapping[str, Any]) -> bool:
        result = self._http_json(self._vercel_flag_url(packet), self.vercel_token)
        rows = result.get("envs") if isinstance(result, Mapping) else None
        if not isinstance(rows, list):
            raise DevReleaseBlocked("vercel_flag_inventory_invalid")
        matches = [row for row in rows if isinstance(row, Mapping) and row.get("key") == WEB_WORKBENCH_KEY and "production" in row.get("target", [])]
        if (len(matches) != 1 or matches[0].get("target") != ["production"]
                or matches[0].get("type") != "plain"):
            raise DevReleaseBlocked("vercel_flag_scope_ambiguous")
        return _literal_flag(matches[0].get("value"))

    def workbench_flags(self, packet: Mapping[str, Any]) -> Mapping[str, bool]:
        cfg = _require_mapping(packet, "render")
        flags = {}
        for label, field in (("api", "api_service_id"), ("worker", "worker_service_id")):
            row = self._http_json(self._render_flag_url(str(cfg[field])), self.render_token)
            flags[label] = _literal_flag(row.get("value") if isinstance(row, Mapping) else None)
        flags["frontend"] = self._vercel_workbench_value(packet)
        return flags

    def set_workbench_flags(self, packet: Mapping[str, Any], enabled: bool) -> list[str]:
        if type(enabled) is not bool:
            raise DevReleaseBlocked("workbench_enabled_invalid")
        # Inventory every flag before the first mutation. Each single-key update
        # is read back immediately; a partial failure stops remaining updates.
        before = self.workbench_flags(packet)
        literal = "true" if enabled else "false"
        cfg = _require_mapping(packet, "render")
        changed = []
        for label, field in (("api", "api_service_id"), ("worker", "worker_service_id")):
            if before[label] is enabled:
                continue
            url = self._render_flag_url(str(cfg[field]))
            self._http_json(url, self.render_token, method="PUT", body={"value": literal})
            row = self._http_json(url, self.render_token)
            if not isinstance(row, Mapping) or _literal_flag(row.get("value")) is not enabled:
                raise DevReleaseBlocked(f"{label}_flag_readback_mismatch")
            changed.append(label)
        if before["frontend"] is not enabled:
            self._http_json(
                self._vercel_flag_url(packet) + "&upsert=true", self.vercel_token,
                method="POST", body={"key": WEB_WORKBENCH_KEY, "value": literal, "type": "plain", "target": ["production"]},
            )
            if self._vercel_workbench_value(packet) is not enabled:
                raise DevReleaseBlocked("frontend_flag_readback_mismatch")
            changed.append("frontend")
        return changed

    def _render_document_value(self, packet: Mapping[str, Any], service: str) -> bool:
        return self._render_feature_value(service, API_DOCUMENT_DRAFT_KEY, "document")

    def _render_feature_value(self, service: str, key: str, label: str) -> bool:
        result = self._render_document_inventory(service)
        matches = []
        for row in result:
            env = row["envVar"]
            if env.get("key") == key:
                matches.append(env)
        if len(matches) > 1:
            raise DevReleaseBlocked(f"render_{label}_flag_duplicate")
        if not matches:
            return False
        return _literal_flag(matches[0].get("value"), reason=f"{label}_flag_not_literal")

    def _render_document_inventory(self, service: str) -> list[Mapping[str, Any]]:
        rows: list[Mapping[str, Any]] = []
        cursor: str | None = None
        for _page in range(10):
            url = self._render_env_inventory_url(service) + "?limit=100"
            if cursor:
                url += "&cursor=" + urllib.parse.quote(cursor, safe="")
            result = self._http_json(url, self.render_token)
            if not isinstance(result, list) or len(result) > 100:
                raise DevReleaseBlocked("render_document_flag_inventory_invalid")
            if not result:
                return rows
            for row in result:
                if (not isinstance(row, Mapping) or not isinstance(row.get("envVar"), Mapping)
                        or not isinstance(row["envVar"].get("key"), str)
                        or not row["envVar"]["key"]
                        or not isinstance(row["envVar"].get("value"), str)
                        or not isinstance(row.get("cursor"), str) or not row["cursor"]):
                    raise DevReleaseBlocked("render_document_flag_inventory_invalid")
                rows.append(row)
            next_cursor = result[-1]["cursor"]
            if next_cursor == cursor:
                raise DevReleaseBlocked("render_document_flag_inventory_incomplete")
            cursor = next_cursor
        raise DevReleaseBlocked("render_document_flag_inventory_incomplete")

    def document_draft_flags(self, packet: Mapping[str, Any]) -> Mapping[str, bool]:
        cfg = _require_mapping(packet, "render")
        return {
            "api": self._render_document_value(packet, str(cfg["api_service_id"])),
            "worker": self._render_document_value(packet, str(cfg["worker_service_id"])),
            "frontend": self._vercel_document_value(packet),
        }

    def _vercel_document_value(self, packet: Mapping[str, Any]) -> bool:
        return self._vercel_feature_value(packet, WEB_DOCUMENT_DRAFT_KEY, "document")

    def _vercel_feature_value(self, packet: Mapping[str, Any], key: str, label: str) -> bool:
        result = self._http_json(self._vercel_flag_url(packet), self.vercel_token)
        rows = result.get("envs") if isinstance(result, Mapping) else None
        if not isinstance(rows, list) or len(rows) > 512:
            raise DevReleaseBlocked(f"vercel_{label}_flag_inventory_invalid")
        if any(not isinstance(row, Mapping) or not isinstance(row.get("key"), str)
               or not isinstance(row.get("target"), list)
               or any(not isinstance(target, str) for target in row["target"])
               for row in rows):
            raise DevReleaseBlocked(f"vercel_{label}_flag_inventory_invalid")
        matches = [
            row for row in rows
            if isinstance(row, Mapping)
            and row.get("key") == key
            and "production" in row.get("target", [])
        ]
        if len(matches) > 1:
            raise DevReleaseBlocked(f"vercel_{label}_flag_duplicate")
        if not matches:
            return False
        if matches[0].get("target") != ["production"] or matches[0].get("type") != "plain":
            raise DevReleaseBlocked(f"vercel_{label}_flag_scope_ambiguous")
        return _literal_flag(matches[0].get("value"), reason=f"{label}_flag_not_literal")

    def set_document_draft_flags(self, packet: Mapping[str, Any], enabled: bool) -> list[str]:
        if type(enabled) is not bool:
            raise DevReleaseBlocked("document_draft_enabled_invalid")
        before = self.document_draft_flags(packet)
        literal = "true" if enabled else "false"
        cfg = _require_mapping(packet, "render")
        changed = []
        for label, field in (("api", "api_service_id"), ("worker", "worker_service_id")):
            if before[label] is enabled:
                continue
            url = self._render_flag_url(str(cfg[field])).replace(API_WORKBENCH_KEY, API_DOCUMENT_DRAFT_KEY)
            self._http_json(url, self.render_token, method="PUT", body={"value": literal})
            if self._render_document_value(packet, str(cfg[field])) is not enabled:
                raise DevReleaseBlocked(f"{label}_document_flag_readback_mismatch")
            changed.append(label)
        if before["frontend"] is not enabled:
            self._http_json(
                self._vercel_flag_url(packet) + "&upsert=true", self.vercel_token,
                method="POST", body={"key": WEB_DOCUMENT_DRAFT_KEY, "value": literal, "type": "plain", "target": ["production"]},
            )
            if self._vercel_document_value(packet) is not enabled:
                raise DevReleaseBlocked("frontend_document_flag_readback_mismatch")
            changed.append("frontend")
        return changed

    def correction_flags(self, packet: Mapping[str, Any]) -> Mapping[str, bool]:
        cfg = _require_mapping(packet, "render")
        return {
            "api": self._render_feature_value(str(cfg["api_service_id"]), API_CORRECTION_KEY, "correction"),
            "worker": self._render_feature_value(str(cfg["worker_service_id"]), API_CORRECTION_KEY, "correction"),
            "frontend": self._vercel_feature_value(packet, WEB_CORRECTION_KEY, "correction"),
        }

    def set_correction_flags(self, packet: Mapping[str, Any], enabled: bool) -> list[str]:
        if type(enabled) is not bool:
            raise DevReleaseBlocked("lesson_correction_enabled_invalid")
        before = self.correction_flags(packet)
        literal = "true" if enabled else "false"
        cfg = _require_mapping(packet, "render")
        changed = []
        for label, field in (("api", "api_service_id"), ("worker", "worker_service_id")):
            if before[label] is enabled:
                continue
            url = self._render_flag_url(str(cfg[field])).replace(API_WORKBENCH_KEY, API_CORRECTION_KEY)
            self._http_json(url, self.render_token, method="PUT", body={"value": literal})
            if self._render_feature_value(str(cfg[field]), API_CORRECTION_KEY, "correction") is not enabled:
                raise DevReleaseBlocked(f"{label}_correction_flag_readback_mismatch")
            changed.append(label)
        if before["frontend"] is not enabled:
            self._http_json(
                self._vercel_flag_url(packet) + "&upsert=true", self.vercel_token,
                method="POST", body={"key": WEB_CORRECTION_KEY, "value": literal, "type": "plain", "target": ["production"]},
            )
            if self._vercel_feature_value(packet, WEB_CORRECTION_KEY, "correction") is not enabled:
                raise DevReleaseBlocked("frontend_correction_flag_readback_mismatch")
            changed.append("frontend")
        return changed

    def render_service(self, service_id: str) -> Mapping[str, Any]:
        result = self._http_json(
            f"https://api.render.com/v1/services/{urllib.parse.quote(service_id)}",
            self.render_token,
        )
        details = result.get("serviceDetails") or {}
        return {
            "plan": details.get("plan"),
            "branch": result.get("branch"),
            "auto_deploy": result.get("autoDeploy"),
        }

    def trigger_render(self, service_id: str, release_sha: str) -> str:
        result = self._http_json(
            f"https://api.render.com/v1/services/{urllib.parse.quote(service_id)}/deploys",
            self.render_token,
            method="POST",
            body={
                "commitId": release_sha,
                "clearCache": "do_not_clear",
                "deployMode": "build_and_deploy",
            },
        )
        deployment_id = result.get("id")
        if not deployment_id:
            raise DevReleaseBlocked("render_deployment_id_missing")
        return str(deployment_id)

    def find_render(
        self, service_id: str, release_sha: str
    ) -> Mapping[str, Any] | None:
        for deploy in self._render_deploys(service_id):
            commit = deploy.get("commit") or {}
            if commit.get("id") == release_sha:
                return {
                    "status": deploy.get("status"),
                    "deployment_id": deploy.get("id"),
                    "release_sha": release_sha,
                }
        return None

    def _render_deploys(self, service_id: str) -> list[Mapping[str, Any]]:
        result = self._http_json(
            f"https://api.render.com/v1/services/{urllib.parse.quote(service_id)}/deploys?limit=20",
            self.render_token,
        )
        if not isinstance(result, list):
            raise DevReleaseBlocked("render_deploy_list_invalid")
        deploys: list[Mapping[str, Any]] = []
        for item in result:
            if not isinstance(item, Mapping):
                continue
            deploy = item.get("deploy")
            if isinstance(deploy, Mapping):
                deploys.append(deploy)
            elif "id" in item:
                deploys.append(item)
        return deploys

    def wait_render(
        self, service_id: str, deployment_id: str, release_sha: str
    ) -> Mapping[str, Any]:
        def probe() -> Mapping[str, Any]:
            matches = []
            for deploy in self._render_deploys(service_id):
                commit = deploy.get("commit") or {}
                if commit.get("id") != release_sha:
                    continue
                if deployment_id and deploy.get("id") != deployment_id:
                    continue
                matches.append(deploy)
            if not matches:
                return {
                    "status": "waiting",
                    "deployment_id": deployment_id or None,
                    "release_sha": release_sha,
                }
            deploy = matches[0]
            return {
                "status": deploy.get("status"),
                "deployment_id": deploy.get("id"),
                "release_sha": release_sha,
            }

        return self._wait(
            probe,
            lambda item: item.get("status")
            in {"live", "build_failed", "update_failed", "canceled", "deactivated"},
            "render_deployment_timeout",
        )

    def read_health(self, url: str) -> Any:
        last_error: Exception | None = None
        for _attempt in range(3):
            request = urllib.request.Request(
                url, headers={"User-Agent": "Kamilya-DEV-Release-Controller/1"}
            )
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    status = response.status
                    raw = response.read()
                    content_type = response.headers.get("Content-Type", "")
                break
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                time.sleep(self.poll_seconds)
        else:
            raise DevReleaseBlocked("public_health_request_failed") from last_error
        if "application/json" in content_type:
            try:
                return json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise DevReleaseBlocked("public_health_json_invalid") from exc
        text = raw.decode("utf-8", errors="replace").strip()
        if text == "ok":
            return "ok"
        return {"http_status": status}


def _require_string(data: Mapping[str, Any], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value:
        raise DevReleaseBlocked(f"packet_{name}_invalid")
    return value


def _require_mapping(data: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = data.get(name)
    if not isinstance(value, Mapping):
        raise DevReleaseBlocked(f"packet_{name}_invalid")
    return value


def _literal_flag(value: Any, *, reason: str = "provider_workbench_flag_not_literal") -> bool:
    if value not in ("true", "false"):
        raise DevReleaseBlocked(reason)
    return value == "true"


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def validate_activation_packet(data: Mapping[str, Any]) -> dict[str, Any]:
    if data.get("schema") not in ACTIVATION_REVISIONS:
        raise DevReleaseBlocked("activation_packet_v2_schema_required")
    return validate_packet(data)


def validate_packet(data: Mapping[str, Any]) -> dict[str, Any]:
    schema = data.get("schema")
    if schema not in (PACKET_SCHEMA, *ACTIVATION_REVISIONS):
        raise DevReleaseBlocked("release_packet_schema_invalid")
    expected = {"schema", "release_id", "release_sha", "expected_previous_sha", "repository", "branch", "migration_scope", "github", "vercel", "render"}
    if schema in ACTIVATION_REVISIONS:
        expected.update({"workbench_enabled", "configuration_ci_run_id", "schema_evidence"})
    if schema in {DOCUMENT_ACTIVATION_SCHEMA, CORRECTION_ACTIVATION_SCHEMA}:
        expected.add("document_draft_enabled")
    if schema == CORRECTION_ACTIVATION_SCHEMA:
        expected.add("lesson_correction_enabled")
    if set(data) != expected:
        raise DevReleaseBlocked("release_packet_unknown_or_missing_fields")
    if data.get("repository") != "KamillaLMSCRM/Kamilya-NEW":
        raise DevReleaseBlocked("repository_scope_invalid")
    if schema in ACTIVATION_REVISIONS:
        if type(data.get("workbench_enabled")) is not bool:
            raise DevReleaseBlocked("packet_workbench_enabled_invalid")
        if schema in {DOCUMENT_ACTIVATION_SCHEMA, CORRECTION_ACTIVATION_SCHEMA}:
            if type(data.get("document_draft_enabled")) is not bool:
                raise DevReleaseBlocked("packet_document_draft_enabled_invalid")
            if data["document_draft_enabled"] and not data["workbench_enabled"]:
                raise DevReleaseBlocked("document_draft_requires_workbench_enabled")
        if schema == CORRECTION_ACTIVATION_SCHEMA:
            if type(data.get("lesson_correction_enabled")) is not bool:
                raise DevReleaseBlocked("packet_lesson_correction_enabled_invalid")
            if data["lesson_correction_enabled"] and not data["workbench_enabled"]:
                raise DevReleaseBlocked("lesson_correction_requires_workbench_enabled")
        if type(data.get("configuration_ci_run_id")) is not int or data["configuration_ci_run_id"] <= 0:
            raise DevReleaseBlocked("configuration_ci_run_id_invalid")
        evidence = _require_mapping(data, "schema_evidence")
        if set(evidence) != {"path", "sha256"}:
            raise DevReleaseBlocked("schema_evidence_fields_invalid")
        _require_string(evidence, "path")
        digest = _require_string(evidence, "sha256")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise DevReleaseBlocked("schema_evidence_digest_invalid")

    release_id = _require_string(data, "release_id")
    release_sha = _require_string(data, "release_sha")
    previous_sha = _require_string(data, "expected_previous_sha")
    if not RELEASE_ID_RE.fullmatch(release_id):
        raise DevReleaseBlocked("release_id_invalid")
    if not SHA_RE.fullmatch(release_sha):
        raise DevReleaseBlocked("release_sha_invalid")
    if not SHA_RE.fullmatch(previous_sha):
        raise DevReleaseBlocked("expected_previous_sha_invalid")
    if release_sha == previous_sha:
        raise DevReleaseBlocked("release_sha_not_new")
    if data.get("migration_scope") != "none":
        raise DevReleaseBlocked("schema_gate_required")
    if data.get("branch") != "dev":
        raise DevReleaseBlocked("dev_branch_required")

    github = _require_mapping(data, "github")
    vercel = _require_mapping(data, "vercel")
    render = _require_mapping(data, "render")
    if schema in ACTIVATION_REVISIONS and (vercel.get("expected_plan") != "hobby" or render.get("expected_plan") != "free"):
        raise DevReleaseBlocked("activation_free_plan_required")
    for name in ("workflow",):
        _require_string(github, name)
    for name in (
        "project_id",
        "project_name",
        "team_id",
        "expected_plan",
        "public_url",
    ):
        _require_string(vercel, name)
    for name in (
        "api_service_id",
        "worker_service_id",
        "expected_plan",
        "api_auto_deploy",
        "worker_auto_deploy",
        "api_health_url",
        "worker_health_url",
    ):
        _require_string(render, name)

    # Round-trip through JSON to detach the validated packet from caller state.
    return json.loads(json.dumps(data))


def load_packet(path: Path, expected_sha256: str) -> dict[str, Any]:
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha256:
        raise DevReleaseBlocked("release_packet_digest_mismatch")
    try:
        decoded = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, ValueError) as exc:
        raise DevReleaseBlocked("release_packet_json_invalid") from exc
    if not isinstance(decoded, Mapping):
        raise DevReleaseBlocked("release_packet_root_invalid")
    return validate_packet(decoded)


@dataclass(frozen=True)
class DevReleaseController:
    packet: Mapping[str, Any]
    providers: ProviderAdapter

    def __post_init__(self) -> None:
        object.__setattr__(self, "packet", validate_packet(self.packet))

    def _schema_gate(self) -> None:
        if self.packet["schema"] not in ACTIVATION_REVISIONS:
            return
        expected_revision = ACTIVATION_REVISIONS[self.packet["schema"]]
        evidence = self.packet["schema_evidence"]
        root = self.providers.repo_root.resolve()
        original = Path(evidence["path"])
        if not original.is_absolute():
            original = root / original
        path = original.resolve()
        if (original.is_symlink() or not path.is_relative_to(root / ".release-evidence")
                or not path.is_file()):
            raise DevReleaseBlocked("schema_evidence_not_canonical_regular_file")
        if path.stat().st_size > 4096:
            raise DevReleaseBlocked("schema_evidence_size_not_bounded")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != evidence["sha256"]:
            raise DevReleaseBlocked("schema_evidence_digest_mismatch")
        try:
            result = json.loads(raw, object_pairs_hook=_unique_object)
        except (UnicodeError, ValueError) as exc:
            raise DevReleaseBlocked("schema_evidence_json_invalid") from exc
        if (not isinstance(result, Mapping) or result.get("status") != "PASS"
                or result.get("target") != "canonical_supabase_dev_public_schema"
                or result.get("current_revision") != expected_revision or result.get("expected_revision") != expected_revision
                or result.get("project_ref_sha256") != DEV_PROJECT_REF_SHA256):
            raise DevReleaseBlocked(f"schema_evidence_{expected_revision}_pass_required")

    def _flags(self) -> dict[str, bool]:
        flags = dict(self.providers.workbench_flags(self.packet))
        if set(flags) != {"api", "worker", "frontend"} or any(type(value) is not bool for value in flags.values()):
            raise DevReleaseBlocked("provider_workbench_flag_shape_invalid")
        return flags

    def _document_flags(self) -> dict[str, bool]:
        flags = dict(self.providers.document_draft_flags(self.packet))
        if set(flags) != {"api", "worker", "frontend"} or any(
            type(value) is not bool for value in flags.values()
        ):
            raise DevReleaseBlocked("provider_document_flag_shape_invalid")
        return flags

    def _correction_flags(self) -> dict[str, bool]:
        flags = dict(self.providers.correction_flags(self.packet))
        if set(flags) != {"api", "worker", "frontend"} or any(
            type(value) is not bool for value in flags.values()
        ):
            raise DevReleaseBlocked("provider_correction_flag_shape_invalid")
        return flags

    def _configuration(self) -> dict[str, Any]:
        if self.packet["schema"] not in ACTIVATION_REVISIONS:
            return {}
        flags = self._flags()
        if any(value is not self.packet["workbench_enabled"] for value in flags.values()):
            raise DevReleaseBlocked("provider_workbench_flag_mismatch_prepare_required")
        result = {
            "requested_workbench_enabled": self.packet["workbench_enabled"],
            "observed_flags": flags, "evidence_source": "provider_configuration_not_runtime",
        }
        if self.packet["schema"] in {DOCUMENT_ACTIVATION_SCHEMA, CORRECTION_ACTIVATION_SCHEMA}:
            document_flags = self._document_flags()
            if any(value is not self.packet["document_draft_enabled"] for value in document_flags.values()):
                raise DevReleaseBlocked("provider_document_flag_mismatch_prepare_required")
            result.update({
                "requested_document_draft_enabled": self.packet["document_draft_enabled"],
                "observed_document_flags": document_flags,
            })
        if self.packet["schema"] == CORRECTION_ACTIVATION_SCHEMA:
            correction_flags = self._correction_flags()
            if any(value is not self.packet["lesson_correction_enabled"] for value in correction_flags.values()):
                raise DevReleaseBlocked("provider_correction_flag_mismatch_prepare_required")
            result.update({
                "requested_lesson_correction_enabled": self.packet["lesson_correction_enabled"],
                "observed_correction_flags": correction_flags,
            })
        return result

    def prepare(self, confirm_release_id: str) -> dict[str, Any]:
        if self.packet["schema"] not in ACTIVATION_REVISIONS:
            raise DevReleaseBlocked("prepare_requires_activation_v2")
        if confirm_release_id != self.packet["release_id"]:
            raise DevReleaseBlocked("execute_confirmation_mismatch")
        self._schema_gate()
        repository, sha = self.packet["repository"], self.packet["release_sha"]
        ci = self.providers.verify_source_ci(self.packet["configuration_ci_run_id"], sha, repository)
        if ci.get("branch") != "master" or ci.get("event") != "push":
            raise DevReleaseBlocked("configuration_source_master_branch_required")
        if (ci.get("status") != "completed" or ci.get("conclusion") != "success"
                or ci.get("release_sha") != sha or ci.get("run_id") != self.packet["configuration_ci_run_id"]):
            raise DevReleaseBlocked("configuration_source_ci_not_successful")
        if self.providers.remote_branch_sha(repository, "master") != sha:
            raise DevReleaseBlocked("configuration_source_master_sha_mismatch")
        if self.providers.remote_branch_sha(repository, "dev") != self.packet["expected_previous_sha"]:
            raise DevReleaseBlocked("configuration_dev_previous_sha_mismatch")
        self._verify_provider_contract()
        document_before = self._document_flags() if self.packet["schema"] in {DOCUMENT_ACTIVATION_SCHEMA, CORRECTION_ACTIVATION_SCHEMA} else {}
        correction_before = self._correction_flags() if self.packet["schema"] == CORRECTION_ACTIVATION_SCHEMA else {}
        before = self._flags()
        enabled = self.packet["workbench_enabled"]
        changed = self.providers.set_workbench_flags(self.packet, enabled) if any(value is not enabled for value in before.values()) else []
        document_changed: list[str] = []
        if self.packet["schema"] in {DOCUMENT_ACTIVATION_SCHEMA, CORRECTION_ACTIVATION_SCHEMA}:
            document_enabled = self.packet["document_draft_enabled"]
            if any(value is not document_enabled for value in document_before.values()):
                document_changed = self.providers.set_document_draft_flags(self.packet, document_enabled)
        correction_changed: list[str] = []
        if self.packet["schema"] == CORRECTION_ACTIVATION_SCHEMA:
            correction_enabled = self.packet["lesson_correction_enabled"]
            if any(value is not correction_enabled for value in correction_before.values()):
                correction_changed = self.providers.set_correction_flags(self.packet, correction_enabled)
        configuration = self._configuration()
        return self._bounded({
            "status": "CONFIGURATION_READY", "release_id": self.packet["release_id"],
            "release_sha": sha, "before_flags": before, "changed_labels": changed,
            **({"before_document_flags": document_before, "document_changed_labels": document_changed} if document_before else {}),
            **({"before_correction_flags": correction_before, "correction_changed_labels": correction_changed} if correction_before else {}),
            "configuration": configuration, "schema_evidence_sha256": self.packet["schema_evidence"]["sha256"],
            "product_go": "NOT_VERIFIED_UNTIL_EXACT_DEPLOY_AND_LIVE_TEST", "billing_changed": False,
        })

    def execute(self, confirm_release_id: str) -> dict[str, Any]:
        release_id = str(self.packet["release_id"])
        if confirm_release_id != release_id:
            raise DevReleaseBlocked("execute_confirmation_mismatch")
        self._schema_gate()

        repository = str(self.packet["repository"])
        branch = str(self.packet["branch"])
        release_sha = str(self.packet["release_sha"])
        expected_previous = str(self.packet["expected_previous_sha"])
        current = self.providers.remote_branch_sha(repository, branch)
        if current not in {expected_previous, release_sha}:
            raise DevReleaseBlocked("expected_previous_sha_mismatch")

        self._verify_provider_contract()
        self._configuration()
        if current == expected_previous:
            self.providers.push_exact_sha(repository, branch, release_sha)
            if self.providers.remote_branch_sha(repository, branch) != release_sha:
                raise DevReleaseBlocked("remote_branch_readback_mismatch")

        github_ci = self._github_ci()
        vercel = self._vercel()
        render = self._deploy_render()
        health = self._health()
        configuration = self._configuration()
        return self._bounded(
            {
                "status": "RELEASE_OK",
                "release_id": release_id,
                "release_sha": release_sha,
                "previous_release_sha": expected_previous,
                "migration_scope": "none",
                "github_ci": github_ci,
                "vercel": vercel,
                "render": render,
                "health": health,
                **({"configuration": configuration, "product_go": "NOT_VERIFIED_UNTIL_EXACT_DEPLOY_AND_LIVE_TEST"} if configuration else {}),
            }
        )

    def reconcile(self) -> dict[str, Any]:
        self._schema_gate()
        repository = str(self.packet["repository"])
        branch = str(self.packet["branch"])
        release_sha = str(self.packet["release_sha"])
        if self.providers.remote_branch_sha(repository, branch) != release_sha:
            raise DevReleaseBlocked("remote_branch_readback_mismatch")

        self._verify_provider_contract()
        self._configuration()
        github_ci = self._github_ci()
        vercel = self._vercel()
        render_cfg = _require_mapping(self.packet, "render")
        api_service = str(render_cfg["api_service_id"])
        worker_service = str(render_cfg["worker_service_id"])
        render = {
            "api": self._validate_render_deploy(
                self.providers.wait_render(api_service, "", release_sha)
            ),
            "worker": self._validate_render_deploy(
                self.providers.wait_render(worker_service, "", release_sha)
            ),
        }
        health = self._health()
        configuration = self._configuration()
        return self._bounded(
            {
                "status": "RECONCILED",
                "release_id": self.packet["release_id"],
                "release_sha": release_sha,
                "migration_scope": "none",
                "github_ci": github_ci,
                "vercel": vercel,
                "render": render,
                "health": health,
                **({"configuration": configuration, "product_go": "NOT_VERIFIED_UNTIL_EXACT_DEPLOY_AND_LIVE_TEST"} if configuration else {}),
            }
        )

    def _github_ci(self) -> dict[str, Any]:
        result = dict(
            self.providers.wait_github_ci(
                str(self.packet["repository"]),
                str(_require_mapping(self.packet, "github")["workflow"]),
                str(self.packet["release_sha"]),
            )
        )
        if result.get("status") != "completed" or result.get("conclusion") != "success":
            raise DevReleaseBlocked("github_ci_not_successful")
        return {
            "status": "completed",
            "conclusion": "success",
            "run_id": result.get("run_id"),
        }

    def _vercel(self) -> dict[str, Any]:
        cfg = _require_mapping(self.packet, "vercel")
        result = dict(
            self.providers.wait_vercel(
                str(cfg["project_id"]),
                str(cfg["team_id"]),
                str(self.packet["release_sha"]),
            )
        )
        if result.get("status") != "READY":
            raise DevReleaseBlocked("vercel_deployment_not_ready")
        if result.get("release_sha") != self.packet["release_sha"]:
            raise DevReleaseBlocked("vercel_release_sha_mismatch")
        if result.get("plan") != cfg["expected_plan"]:
            raise DevReleaseBlocked("vercel_plan_mismatch")
        return {
            "status": "READY",
            "deployment_id": result.get("deployment_id"),
            "release_sha": result.get("release_sha"),
            "plan": result.get("plan"),
        }

    def _verify_provider_contract(self) -> None:
        vercel = _require_mapping(self.packet, "vercel")
        project = self.providers.vercel_project(
            str(vercel["project_id"]), str(vercel["team_id"])
        )
        if project.get("project_id") != vercel["project_id"]:
            raise DevReleaseBlocked("vercel_project_id_mismatch")
        if project.get("project_name") != vercel["project_name"]:
            raise DevReleaseBlocked("vercel_project_name_mismatch")
        if project.get("branch") != self.packet["branch"]:
            raise DevReleaseBlocked("vercel_branch_mismatch")
        if project.get("plan") != vercel["expected_plan"]:
            raise DevReleaseBlocked("vercel_plan_mismatch")

        cfg = _require_mapping(self.packet, "render")
        expected_plan = cfg["expected_plan"]
        for key, auto_deploy_key in (
            ("api_service_id", "api_auto_deploy"),
            ("worker_service_id", "worker_auto_deploy"),
        ):
            service = self.providers.render_service(str(cfg[key]))
            if service.get("plan") != expected_plan:
                raise DevReleaseBlocked("render_plan_mismatch")
            if service.get("branch") != self.packet["branch"]:
                raise DevReleaseBlocked("render_branch_mismatch")
            if service.get("auto_deploy") != cfg[auto_deploy_key]:
                raise DevReleaseBlocked("render_auto_deploy_mismatch")

    def _deploy_render(self) -> dict[str, Any]:
        cfg = _require_mapping(self.packet, "render")
        release_sha = str(self.packet["release_sha"])
        result: dict[str, Any] = {}
        for label, key in (
            ("api", "api_service_id"),
            ("worker", "worker_service_id"),
        ):
            service_id = str(cfg[key])
            existing = self.providers.find_render(service_id, release_sha)
            failed = {
                "build_failed",
                "update_failed",
                "canceled",
                "deactivated",
            }
            if (
                existing
                and existing.get("deployment_id")
                and existing.get("status") not in failed
            ):
                deployment_id = str(existing["deployment_id"])
            else:
                deployment_id = self.providers.trigger_render(service_id, release_sha)
            result[label] = self._validate_render_deploy(
                self.providers.wait_render(service_id, deployment_id, release_sha)
            )
        return result

    def _validate_render_deploy(self, value: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(value)
        if result.get("status") != "live":
            raise DevReleaseBlocked("render_deployment_not_live")
        if result.get("release_sha") != self.packet["release_sha"]:
            raise DevReleaseBlocked("render_release_sha_mismatch")
        return {
            "status": "live",
            "deployment_id": result.get("deployment_id"),
            "release_sha": result.get("release_sha"),
        }

    def _health(self) -> dict[str, Any]:
        render = _require_mapping(self.packet, "render")
        vercel = _require_mapping(self.packet, "vercel")
        api = self._read_health("api", str(render["api_health_url"]))
        worker = self._read_health("worker", str(render["worker_health_url"]))
        frontend = self._read_health("frontend", str(vercel["public_url"]))
        if not isinstance(api, Mapping) or api.get("status") != "ok":
            raise DevReleaseBlocked("api_health_not_ok")
        if api.get("deployment_environment") != "render-development":
            raise DevReleaseBlocked("api_environment_mismatch")
        if api.get("release_sha") != self.packet["release_sha"]:
            raise DevReleaseBlocked("api_release_sha_mismatch")
        if worker != "ok":
            raise DevReleaseBlocked("worker_health_not_ok")
        if not isinstance(frontend, Mapping) or frontend.get("http_status") != 200:
            raise DevReleaseBlocked("frontend_health_not_ok")
        return {"api": dict(api), "worker": worker, "frontend": dict(frontend)}

    def _read_health(self, label: str, url: str) -> Any:
        try:
            return self.providers.read_health(url)
        except DevReleaseBlocked as exc:
            raise DevReleaseBlocked(f"{label}_health_request_failed") from exc

    @staticmethod
    def _bounded(result: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(result, sort_keys=True)) >= 4096:
            raise DevReleaseBlocked("evidence_output_too_large")
        return result


def _evidence_path(evidence_root: Path, packet: Mapping[str, Any], mode: str) -> Path:
    return evidence_root / "dev" / str(packet["release_id"]) / f"{mode}.json"


def _write_evidence(
    evidence_root: Path,
    repo_root: Path,
    packet: Mapping[str, Any],
    mode: str,
    result: Mapping[str, Any],
) -> Path:
    canonical = (repo_root.resolve() / ".release-evidence").resolve()
    if evidence_root.resolve() != canonical:
        raise DevReleaseBlocked("evidence_root_not_canonical")
    path = _evidence_path(canonical, packet, mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("reconcile", "execute", "prepare"))
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--packet-sha256", required=True)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--confirm-release-id", default="")
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        packet = load_packet(args.packet, args.packet_sha256)
        adapter = LiveProviderAdapter(
            repo_root=args.repo_root,
            env_file=args.env_file,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
        )
        release = DevReleaseController(packet, adapter)
        if args.command == "prepare":
            result = release.prepare(args.confirm_release_id)
        elif args.command == "reconcile":
            result = release.reconcile()
        else:
            result = release.execute(args.confirm_release_id)
        evidence = _write_evidence(
            args.evidence_root, args.repo_root, packet, args.command, result
        )
        output = dict(result)
        output["evidence"] = str(evidence)
        print(
            json.dumps(
                output, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        )
        return 0
    except DevReleaseBlocked as exc:
        error = {"status": "BLOCKED", "reason": str(exc)}
        print(
            json.dumps(
                error, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
            file=sys.stderr,
        )
        return 1
    except Exception:
        error = {"status": "BLOCKED", "reason": "unexpected_controller_failure"}
        print(
            json.dumps(
                error, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
