"""Request-local provider policy for fresh V3 course generation.

This adapter is intentionally not a routing or provider factory.  It binds one
already-resolved managed client to one immutable runtime snapshot and makes the
request profile part of the checkpoint identity.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.modules.admin.runtime_configuration.catalog import RuntimeSnapshot
from app.modules.admin.runtime_configuration.runtime import runtime_settings_scope
from app.modules.ai.llm_client import (
    COURSE_GENERATION_MAX_TOKENS,
    EXTENDED_COURSE_GENERATION_MAX_TOKENS,
    EXTENDED_COURSE_GENERATION_SECONDS,
    RequestProfile,
    ResilientLLMClient,
)
from app.modules.ai.source_first_response import parse_source_first_response
from app.modules.ai.v3.rejected_artifact import ModelArtifactRejectedError
from app.modules.ai.v3.stage_checkpoint import _digest

logger = logging.getLogger(__name__)

PROFILE_VERSION = "v3-course-generation-profile-v1"


def _profile_values(policy: RuntimeSnapshot) -> dict[str, object]:
    """Read only the frozen settings that affect the managed request."""
    return {
        "deepseek_seconds": policy.number("provider.deepseek.timeout_seconds"),
        "max_tokens": COURSE_GENERATION_MAX_TOKENS,
        "thinking": "enabled",
        "reasoning_effort": "low",
    }


def _policy_digest(policy: RuntimeSnapshot, values: Mapping[str, object]) -> str:
    payload = {"values": dict(values)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _effective_profile_values(
    policy: RuntimeSnapshot, client: ResilientLLMClient, request_profile: RequestProfile,
) -> dict[str, object]:
    from app.modules.ai.v3.local_deepseek_dev import (
        GENERATION_SECONDS,
        THINKING_BUDGET,
        is_local_deepseek_dev_client,
    )
    values = _profile_values(policy)
    if request_profile == "course_generation_extended":
        values.update(deepseek_seconds=EXTENDED_COURSE_GENERATION_SECONDS,
                      max_tokens=EXTENDED_COURSE_GENERATION_MAX_TOKENS)
    elif is_local_deepseek_dev_client(client):
        values.update(local_generation_seconds=GENERATION_SECONDS, thinking_budget=THINKING_BUDGET,
                      structured_output_mode='prompt_json')
    return values


class V3ProfiledClient:
    """Apply the fresh V3 course-generation profile to one resolved client."""

    def __init__(self, client: ResilientLLMClient, policy: RuntimeSnapshot, *, job_id: str,
                 cooperative_deadline: bool = False, extended_output: bool = False):
        if type(client) is not ResilientLLMClient:
            raise TypeError("v3_provider_profile_client_invalid")
        if not isinstance(policy, RuntimeSnapshot):
            raise TypeError("v3_provider_profile_policy_invalid")
        if type(cooperative_deadline) is not bool:
            raise ValueError("v3_provider_cooperative_deadline_invalid")
        if type(extended_output) is not bool or extended_output and not cooperative_deadline:
            raise ValueError("v3_provider_extended_output_invalid")
        if cooperative_deadline and type(policy.values.get("provider.deepseek.timeout_seconds")) not in (int, float):
            raise ValueError("v3_provider_cooperative_deadline_invalid")
        self._client = client
        self._policy = policy
        self._job_id = job_id
        self._base_fingerprint = client.cache_fingerprint()
        managed_deepseek = any(
            provider.name == "deepseek" and provider.config.managed_evidence_profile
            for provider in client._clients
        )
        self._request_profile: RequestProfile = (
            "course_generation_extended" if extended_output and managed_deepseek else "course_generation"
        )
        self._values = _effective_profile_values(policy, client, self._request_profile)
        seconds = self._values.get('local_generation_seconds', self._values["deepseek_seconds"])
        self._generation_deadline_seconds: float | None = None
        if cooperative_deadline:
            if (isinstance(seconds, bool) or not isinstance(seconds, int | float)
                    or not math.isfinite(seconds) or seconds <= 0 or seconds > 3600):
                raise ValueError("v3_provider_cooperative_deadline_invalid")
            self._generation_deadline_seconds = float(seconds)
        self._policy_identity = _policy_digest(policy, self._values)
        self._fingerprint = hashlib.sha256(json.dumps({
            "base": self._base_fingerprint,
            "profile": "v3-course-generation-profile-v2" if cooperative_deadline else PROFILE_VERSION,
            "policy": self._values,
            **({"whole_invocation_seconds": self.generation_deadline_seconds} if cooperative_deadline else {}),
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def cache_fingerprint(self) -> str:
        return self._fingerprint

    @property
    def generation_deadline_seconds(self) -> float | None:
        return self._generation_deadline_seconds

    @property
    def provider_names(self) -> list[str]:
        return self._client.provider_names

    def _assert_identity(self) -> None:
        if self._client.cache_fingerprint() != self._base_fingerprint:
            raise RuntimeError("v3_provider_profile_route_changed")
        if _policy_digest(self._policy, _effective_profile_values(
            self._policy, self._client, self._request_profile,
        )) != self._policy_identity:
            raise RuntimeError("v3_provider_profile_policy_changed")

    async def ainvoke(
        self,
        messages: str | list[dict[str, Any]],
        config: dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> Any:
        self._assert_identity()
        try:
            with runtime_settings_scope(self._policy):
                if self.generation_deadline_seconds is None:
                    response = await self._client.ainvoke(messages, config=config, response_format=response_format,
                                                          request_profile=self._request_profile)
                else:
                    async with asyncio.timeout(self.generation_deadline_seconds):
                        response = await self._client.ainvoke(messages, config=config, response_format=response_format,
                                                              request_profile=self._request_profile)
            try:
                if (getattr(response, "finish_reason", None) in {"length", "content_filter"}
                        or getattr(response, "content_is_reasoning", False)):
                    raise ValueError("v3_provider_incomplete_response")
                parse_source_first_response(response.content)
            except ValueError:
                content = getattr(response, "content", None)
                if not isinstance(content, str) or any(
                        item.config.api_key and item.config.api_key in content for item in self._client._clients):
                    raise ValueError("v3_provider_response_invalid") from None
                complete = getattr(response, "usage_complete", False) is True
                raise ModelArtifactRejectedError(content,
                    provider=getattr(response, "provider_name", None), model=getattr(response, "model", None),
                    input_tokens=getattr(response, "prompt_tokens", None) if complete else None,
                    output_tokens=getattr(response, "completion_tokens", None) if complete else None) from None
        except ModelArtifactRejectedError as exc:
            raise exc.bound(job_id=self._job_id, route=self._fingerprint,
                            request=_digest([messages, response_format])) from None
        provider = getattr(response, "provider_name", None)
        model = getattr(response, "model", None)
        if not isinstance(provider, str) or not provider:
            provider = None
        if not isinstance(model, str) or not model:
            model = None
        usage_complete = getattr(response, "usage_complete", None)
        if type(usage_complete) is not bool:
            usage_complete = None
        try:
            safe_job = str(UUID(str(self._job_id)))
        except (ValueError, TypeError, AttributeError):
            safe_job = "unknown"
        logger.info(
            "v3.provider_profile.completed job_id=%s provider=%s model=%s input_tokens=%s output_tokens=%s usage_complete=%s",
            safe_job,
            provider or "unknown",
            model or "unknown",
            getattr(response, "prompt_tokens", None) if usage_complete is True else None,
            getattr(response, "completion_tokens", None) if usage_complete is True else None,
            usage_complete if usage_complete is not None else "unknown",
        )
        return response
