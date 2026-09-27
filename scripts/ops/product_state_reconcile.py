#!/usr/bin/env python3
"""Reconcile source, production API and native frontend release identities."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.ops.verify_production_endpoint import (  # noqa: E402
    MAX_RESPONSE_BYTES,
    _NoRedirect,
    _fetch_json_without_redirect,
    _origin,
    validate_health_payload,
)

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
AncestorCheck = Callable[[str, str], bool]


class ProductStateError(RuntimeError):
    """The observed product state cannot be reconciled safely."""


def parse_frontend_health(body: str, release_header: str) -> str:
    """Return the exact frontend SHA when body and header agree."""

    match = re.fullmatch(r"ok ([0-9a-f]{40})", body.strip())
    if match is None or FULL_SHA.fullmatch(release_header or "") is None:
        raise ProductStateError("frontend_health_invalid")
    body_sha = match.group(1)
    if body_sha != release_header:
        raise ProductStateError("frontend_release_mismatch")
    return body_sha


def reconcile_product_state(
    *,
    source_version: str,
    source_sha: str,
    api_payload: Mapping[str, Any],
    frontend_sha: str,
    is_ancestor: AncestorCheck,
) -> dict[str, Any]:
    """Classify exact alignment, legitimate source ancestry, or runtime drift."""

    if SEMVER.fullmatch(source_version) is None or FULL_SHA.fullmatch(source_sha) is None:
        raise ProductStateError("source_identity_invalid")
    api_errors = validate_health_payload(
        api_payload,
        expected_deployment="kz-production",
        expected_release="",
        expected_version="",
    )
    if api_errors:
        raise ProductStateError("api_health_invalid:" + ";".join(api_errors))
    api_sha = str(api_payload["release_sha"])
    api_version = str(api_payload["product_version"])
    if FULL_SHA.fullmatch(frontend_sha) is None:
        raise ProductStateError("frontend_release_invalid")

    api_exact = api_sha == source_sha
    frontend_exact = frontend_sha == source_sha
    api_ancestor = api_exact or is_ancestor(api_sha, source_sha)
    frontend_ancestor = frontend_exact or is_ancestor(frontend_sha, source_sha)
    if api_exact and frontend_exact:
        status = "ALIGNED"
    elif api_ancestor and frontend_ancestor:
        status = "SPLIT_ANCESTRY"
    else:
        status = "DRIFT"
    return {
        "schema_version": "kamilya-product-state-v1",
        "status": status,
        "source": {"version": source_version, "sha": source_sha},
        "api": {
            "version": api_version,
            "sha": api_sha,
            "exact": api_exact,
            "ancestor_of_source": api_ancestor,
        },
        "frontend": {
            "sha": frontend_sha,
            "exact": frontend_exact,
            "ancestor_of_source": frontend_ancestor,
        },
    }


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if completed.returncode != 0:
        raise ProductStateError("git_identity_failed")
    return completed.stdout.strip()


def _git_is_ancestor(repository: Path, older: str, newer: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(repository), "merge-base", "--is-ancestor", older, newer],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if completed.returncode == 0:
        return True
    if completed.returncode == 1:
        return False
    raise ProductStateError("git_ancestry_failed")


def _fetch_frontend_health(url: str) -> str:
    opener = build_opener(_NoRedirect())
    request = Request(url, headers={"User-Agent": "kamilya-product-state/1"})
    with opener.open(request, timeout=20) as response:
        if response.status != 200:
            raise ProductStateError("frontend_health_http_invalid")
        if _origin(response.geturl()) != _origin(url):
            raise ProductStateError("frontend_health_origin_changed")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ProductStateError("frontend_health_too_large")
        header = response.headers.get("X-Kamilya-Release", "")
    try:
        body = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProductStateError("frontend_health_invalid") from exc
    return parse_frontend_health(body, header)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repository", type=Path, default=REPOSITORY_ROOT
    )
    parser.add_argument("--api-url", default="https://api.kml.kz/api/v1/health")
    parser.add_argument("--web-health-url", default="https://app.kml.kz/healthz")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    repository = args.repository.resolve(strict=True)
    try:
        source_version = (repository / "VERSION").read_text(encoding="utf-8").strip()
        source_sha = _git(repository, "rev-parse", "HEAD")
        tag_sha = _git(repository, "rev-parse", f"v{source_version}^{{}}")
        if tag_sha != source_sha:
            raise ProductStateError("source_tag_mismatch")
        api_payload = _fetch_json_without_redirect(args.api_url)
        frontend_sha = _fetch_frontend_health(args.web_health_url)
        report = reconcile_product_state(
            source_version=source_version,
            source_sha=source_sha,
            api_payload=api_payload,
            frontend_sha=frontend_sha,
            is_ancestor=lambda older, newer: _git_is_ancestor(
                repository, older, newer
            ),
        )
    except (HTTPError, URLError, OSError, TimeoutError, ProductStateError) as exc:
        print(json.dumps({"status": "ERROR", "reason": str(exc)}, sort_keys=True))
        return 2

    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 1 if report["status"] == "DRIFT" else 0


if __name__ == "__main__":
    raise SystemExit(main())
