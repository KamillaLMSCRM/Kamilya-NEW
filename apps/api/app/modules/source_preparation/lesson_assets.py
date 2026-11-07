"""Bind model-selected illustration markers to approved, immutable source assets."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from app.modules.source_preparation.domain import validate_binding

_IMAGE = re.compile(r"!\[([^\]\n]*)\]\(source-asset:(asset-[a-f0-9]{64})\)")


def approved_asset_inventory(approved: dict[str, Any]) -> dict[str, dict[str, str]]:
    inventory: dict[str, dict[str, str]] = {}
    for doc_id, source in approved.items():
        if source.preparation is None:
            continue
        package, selected = validate_binding(source.preparation, source.source_revision.removeprefix("document:"),
                                             source.recognized_text)
        ids = {i for b in package.selected(selected)[2] for i in b.asset_ids}
        for asset in package.assets:
            if asset.id in ids and asset.kind != "scan":
                descriptor = {"id": asset.id, "document_id": doc_id, "sha256": asset.sha256,
                              "mime_type": asset.mime_type, "storage_key": asset.storage_key,
                              "preparation_sha256": package.sha256}
                if asset.id in inventory and inventory[asset.id] != descriptor:
                    # Identical image bytes in two sources retain one exact approved owner.
                    continue
                inventory[asset.id] = descriptor
    return inventory


def bind_lesson_assets(content: str, inventory: dict[str, dict[str, str]], *, course_id: UUID,
                       lesson_id: UUID) -> tuple[str, list[dict[str, str]]]:
    selected: dict[str, dict[str, str]] = {}

    def replace(match: re.Match[str]) -> str:
        asset_id = match[2]
        if asset_id not in inventory:
            raise ValueError("generation_source_image_unapproved")
        selected[asset_id] = inventory[asset_id]
        # Put images on their own line for the shared safe renderer.
        return f"\n\n![{match[1]}](/v1/courses/{course_id}/lessons/{lesson_id}/source-assets/{asset_id})\n\n"

    result = _IMAGE.sub(replace, content)
    if "source-asset:" in result:
        raise ValueError("generation_source_image_marker_invalid")
    return result, list(selected.values())
