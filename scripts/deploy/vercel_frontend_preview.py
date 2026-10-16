#!/usr/bin/env python3
"""Deploy one exact Kamilya web commit as an isolated Vercel preview.

This controller never moves a Git branch, changes a Vercel project setting or
alias, or starts a Render deployment.  Mutating execution is deliberately split
into a single POST (``create``) and read-only ``wait``/``reconcile`` commands so
an uncertain POST outcome is never retried blindly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Mapping, Protocol
import urllib.error
import urllib.parse
import urllib.request


SCHEMA = "kamilya-vercel-frontend-preview-v1"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DEPLOYMENT_RE = re.compile(r"^dpl_[A-Za-z0-9]+$")
RENDER_DEPLOYMENT_RE = re.compile(r"^dep-[A-Za-z0-9]+$")
TERMINAL_STATES = {"READY", "ERROR", "CANCELED"}
IN_PROGRESS_STATES = {"QUEUED", "INITIALIZING", "BUILDING"}


class PreviewBlocked(RuntimeError):
    """Fail-closed packet, provider, or release invariant."""


class ProviderRequestUnknown(PreviewBlocked):
    """The create request may have reached Vercel, but no response was received."""


class Providers(Protocol):
    def remote_branch_sha(self, repository: str, branch: str) -> str: ...

    def github_ci(self, repository: str, run_id: int) -> Mapping[str, Any]: ...

    def source_api_guard(self, release_sha: str) -> bool: ...

    def vercel_project(self, project_id: str, team_id: str) -> Mapping[str, Any]: ...

    def preview_api_url(self, project_id: str, team_id: str) -> str: ...

    def deployment(self, deployment_id_or_url: str, team_id: str) -> Mapping[str, Any]: ...

    def render_deployment(self, service_id: str) -> Mapping[str, Any]: ...

    def create_preview(self, packet: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def find_previews(self, packet: Mapping[str, Any]) -> list[Mapping[str, Any]]: ...


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PreviewBlocked(f"{name}_invalid")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise PreviewBlocked(f"{name}_invalid")
    return value


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise PreviewBlocked("env_file_missing")
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def _secret(values: Mapping[str, str], *names: str) -> str:
    for name in names:
        value = values.get(name)
        if value:
            return value
    raise PreviewBlocked(f"secret_missing_{names[0]}")


def packet_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_packet(path: Path, expected_sha256: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise PreviewBlocked("packet_sha256_invalid")
    if packet_digest(path) != expected_sha256:
        raise PreviewBlocked("packet_digest_mismatch")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreviewBlocked("packet_json_invalid") from exc
    packet = dict(_mapping(data, "packet"))
    _validate_packet(packet)
    return packet


def _validate_packet(packet: Mapping[str, Any]) -> None:
    if set(packet) != {
        "schema",
        "release_id",
        "release_sha",
        "repository",
        "github",
        "vercel",
        "baseline",
    }:
        raise PreviewBlocked("packet_unknown_or_missing_fields")
    if packet.get("schema") != SCHEMA:
        raise PreviewBlocked("packet_schema_invalid")
    _string(packet.get("release_id"), "release_id")
    release_sha = _string(packet.get("release_sha"), "release_sha")
    if not SHA_RE.fullmatch(release_sha):
        raise PreviewBlocked("release_sha_invalid")
    if packet.get("repository") != "KamillaLMSCRM/Kamilya-NEW":
        raise PreviewBlocked("repository_scope_invalid")

    github = _mapping(packet.get("github"), "github")
    if set(github) != {"run_id", "workflow", "event"}:
        raise PreviewBlocked("github_fields_invalid")
    if type(github.get("run_id")) is not int or int(github["run_id"]) <= 0:
        raise PreviewBlocked("github_run_id_invalid")
    _string(github.get("workflow"), "github_workflow")
    if github.get("event") not in {"push", "workflow_dispatch"}:
        raise PreviewBlocked("github_event_invalid")

    vercel = _mapping(packet.get("vercel"), "vercel")
    if set(vercel) != {
        "team_id",
        "team_slug",
        "project_id",
        "project_name",
        "github_repo_id",
        "production_branch",
        "root_directory",
        "expected_plan",
        "stable_alias",
        "preview_api_url",
    }:
        raise PreviewBlocked("vercel_fields_invalid")
    for name in vercel:
        _string(vercel.get(name), f"vercel_{name}")
    if vercel["project_name"] != "kamilya-lms-dev":
        raise PreviewBlocked("vercel_project_scope_invalid")
    if vercel["production_branch"] != "dev":
        raise PreviewBlocked("vercel_production_branch_invalid")
    if vercel["root_directory"] != "apps/web":
        raise PreviewBlocked("vercel_root_directory_invalid")
    if vercel["expected_plan"] != "hobby":
        raise PreviewBlocked("vercel_hobby_required")
    if vercel["stable_alias"] != "kamilya-lms-dev.vercel.app":
        raise PreviewBlocked("vercel_alias_scope_invalid")
    if vercel["preview_api_url"] != "https://kamilya-lms-api.onrender.com/api":
        raise PreviewBlocked("preview_api_url_invalid")

    baseline = _mapping(packet.get("baseline"), "baseline")
    if set(baseline) != {
        "origin_dev_sha",
        "stable_alias_deployment_id",
        "render_api_service_id",
        "render_api_deployment_id",
        "render_worker_service_id",
        "render_worker_deployment_id",
    }:
        raise PreviewBlocked("baseline_fields_invalid")
    for name in baseline:
        value = _string(baseline.get(name), f"baseline_{name}")
        if name == "origin_dev_sha" and not SHA_RE.fullmatch(value):
            raise PreviewBlocked("baseline_origin_dev_sha_invalid")
        if name == "stable_alias_deployment_id" and not DEPLOYMENT_RE.fullmatch(value):
            raise PreviewBlocked(f"baseline_{name}_invalid")
        if name.startswith("render_") and name.endswith("deployment_id"):
            if not RENDER_DEPLOYMENT_RE.fullmatch(value):
                raise PreviewBlocked(f"baseline_{name}_invalid")


def _state_path(path: Path, repo_root: Path) -> Path:
    resolved = path.resolve()
    evidence = (repo_root.resolve() / ".release-evidence").resolve()
    try:
        resolved.relative_to(evidence)
    except ValueError as exc:
        raise PreviewBlocked("state_file_not_under_release_evidence") from exc
    return resolved


def _write_state(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _read_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise PreviewBlocked("state_file_missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreviewBlocked("state_file_invalid") from exc
    return dict(_mapping(value, "state"))


class LiveProviders:
    """Secret-safe adapters for GitHub, Vercel and read-only Render identity."""

    def __init__(self, repo_root: Path, env_file: Path, timeout_seconds: int) -> None:
        values = _read_env_file(env_file)
        self.vercel_token = _secret(values, "vercel_token", "VERCEL_TOKEN")
        self.render_token = _secret(values, "RENDER_API_KEY")
        self.repo_root = repo_root.resolve()
        self.request_timeout_seconds = min(timeout_seconds, 30)
        self.github_helper = self.repo_root / "scripts/ops/with_project_github_token.py"
        if not self.github_helper.is_file():
            raise PreviewBlocked("canonical_github_helper_missing")

    def _http_json(
        self,
        url: str,
        token: str,
        *,
        method: str = "GET",
        body: Mapping[str, Any] | None = None,
        create: bool = False,
    ) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "kamilya-vercel-frontend-preview/1",
            },
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.request_timeout_seconds
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # A 4xx is a known rejection. A 5xx may follow a committed create.
            if create and exc.code >= 500:
                raise ProviderRequestUnknown("vercel_create_outcome_unknown") from exc
            raise PreviewBlocked(f"provider_http_{exc.code}") from exc
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            if create:
                raise ProviderRequestUnknown("vercel_create_outcome_unknown") from exc
            raise PreviewBlocked("provider_request_failed") from exc
        except json.JSONDecodeError as exc:
            if create:
                raise ProviderRequestUnknown("vercel_create_response_invalid") from exc
            raise PreviewBlocked("provider_response_invalid") from exc

    def _gh(self, endpoint: str) -> Mapping[str, Any]:
        completed = subprocess.run(
            [
                sys.executable,
                str(self.github_helper),
                "--repo",
                str(self.repo_root),
                "--",
                "gh",
                "api",
                endpoint,
            ],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if completed.returncode != 0:
            raise PreviewBlocked("github_api_failed")
        try:
            return _mapping(json.loads(completed.stdout), "github_response")
        except json.JSONDecodeError as exc:
            raise PreviewBlocked("github_response_invalid") from exc

    def remote_branch_sha(self, repository: str, branch: str) -> str:
        response = self._gh(f"repos/{repository}/git/ref/heads/{branch}")
        try:
            return str(response["object"]["sha"])
        except (KeyError, TypeError) as exc:
            raise PreviewBlocked("github_branch_identity_invalid") from exc

    def github_ci(self, repository: str, run_id: int) -> Mapping[str, Any]:
        return self._gh(f"repos/{repository}/actions/runs/{run_id}")

    def source_api_guard(self, release_sha: str) -> bool:
        if not SHA_RE.fullmatch(release_sha):
            return False
        completed = subprocess.run(
            ["git", "show", f"{release_sha}:apps/web/next.config.js"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if completed.returncode != 0:
            return False
        source = completed.stdout
        required = (
            "const DEV_VERCEL_PROJECT_URL = 'kamilya-lms-dev.vercel.app';",
            "const DEV_API_URL = 'https://kamilya-lms-api.onrender.com/api';",
            "process.env.VERCEL_PROJECT_PRODUCTION_URL === DEV_VERCEL_PROJECT_URL",
            "NEXT_PUBLIC_API_URL: apiUrl",
        )
        return all(fragment in source for fragment in required)

    def vercel_project(self, project_id: str, team_id: str) -> Mapping[str, Any]:
        quoted_team = urllib.parse.quote(team_id, safe="")
        team = _mapping(
            self._http_json(
                f"https://api.vercel.com/v2/teams/{quoted_team}", self.vercel_token
            ),
            "vercel_team",
        )
        project = _mapping(
            self._http_json(
                "https://api.vercel.com/v9/projects/"
                f"{urllib.parse.quote(project_id, safe='')}?teamId={quoted_team}",
                self.vercel_token,
            ),
            "vercel_project",
        )
        link = _mapping(project.get("link"), "vercel_project_link")
        return {
            "team_id": team.get("id"),
            "team_slug": team.get("slug"),
            "plan": _mapping(team.get("billing"), "vercel_billing").get("plan"),
            "project_id": project.get("id"),
            "project_name": project.get("name"),
            "root_directory": project.get("rootDirectory"),
            "production_branch": link.get("productionBranch"),
            "repository": f"{link.get('org')}/{link.get('repo')}",
            "github_repo_id": str(link.get("repoId")),
            "git_type": link.get("type"),
        }

    def preview_api_url(self, project_id: str, team_id: str) -> str:
        query = urllib.parse.urlencode({"teamId": team_id})
        response = _mapping(
            self._http_json(
                "https://api.vercel.com/v10/projects/"
                f"{urllib.parse.quote(project_id, safe='')}/env?{query}",
                self.vercel_token,
            ),
            "vercel_env_inventory",
        )
        rows = response.get("envs")
        if not isinstance(rows, list):
            raise PreviewBlocked("vercel_env_inventory_invalid")
        matches = []
        for row in rows:
            if not isinstance(row, Mapping) or row.get("key") != "NEXT_PUBLIC_API_URL":
                continue
            targets = row.get("target")
            if isinstance(targets, list) and "preview" in targets and not row.get("gitBranch"):
                matches.append(row)
        if len(matches) != 1 or not isinstance(matches[0].get("value"), str):
            raise PreviewBlocked("preview_api_url_unavailable_or_ambiguous")
        return str(matches[0]["value"])

    def deployment(self, deployment_id_or_url: str, team_id: str) -> Mapping[str, Any]:
        query = urllib.parse.urlencode({"teamId": team_id})
        return _mapping(
            self._http_json(
                "https://api.vercel.com/v13/deployments/"
                f"{urllib.parse.quote(deployment_id_or_url, safe='')}?{query}",
                self.vercel_token,
            ),
            "vercel_deployment",
        )

    def render_deployment(self, service_id: str) -> Mapping[str, Any]:
        response = self._http_json(
            "https://api.render.com/v1/services/"
            f"{urllib.parse.quote(service_id, safe='')}/deploys?limit=1",
            self.render_token,
        )
        if not isinstance(response, list) or len(response) != 1:
            raise PreviewBlocked("render_deployment_inventory_invalid")
        item = response[0]
        if isinstance(item, Mapping) and isinstance(item.get("deploy"), Mapping):
            return _mapping(item["deploy"], "render_deployment")
        return _mapping(item, "render_deployment")

    def create_preview(self, packet: Mapping[str, Any]) -> Mapping[str, Any]:
        vercel = _mapping(packet["vercel"], "vercel")
        sha = str(packet["release_sha"])
        repository_org, repository_name = str(packet["repository"]).split("/", 1)
        query = urllib.parse.urlencode({"teamId": vercel["team_id"]})
        body = {
            "name": vercel["project_name"],
            "project": vercel["project_id"],
            "gitSource": {
                "type": "github",
                "repoId": vercel["github_repo_id"],
                "org": repository_org,
                "repo": repository_name,
                "ref": sha,
                "sha": sha,
            },
        }
        # target is intentionally absent: Vercel therefore creates a preview.
        return _mapping(
            self._http_json(
                f"https://api.vercel.com/v13/deployments?{query}",
                self.vercel_token,
                method="POST",
                body=body,
                create=True,
            ),
            "vercel_create_response",
        )

    def find_previews(self, packet: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        vercel = _mapping(packet["vercel"], "vercel")
        query = urllib.parse.urlencode(
            {
                "projectId": vercel["project_id"],
                "teamId": vercel["team_id"],
                "sha": packet["release_sha"],
                "limit": 20,
            }
        )
        response = _mapping(
            self._http_json(
                f"https://api.vercel.com/v6/deployments?{query}", self.vercel_token
            ),
            "vercel_deployments",
        )
        rows = response.get("deployments")
        if not isinstance(rows, list):
            raise PreviewBlocked("vercel_deployments_invalid")
        return [row for row in rows if isinstance(row, Mapping)]


def _deployment_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    raw_meta = value.get("meta")
    raw_git_source = value.get("gitSource")
    meta: Mapping[str, Any] = raw_meta if isinstance(raw_meta, Mapping) else {}
    git_source: Mapping[str, Any] = (
        raw_git_source if isinstance(raw_git_source, Mapping) else {}
    )
    raw_aliases = value.get("alias", [])
    aliases: list[str] | None
    if raw_aliases is None:
        aliases = []
    elif isinstance(raw_aliases, list) and all(
        isinstance(alias, str) for alias in raw_aliases
    ):
        aliases = list(raw_aliases)
    else:
        aliases = None
    return {
        "deployment_id": value.get("id") or value.get("uid"),
        "status": value.get("readyState") or value.get("state"),
        "target": value.get("target"),
        "url": value.get("url"),
        "release_sha": git_source.get("sha") or meta.get("githubCommitSha"),
        "aliases": aliases,
    }


def _render_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    raw_commit = value.get("commit")
    commit: Mapping[str, Any] = raw_commit if isinstance(raw_commit, Mapping) else {}
    return {
        "deployment_id": value.get("id"),
        "release_sha": commit.get("id") or commit.get("sha"),
        "status": value.get("status"),
    }


class PreviewController:
    def __init__(
        self,
        packet: Mapping[str, Any],
        providers: Providers,
        state_file: Path,
        packet_sha256: str,
        *,
        timeout_seconds: int,
        poll_seconds: float,
    ) -> None:
        self.packet = packet
        self.providers = providers
        self.state_file = state_file
        self.packet_sha256 = packet_sha256
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds

    def _snapshot(self) -> dict[str, Any]:
        repository = str(self.packet["repository"])
        vercel = _mapping(self.packet["vercel"], "vercel")
        baseline = _mapping(self.packet["baseline"], "baseline")
        stable = _deployment_identity(
            self.providers.deployment(str(vercel["stable_alias"]), str(vercel["team_id"]))
        )
        api = _render_identity(
            self.providers.render_deployment(str(baseline["render_api_service_id"]))
        )
        worker = _render_identity(
            self.providers.render_deployment(str(baseline["render_worker_service_id"]))
        )
        return {
            "origin_dev_sha": self.providers.remote_branch_sha(repository, "dev"),
            "stable_alias": stable,
            "render_api": api,
            "render_worker": worker,
        }

    def _verify_baseline(self, snapshot: Mapping[str, Any]) -> None:
        baseline = _mapping(self.packet["baseline"], "baseline")
        if snapshot.get("origin_dev_sha") != baseline["origin_dev_sha"]:
            raise PreviewBlocked("origin_dev_sha_changed")
        stable = _mapping(snapshot.get("stable_alias"), "stable_alias")
        if stable.get("deployment_id") != baseline["stable_alias_deployment_id"]:
            raise PreviewBlocked("stable_alias_deployment_changed")
        if stable.get("target") != "production":
            raise PreviewBlocked("stable_alias_not_production")
        for label in ("render_api", "render_worker"):
            identity = _mapping(snapshot.get(label), label)
            expected = baseline[f"{label}_deployment_id"]
            if identity.get("deployment_id") != expected:
                raise PreviewBlocked(f"{label}_deployment_changed")

    def preflight(self) -> dict[str, Any]:
        github = _mapping(self.packet["github"], "github")
        vercel = _mapping(self.packet["vercel"], "vercel")
        run = self.providers.github_ci(
            str(self.packet["repository"]), int(github["run_id"])
        )
        if run.get("head_sha") != self.packet["release_sha"]:
            raise PreviewBlocked("github_ci_sha_mismatch")
        if run.get("name") != github["workflow"]:
            raise PreviewBlocked("github_ci_workflow_mismatch")
        if run.get("event") != github["event"]:
            raise PreviewBlocked("github_ci_event_mismatch")
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            raise PreviewBlocked("github_ci_not_successful")
        if not self.providers.source_api_guard(str(self.packet["release_sha"])):
            raise PreviewBlocked("source_dev_api_guard_missing")

        project = self.providers.vercel_project(
            str(vercel["project_id"]), str(vercel["team_id"])
        )
        expected_project = {
            "team_id": vercel["team_id"],
            "team_slug": vercel["team_slug"],
            "plan": vercel["expected_plan"],
            "project_id": vercel["project_id"],
            "project_name": vercel["project_name"],
            "root_directory": vercel["root_directory"],
            "production_branch": vercel["production_branch"],
            "repository": self.packet["repository"],
            "github_repo_id": vercel["github_repo_id"],
            "git_type": "github",
        }
        if dict(project) != expected_project:
            raise PreviewBlocked("vercel_project_contract_mismatch")
        if self.providers.preview_api_url(
            str(vercel["project_id"]), str(vercel["team_id"])
        ) != vercel["preview_api_url"]:
            raise PreviewBlocked("preview_api_url_mismatch")
        before = self._snapshot()
        self._verify_baseline(before)
        return {
            "status": "PREFLIGHT_OK",
            "release_id": self.packet["release_id"],
            "release_sha": self.packet["release_sha"],
            "github_ci_run_id": github["run_id"],
            "provider_contract": "EXISTING_HOBBY_PROJECT",
            "preview_api_url": "VERIFIED_EXPECTED",
            "before": before,
        }

    def _base_state(self, before: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "packet_sha256": self.packet_sha256,
            "release_id": self.packet["release_id"],
            "release_sha": self.packet["release_sha"],
            "before": before,
        }

    def create(self, confirm_release_id: str) -> dict[str, Any]:
        if confirm_release_id != self.packet["release_id"]:
            raise PreviewBlocked("create_confirmation_mismatch")
        if self.state_file.exists():
            raise PreviewBlocked("state_exists_resume_or_reconcile_required")
        preflight = self.preflight()
        state = self._base_state(_mapping(preflight["before"], "before"))
        state["operation"] = "create_pending"
        _write_state(self.state_file, state)
        try:
            created = self.providers.create_preview(self.packet)
        except ProviderRequestUnknown:
            state["operation"] = "create_outcome_unknown"
            _write_state(self.state_file, state)
            raise
        identity = _deployment_identity(created)
        deployment_id = identity.get("deployment_id")
        if not isinstance(deployment_id, str) or not DEPLOYMENT_RE.fullmatch(deployment_id):
            state["operation"] = "create_response_without_deployment_id"
            _write_state(self.state_file, state)
            raise PreviewBlocked("vercel_deployment_id_missing")
        state.update({"operation": "created", "deployment_id": deployment_id})
        _write_state(self.state_file, state)  # persist before any subsequent read
        self._verify_preview(identity, allow_in_progress=True)
        return {
            "status": "CREATED",
            "release_sha": self.packet["release_sha"],
            "deployment_id": deployment_id,
            "deployment_url": identity.get("url"),
        }

    def _verify_preview(
        self, identity: Mapping[str, Any], *, allow_in_progress: bool = False
    ) -> None:
        if identity.get("release_sha") != self.packet["release_sha"]:
            raise PreviewBlocked("vercel_preview_sha_mismatch")
        if identity.get("target") not in {None, "preview"}:
            raise PreviewBlocked("vercel_preview_target_mismatch")
        aliases = identity.get("aliases")
        if not isinstance(aliases, list) or not all(
            isinstance(alias, str) for alias in aliases
        ):
            raise PreviewBlocked("vercel_preview_alias_inventory_invalid")
        stable_alias = _mapping(self.packet["vercel"], "vercel")["stable_alias"]
        if stable_alias in aliases:
            raise PreviewBlocked("vercel_preview_stable_alias_assigned")
        status = identity.get("status")
        allowed = TERMINAL_STATES | (IN_PROGRESS_STATES if allow_in_progress else set())
        if status not in allowed:
            raise PreviewBlocked("vercel_preview_status_invalid")

    def _state_for_packet(self) -> dict[str, Any]:
        state = _read_state(self.state_file)
        if state.get("schema") != SCHEMA:
            raise PreviewBlocked("state_schema_mismatch")
        if state.get("packet_sha256") != self.packet_sha256:
            raise PreviewBlocked("state_packet_mismatch")
        if state.get("release_sha") != self.packet["release_sha"]:
            raise PreviewBlocked("state_release_sha_mismatch")
        return state

    def _resolve_deployment_id(self, state: dict[str, Any]) -> str:
        deployment_id = state.get("deployment_id")
        if isinstance(deployment_id, str) and DEPLOYMENT_RE.fullmatch(deployment_id):
            return deployment_id
        if state.get("operation") not in {
            "create_pending",
            "create_outcome_unknown",
            "create_response_without_deployment_id",
        }:
            raise PreviewBlocked("state_deployment_id_missing")
        matches = []
        for deployment in self.providers.find_previews(self.packet):
            identity = _deployment_identity(deployment)
            if (
                identity.get("release_sha") == self.packet["release_sha"]
                and identity.get("target") in {None, "preview"}
                and isinstance(identity.get("aliases"), list)
                and _mapping(self.packet["vercel"], "vercel")["stable_alias"]
                not in identity["aliases"]
            ):
                matches.append(identity)
        if len(matches) != 1:
            raise PreviewBlocked("unknown_outcome_preview_not_unique")
        recovered = matches[0].get("deployment_id")
        if not isinstance(recovered, str) or not DEPLOYMENT_RE.fullmatch(recovered):
            raise PreviewBlocked("recovered_deployment_id_invalid")
        state.update({"operation": "recovered", "deployment_id": recovered})
        _write_state(self.state_file, state)
        return recovered

    def _finish(self, state: dict[str, Any], identity: Mapping[str, Any]) -> dict[str, Any]:
        self._verify_preview(identity)
        status = str(identity["status"])
        after = self._snapshot()
        self._verify_baseline(after)
        if after != state.get("before"):
            raise PreviewBlocked("protected_identities_changed")
        state.update(
            {
                "operation": "terminal",
                "terminal_status": status,
                "deployment_url": identity.get("url"),
                "after": after,
            }
        )
        _write_state(self.state_file, state)
        if status != "READY":
            raise PreviewBlocked(f"vercel_preview_terminal_{status.lower()}")
        return {
            "status": "READY",
            "release_sha": self.packet["release_sha"],
            "deployment_id": identity["deployment_id"],
            "deployment_url": identity.get("url"),
            "protected_identities": "UNCHANGED",
        }

    def wait(self) -> dict[str, Any]:
        state = self._state_for_packet()
        deployment_id = self._resolve_deployment_id(state)
        vercel = _mapping(self.packet["vercel"], "vercel")
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            identity = _deployment_identity(
                self.providers.deployment(deployment_id, str(vercel["team_id"]))
            )
            self._verify_preview(identity, allow_in_progress=True)
            if identity.get("status") in TERMINAL_STATES:
                return self._finish(state, identity)
            if time.monotonic() >= deadline:
                raise PreviewBlocked("vercel_preview_timeout")
            time.sleep(self.poll_seconds)

    def reconcile(self) -> dict[str, Any]:
        state = self._state_for_packet()
        deployment_id = self._resolve_deployment_id(state)
        vercel = _mapping(self.packet["vercel"], "vercel")
        identity = _deployment_identity(
            self.providers.deployment(deployment_id, str(vercel["team_id"]))
        )
        self._verify_preview(identity, allow_in_progress=True)
        if identity.get("status") in TERMINAL_STATES:
            return self._finish(state, identity)
        after = self._snapshot()
        self._verify_baseline(after)
        if after != state.get("before"):
            raise PreviewBlocked("protected_identities_changed")
        return {
            "status": identity["status"],
            "release_sha": self.packet["release_sha"],
            "deployment_id": deployment_id,
            "deployment_url": identity.get("url"),
            "protected_identities": "UNCHANGED",
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "create", "wait", "reconcile"))
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--packet-sha256", required=True)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--state-file", required=True, type=Path)
    parser.add_argument("--confirm-release-id", default="")
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if not 1 <= args.timeout_seconds <= 1800:
            raise PreviewBlocked("timeout_seconds_invalid")
        if not 0.1 <= args.poll_seconds <= 60:
            raise PreviewBlocked("poll_seconds_invalid")
        repo_root = args.repo_root.resolve()
        packet = load_packet(args.packet, args.packet_sha256)
        state_file = _state_path(args.state_file, repo_root)
        providers = LiveProviders(repo_root, args.env_file, args.timeout_seconds)
        controller = PreviewController(
            packet,
            providers,
            state_file,
            args.packet_sha256,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
        )
        if args.command == "preflight":
            result = controller.preflight()
        elif args.command == "create":
            result = controller.create(args.confirm_release_id)
        elif args.command == "wait":
            result = controller.wait()
        else:
            result = controller.reconcile()
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 0
    except PreviewBlocked as exc:
        print(
            json.dumps(
                {"status": "BLOCKED", "reason": str(exc)},
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
