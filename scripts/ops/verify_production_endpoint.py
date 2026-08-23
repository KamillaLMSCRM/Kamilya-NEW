#!/usr/bin/env python3
"""Verify that public Kamilya endpoints resolve to the intended KZ release."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
MAX_RESPONSE_BYTES = 1024 * 1024


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def validate_health_payload(
    payload: Any,
    *,
    expected_deployment: str,
    expected_release: str,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["health response must be a JSON object"]
    if payload.get("status") != "ok":
        errors.append("status must be ok")
    if payload.get("app") != "Kamilya LMS":
        errors.append("app identity does not match Kamilya LMS")
    if payload.get("app_environment") != "production":
        errors.append("app_environment must be production")
    if payload.get("deployment_environment") != expected_deployment:
        errors.append("deployment_environment does not match the expected runtime")

    actual_release = payload.get("release_sha")
    if not isinstance(actual_release, str) or not FULL_SHA.fullmatch(actual_release):
        errors.append("release_sha must be a full 40-character Git SHA")
    if expected_release and actual_release != expected_release:
        errors.append("release_sha does not match the expected release")
    return errors


def _origin(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    return parsed.scheme.lower(), parsed.netloc.lower()


def _fetch_json_without_redirect(url: str) -> Any:
    opener = build_opener(_NoRedirect())
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "kamilya-release-verifier/1"})
    with opener.open(request, timeout=20) as response:
        if response.status != 200:
            raise RuntimeError("health endpoint did not return HTTP 200")
        if _origin(response.geturl()) != _origin(url):
            raise RuntimeError("health endpoint changed origin")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise RuntimeError("health response exceeds the size limit")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("health endpoint did not return valid UTF-8 JSON") from exc


def _check_web(url: str) -> None:
    opener = build_opener(_NoRedirect())
    request = Request(url, headers={"User-Agent": "kamilya-release-verifier/1"})
    with opener.open(request, timeout=20) as response:
        if response.status != 200:
            raise RuntimeError("web endpoint did not return HTTP 200")
        if _origin(response.geturl()) != _origin(url):
            raise RuntimeError("web endpoint changed origin")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="https://api.kml.kz/api/v1/health")
    parser.add_argument("--web-url", default="https://app.kml.kz/login")
    parser.add_argument("--expected-deployment", default="kz-production")
    parser.add_argument("--expected-release", default=os.getenv("EXPECTED_RELEASE_SHA", ""))
    args = parser.parse_args()

    if args.expected_release and not FULL_SHA.fullmatch(args.expected_release):
        print("verification failed: expected release must be a full 40-character Git SHA", file=sys.stderr)
        return 2
    try:
        payload = _fetch_json_without_redirect(args.api_url)
        errors = validate_health_payload(
            payload,
            expected_deployment=args.expected_deployment,
            expected_release=args.expected_release,
        )
        if errors:
            raise RuntimeError("; ".join(errors))
        _check_web(args.web_url)
    except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
        print(f"verification failed: {exc}", file=sys.stderr)
        return 1

    print("KZ production identity and public endpoints verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
