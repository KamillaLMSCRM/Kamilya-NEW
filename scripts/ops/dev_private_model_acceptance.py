"""Expiring, Redis-claimed synthetic acceptance on the actual Render DEV host.

Never mounted as an HTTP endpoint; no persisted model failure or provider override.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path


def enabled(env: dict[str, str], now: datetime) -> bool:
    try:
        expiry = datetime.fromisoformat(env.get("DEV_MODEL_ACCEPTANCE_UNTIL", ""))
        remaining = (expiry - now).total_seconds()
    except (ValueError, TypeError):
        return False
    expected_env = {"api": "render-development", "worker": "render-development-worker"}
    return (env.get("DEPLOYMENT_ENVIRONMENT") == expected_env.get(env.get("DEV_MODEL_ACCEPTANCE_ROLE"), "DENIED")
        and env.get("DEV_MODEL_ACCEPTANCE_SCOPE", "full_chain") in {"full_chain", "primary_chatgpt", "assignment_intent"}
        and (env.get("DEV_MODEL_ACCEPTANCE_SCOPE") != "assignment_intent" or env.get("DEV_MODEL_ACCEPTANCE_ROLE") == "api")
        and env.get("DEV_MODEL_ACCEPTANCE_ROLE") in {"api", "worker"}
        and re.fullmatch(r"DEV-PRIVATE-20261016-[A-Z0-9]{1,12}", env.get("DEV_MODEL_ACCEPTANCE_ID", "")) is not None
        and 0 < remaining <= 1200)


def call_deadline(env: dict[str, str], now: datetime) -> float:
    if not enabled(env, now):
        return 0
    return min(35.0, (datetime.fromisoformat(env["DEV_MODEL_ACCEPTANCE_UNTIL"]) - now).total_seconds())


def permitted_provider_configs(clients: list, partial: bool) -> list:
    # Even an unexpected double failure in partial mode must not contact ASUS.
    return [client.config for client in clients[:2 if partial else 3]]


async def unavailable(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        async with asyncio.timeout(2):
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            await writer.drain()
    except (OSError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        pass
    finally:
        writer.close()
        await writer.wait_closed()


async def run() -> dict:
    if os.environ.get("DEV_MODEL_ACCEPTANCE_SCOPE") == "assignment_intent":
        from dev_assignment_intent_acceptance import run_assignment
        return await run_assignment()
    # Imported only after the explicit DEV-only opt-in/time gate.
    from redis.asyncio import Redis
    from app.core.config import get_settings
    from app.core.db import engine
    from app.modules.admin.model_routing.runtime import resolve_runtime_generation_model_order
    from app.modules.ai import llm_client as llm

    env = os.environ
    role, run_id = env["DEV_MODEL_ACCEPTANCE_ROLE"], env["DEV_MODEL_ACCEPTANCE_ID"]
    partial = env.get("DEV_MODEL_ACCEPTANCE_SCOPE") == "primary_chatgpt"
    success = "PARTIAL_PASS" if partial else "PASS"
    result = {"role": role, "run_id": run_id, "cases": [], "production_writes": 0,
        "persisted_failure_overrides": 0, "fault_mode": "ephemeral_loopback_HTTP503",
        "release_sha": env.get("RENDER_GIT_COMMIT", "unknown")}
    result["executed_scope"] = "primary_chatgpt" if partial else "full_chain"
    result["glm"] = "NOT_RUN_OWNER_DEFERRED_ASUS_DOWN" if partial else "REQUIRED"
    settings = get_settings()
    redis = Redis.from_url(settings.REDIS_URL, socket_connect_timeout=3, socket_timeout=3)
    claimed = False
    terminal_status = "FAIL"
    try:
        # Claim before any model call: cold starts/restarts cannot repeat this run.
        claimed = await redis.set(f"qa:dev-private-models:{run_id}:{role}", "claimed", nx=True, ex=3600)
        if not claimed:
            return {**result, "status": "ALREADY_CLAIMED_NO_INFERENCE"}
        deadline = min(time.monotonic() + 180,
            time.monotonic() + (datetime.fromisoformat(env["DEV_MODEL_ACCEPTANCE_UNTIL"]) - datetime.now(UTC)).total_seconds())
        expected = ("deepseek", "chatgpt_reserve", "glm53_flash")
        while time.monotonic() < deadline:
            if await resolve_runtime_generation_model_order() == expected:
                break
            await asyncio.sleep(4)
        else:
            return {**result, "status": "BLOCKED_ROUTE_NOT_READY_NO_INFERENCE"}
        # Serialize the two host-role probes against the single shared connector.
        # Wait for API's terminal marker rather than choosing a guessed delay.
        api_done = f"qa:dev-private-models:{run_id}:api:terminal"
        if role == "worker":
            while time.monotonic() < deadline:
                terminal = await redis.get(api_done)
                if terminal == success.encode():
                    break
                if terminal is not None:
                    return {**result, "status": "BLOCKED_API_FAILED_NO_INFERENCE"}
                await asyncio.sleep(3)
            else:
                return {**result, "status": "BLOCKED_API_NOT_TERMINAL_NO_INFERENCE"}
        server = await asyncio.start_server(unavailable, "127.0.0.1", 0, limit=8192)
        port = server.sockets[0].getsockname()[1]
        try:
            cases = (
                ["deepseek"], ["deepseek", "chatgpt-reserve"],
                ["deepseek", "chatgpt-reserve", "glm53-flash-asus"],
            )[:2 if partial else 3]
            for index, expected_names in enumerate(cases):
                if not enabled(dict(env), datetime.now(UTC)):
                    result["cases"].append({"case": index, "status": "EXPIRED_NO_INFERENCE"})
                    break
                source = await llm.ResilientLLMClient.from_settings_async(
                    temperature=0, max_tokens=512, max_retries_per_provider=0)
                if source.provider_names != ["deepseek", "chatgpt-reserve", "glm53-flash-asus"]:
                    raise ValueError("runtime_route_mismatch")
                providers = permitted_provider_configs(source._clients, partial)
                for failed in range(index):
                    providers[failed] = replace(providers[failed],
                        base_url=f"http://127.0.0.1:{port}/v1", api_key="synthetic-control",
                        timeout=3, connect_timeout=1, max_retries=0, trust_env=False)
                chain = llm.ResilientLLMClient(providers, temperature=0,
                    max_tokens=512, max_retries_per_provider=0)
                attempts = []
                for client in chain._clients:
                    original, name = client.ainvoke, client.name

                    async def recorded(*args, _original=original, _name=name, **kwargs):
                        attempts.append(_name)
                        return await _original(*args, **kwargs)

                    client.ainvoke = recorded
                row = {"case": index, "expected_provider": expected_names[-1]}
                started = time.monotonic()
                try:
                    remaining = call_deadline(dict(env), datetime.now(UTC))
                    if remaining <= 0:
                        raise TimeoutError("acceptance_expired")
                    async with asyncio.timeout(remaining):
                        answer = await chain.ainvoke([
                            {"role": "system", "content": "Synthetic connectivity test. No actions, tools or personal data. Reply only the exact JSON requested."},
                            {"role": "user", "content": 'Return exactly {"ok":true,"check":"private-dev"}'}],
                            response_format={"type": "json_object"})
                    valid = json.loads(answer.content) == {"ok": True, "check": "private-dev"}
                    row.update(status="PASS" if valid and attempts == expected_names else "FAIL",
                        expected_json=valid)
                except Exception as exc:
                    row.update(status="FAIL", error_class=type(exc).__name__)
                row.update(attempt_order=attempts, elapsed_ms=round((time.monotonic() - started) * 1000))
                result["cases"].append(row)
                if row["status"] != "PASS":
                    break
        finally:
            server.close()
            await server.wait_closed()
        result["status"] = success if len(result["cases"]) == len(cases) and all(row["status"] == "PASS" for row in result["cases"]) else "FAIL"
        terminal_status = result["status"]
        return result
    finally:
        if role == "api" and claimed:
            await redis.set(f"qa:dev-private-models:{run_id}:api:terminal", terminal_status, ex=3600)
        await redis.aclose()
        await engine.dispose()


def main() -> int:
    if not enabled(dict(os.environ), datetime.now(UTC)):
        print('DEV_MODEL_ACCEPTANCE|{"status":"DISABLED_OR_EXPIRED_NO_INFERENCE"}', flush=True)
        return 0
    # This process reports only its fixed schema. Upstream logs never escape it.
    logging.disable(logging.CRITICAL)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps/api"))
    try:
        result = asyncio.run(run())
    except Exception as exc:
        result = {"status": "BLOCKED", "error_class": type(exc).__name__,
            "role": os.environ["DEV_MODEL_ACCEPTANCE_ROLE"]}
    print("DEV_MODEL_ACCEPTANCE|" + json.dumps(result, separators=(",", ":")), flush=True)
    return 0 if result["status"] in {"PASS", "PARTIAL_PASS", "ALREADY_CLAIMED_NO_INFERENCE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
