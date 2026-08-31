"""Idempotently provision the persistent synthetic KZ production smoke tenant."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
API_BASE = "https://api.kml.kz/api/v1"
SLUG = "kamilya-production-smoke"
MARKER = "[KAMILYA_SYNTHETIC_SMOKE_V1]"


def load_env() -> None:
    for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


async def request_json(client: httpx.AsyncClient, method: str, path: str, *, expected=(200,), **kwargs):
    response = await client.request(method, f"{API_BASE}{path}", **kwargs)
    if response.status_code not in expected:
        raise RuntimeError(f"request_failed:{method}:{path}:http_{response.status_code}")
    return response.json() if response.content else None


async def provision() -> None:
    if os.getenv("CONFIRM_PERSISTENT_PRODUCTION_SMOKE") != "1":
        raise RuntimeError("CONFIRM_PERSISTENT_PRODUCTION_SMOKE=1 is required")
    smoke_email = required("PRODUCTION_SMOKE_METHODOLOGIST_EMAIL")
    smoke_password = required("PRODUCTION_SMOKE_METHODOLOGIST_PASSWORD")
    super_email = required("SUPERADMIN_EMAIL")
    super_password = required("SUPERADMIN_PASSWORD")
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        login = await request_json(client, "POST", "/auth/login", json={"email": super_email, "password": super_password})
        headers = {"Authorization": f"Bearer {login['access_token']}"}
        listing = await request_json(client, "GET", f"/admin/super/tenants?search={SLUG}&limit=100", headers=headers)
        matches = [tenant for tenant in listing["tenants"] if tenant["slug"] == SLUG]
        if len(matches) > 1:
            raise RuntimeError("smoke_tenant_duplicate")
        if matches:
            tenant = matches[0]
            if not tenant["is_demo"] or tenant["is_financial_organization"] or MARKER not in (tenant.get("notes") or ""):
                raise RuntimeError("existing_smoke_tenant_contract_mismatch")
        else:
            created = await request_json(
                client,
                "POST",
                "/admin/super/tenants",
                expected=(201,),
                headers=headers,
                json={
                    "name": "Kamilya Production Smoke (Synthetic)",
                    "slug": SLUG,
                    "plan": "enterprise",
                    "status": "active",
                    "is_demo": True,
                    "is_financial_organization": False,
                    "max_users": 20,
                    "max_courses_per_month": 50,
                    "notes": f"{MARKER} Persistent non-customer tenant for bounded production acceptance.",
                },
            )
            tenant = created["tenant"]
        tenant_id = tenant["id"]
        impersonated = await request_json(
            client, "POST", f"/admin/super/tenants/{tenant_id}/impersonate", headers=headers, json={"role": "admin"}
        )
        tenant_headers = {"Authorization": f"Bearer {impersonated['access_token']}"}
        users = await request_json(client, "GET", "/users?per_page=100&include_students=true", headers=tenant_headers)
        exact = [user for user in users["users"] if (user.get("email") or "").lower() == smoke_email.lower()]
        if len(exact) > 1:
            raise RuntimeError("smoke_methodologist_duplicate")
        if not exact:
            await request_json(
                client,
                "POST",
                "/users",
                expected=(201,),
                headers=tenant_headers,
                json={
                    "email": smoke_email,
                    "first_name": "Synthetic",
                    "last_name": "Methodologist",
                    "role": "methodologist",
                    "password": smoke_password,
                    "is_active": True,
                },
            )
        methodologist_login = await request_json(
            client, "POST", "/auth/login", json={"email": smoke_email, "password": smoke_password}
        )
        me = await request_json(
            client, "GET", "/users/me", headers={"Authorization": f"Bearer {methodologist_login['access_token']}"}
        )
        if me["tenant_id"] != tenant_id or "methodologist" not in me.get("roles", []):
            raise RuntimeError("smoke_methodologist_identity_mismatch")
        print(json.dumps({"status": "READY", "tenant_slug": SLUG, "is_demo": True, "mail_sent": False}, sort_keys=True))


def main() -> int:
    try:
        load_env()
        asyncio.run(provision())
        return 0
    except (RuntimeError, OSError, KeyError, httpx.HTTPError) as error:
        print(json.dumps({"status": "BLOCKED", "reason": str(error)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
