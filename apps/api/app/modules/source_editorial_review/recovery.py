"""Resume a stale terminal turn, never an unresolved inference or visual request."""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.source_editorial_review.request_custody import POLICY


def recoverable_turn(rows: Sequence[Any], blob_sha: str, actor_id: UUID | None, *,
                     interrupted: bool) -> tuple[Any, Any] | None:
    if not interrupted or not rows or actor_id is None:
        return None
    latest = rows[-1]
    claim_id = latest.payload.get("claim_id")
    turn = latest.payload.get("result")
    if (latest.kind != "analysis_block" or latest.original_blob_sha256 != blob_sha
            or latest.actor_id != actor_id or not isinstance(claim_id, str)
            or latest.payload.get("key") != "source-review-v2:turn-usage:" + claim_id):
        return None
    if not isinstance(turn, dict) or not isinstance(turn.get("usage"), list) or type(turn.get("usage_complete")) is not bool:
        return None
    claim = next((row for row in rows if row.kind == "running" and str(row.id) == claim_id), None)
    if claim is None or claim.actor_id != actor_id or claim.original_blob_sha256 != blob_sha:
        return None
    parent = next((row for row in rows if str(row.id) == claim.payload.get("queued_event_id")
                   and row.kind == "queued" and row.sequence + 1 == claim.sequence), None)
    if parent is None or parent.actor_id != actor_id or parent.original_blob_sha256 != blob_sha:
        return None
    binding = parent.payload.get("preparation")
    if (not isinstance(binding, dict) or not isinstance(binding.get("manifest"), dict)
            or binding["manifest"].get("assets") != []):
        return None  # Visual custody needs its own complete proof; absence is not success.
    tail = [row for row in rows if claim.sequence < row.sequence]
    if any(row.kind != "analysis_block" or row.payload.get("claim_id") != claim_id
           or row.actor_id != actor_id or row.original_blob_sha256 != blob_sha for row in tail):
        return None
    last_analyzed = max((row.sequence for row in rows if row.kind == "analyzed"), default=0)
    receipts: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.sequence <= last_analyzed or row.kind != "analysis_block":
            continue
        key = row.payload.get("key", "")
        if isinstance(key, str) and key.startswith(("source-preparation-v1:image:",
                "source-preparation-v1:reviewed-image:", "source-review-v2:visual-usage:")):
            return None
        if not isinstance(key, str) or not key.startswith(POLICY + ":"):
            continue
        match = re.fullmatch(re.escape(POLICY) + r":([a-f0-9]{64}):([a-z0-9-]+):(intent|completed)", key)
        value = row.payload.get("result")
        if (match is None or not isinstance(value, dict) or value.get("identity") != match[1]
                or value.get("attempt") != match[2] or key in receipts):
            return None
        if match[3] == "intent" and value.get("state") != "started":
            return None
        if match[3] == "completed" and (value.get("status") not in (
                "ok", "invalid_json", "response_rejected", "rejected") or "usage" not in value
                or value.get("status") == "ok" and "value" not in value):
            return None
        receipts[key] = value
    if any(key.endswith(":intent") and key[:-len(":intent")] + ":completed" not in receipts for key in receipts):
        return None
    if any(key.endswith(":completed") and key[:-len(":completed")] + ":intent" not in receipts for key in receipts):
        return None
    return claim, parent
