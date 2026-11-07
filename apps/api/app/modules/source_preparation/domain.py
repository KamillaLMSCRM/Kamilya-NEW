"""Validated immutable source manifests and deterministic part selection."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

POLICY: Literal["source-preparation-v1"] = "source-preparation-v1"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class SourceBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=r"^block-[a-f0-9]{24}$")
    text: str = Field(max_length=1_000_000)
    kind: str = Field(max_length=30)
    page: int | None = Field(default=None, ge=1)
    asset_ids: list[str] = Field(default_factory=list)
    locator: dict[str, Any] = Field(default_factory=dict)


class SourceAsset(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=r"^asset-[a-f0-9]{64}$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    mime_type: Literal["image/png", "image/jpeg"]
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    storage_key: str = Field(min_length=1, max_length=400)
    caption: str = Field(min_length=1, max_length=300)
    kind: Literal["scan", "screen", "form", "figure"]
    text: str = Field(max_length=60_000)
    description: str = Field(max_length=3000)
    uncertainties: list[str] = Field(default_factory=list, max_length=100)
    locator: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def identity(self) -> SourceAsset:
        if self.id != "asset-" + self.sha256:
            raise ValueError("source_asset_identity_invalid")
        return self


class SourcePart(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=r"^part-[a-f0-9]{24}$")
    title: str = Field(min_length=1, max_length=300)
    role: Literal["learning", "supporting", "administrative"]
    reason: str = Field(min_length=1, max_length=1200)
    first_block: str
    last_block: str


class PreparedSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    policy: Literal["source-preparation-v1"] = POLICY
    original_blob_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    blocks: list[SourceBlock] = Field(min_length=1, max_length=50_000)
    assets: list[SourceAsset] = Field(default_factory=list, max_length=5000)
    parts: list[SourcePart] = Field(min_length=1, max_length=5000)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def complete_partition(self) -> PreparedSource:
        block_ids = [block.id for block in self.blocks]
        asset_ids = {asset.id for asset in self.assets}
        if len(set(block_ids)) != len(block_ids) or len(asset_ids) != len(self.assets):
            raise ValueError("source_preparation_duplicate_identity")
        if any(not set(block.asset_ids) <= asset_ids for block in self.blocks):
            raise ValueError("source_preparation_asset_missing")
        indexes = {block_id: index for index, block_id in enumerate(block_ids)}
        cursor = 0
        seen = set()
        for part in self.parts:
            first, last = indexes.get(part.first_block), indexes.get(part.last_block)
            if first is None or first != cursor or last is None or last < first or part.id in seen:
                raise ValueError("source_preparation_partition_invalid")
            expected_id = "part-" + digest(self.original_blob_sha256 + part.first_block + part.last_block)[:24]
            if part.id != expected_id:
                raise ValueError("source_preparation_part_identity_invalid")
            seen.add(part.id)
            cursor = last + 1
        if cursor != len(self.blocks):
            raise ValueError("source_preparation_partition_incomplete")
        return self

    @property
    def sha256(self) -> str:
        return digest(json.dumps(self.model_dump(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))

    def selected(self, ids: list[str]) -> tuple[str, list[str], list[SourceBlock]]:
        if not ids or len(set(ids)) != len(ids) or not set(ids) <= {part.id for part in self.parts}:
            raise ValueError("source_preparation_selection_invalid")
        indexes = {block.id: i for i, block in enumerate(self.blocks)}
        selected_ids, blocks = [], []
        for part in self.parts:
            if part.id in ids:
                selected_ids.append(part.id)
                blocks.extend(self.blocks[indexes[part.first_block]:indexes[part.last_block] + 1])
        text = "\n\n".join(block.text for block in blocks if block.text.strip())
        if not text.strip() or len(text) > 1_000_000:
            raise ValueError("source_preparation_selected_text_invalid")
        return text, selected_ids, blocks

    def binding(self, ids: list[str]) -> dict[str, Any]:
        _, selected_ids, _ = self.selected(ids)
        return {"sha256": self.sha256, "manifest": self.model_dump(), "selected_part_ids": selected_ids}


def validate_binding(value: object, original_blob_sha256: str | None = None,
                     recognized_text: str | None = None) -> tuple[PreparedSource, list[str]]:
    if not isinstance(value, dict) or set(value) != {"sha256", "manifest", "selected_part_ids"}:
        raise ValueError("source_preparation_binding_invalid")
    package = PreparedSource.model_validate(value["manifest"])
    text, selected_ids, _ = package.selected(value["selected_part_ids"])
    if (value["sha256"] != package.sha256
            or original_blob_sha256 is not None and package.original_blob_sha256 != original_blob_sha256
            or recognized_text is not None and text != recognized_text):
        raise ValueError("source_preparation_binding_changed")
    return package, selected_ids
