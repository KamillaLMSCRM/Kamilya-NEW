"""Custody and replay checks without generating another course."""
from hashlib import sha256
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.source_preparation.domain import POLICY, PreparedSource, SourceBlock, SourcePart, digest
from app.modules.source_preparation.extraction import NativeAsset, NativeBlock, NativeSource
from app.modules.source_preparation.lesson_assets import bind_lesson_assets
from app.modules.source_preparation.preparation import prepare_native_source


def native_image(index=0, kind="image", text=""):
    data = f"validated-image-{index}".encode()
    sha = sha256(data).hexdigest()
    asset = NativeAsset("asset-" + sha, sha, "image/png", data, 10, 10, {"image": index})
    block = NativeBlock("block-" + digest(str(index))[:24], kind, text, (asset.asset_id,), 1, {})
    return asset, block


@pytest.mark.asyncio
async def test_individual_readings_survive_changed_batch_size_and_resume_without_paid_calls():
    images = [native_image(i) for i in range(3)]
    native = NativeSource(tuple(b for _, b in images), tuple(a for a, _ in images), None, ())
    saved = {}

    async def checkpoint(key, value):
        saved[key] = value

    async def visual(messages):
        ids = [row["text"].removeprefix("Image ID: ") for row in messages[1]["content"]
               if row.get("type") == "text" and row["text"].startswith("Image ID: ")]
        return {"images": [{"id": i, "caption": "ПКО", "kind": "form", "text": "Основание",
                            "description": "Поле основания", "uncertainties": []} for i in ids]}

    async def partition(messages):
        import json
        blocks = json.loads(messages[1]["content"])["blocks"]
        return {"parts": [{"title": "Касса", "role": "learning", "reason": "Порядок",
                           "first_block": blocks[0]["id"], "last_block": blocks[-1]["id"]}]}

    persist = AsyncMock(side_effect=lambda a: "source-assets/fixture/" + a.sha256 + ".png")
    kwargs = dict(original_sha256="a" * 64, complete=partition, checkpoint=checkpoint, persist_asset=persist,
                  preview_chars=600)
    package = await prepare_native_source(native, visual_complete=visual, retained={}, vision_batch_size=2, **kwargs)
    saved = {key: value for key, value in saved.items() if key.startswith(POLICY + ":image:")}
    no_post = AsyncMock(side_effect=AssertionError("Repeated paid reading"))
    replay = await prepare_native_source(native, visual_complete=no_post, retained=saved, vision_batch_size=1, **kwargs)
    assert replay == package
    no_post.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_visual_post_blocks_regrouped_retry_before_any_provider_call():
    asset, block = native_image()
    complete = AsyncMock()
    with pytest.raises(ValueError, match="source_preparation_visual_outcome_unknown"):
        await prepare_native_source(NativeSource((block,), (asset,), None, ()), original_sha256="b" * 64,
            complete=complete, visual_complete=complete, checkpoint=AsyncMock(), persist_asset=AsyncMock(),
            retained={POLICY + ":image-intent:" + "b" * 64 + ":" + asset.sha256: {"state": "started"}},
            vision_batch_size=4, preview_chars=600)
    complete.assert_not_called()


@pytest.mark.asyncio
async def test_pdf_header_plus_scan_retains_operational_image_transcription():
    asset, image_block = native_image()
    header = NativeBlock("block-" + "d" * 24, "page", "Страница 1", (), 1, {})
    cached = {POLICY + ":image:" + "c" * 64 + ":" + asset.sha256: {"id": asset.asset_id,
        "caption": "Страница", "kind": "scan", "text": "Кассир проверяет подпись до выдачи денег.",
        "description": "Скан", "uncertainties": []}}

    async def partition(messages):
        import json
        blocks = json.loads(messages[1]["content"])["blocks"]
        return {"parts": [{"title": "Выдача", "role": "learning", "reason": "Процедура",
                           "first_block": blocks[0]["id"], "last_block": blocks[-1]["id"]}]}

    package = await prepare_native_source(NativeSource((header, image_block), (asset,), 1, ()),
        original_sha256="c" * 64, complete=partition, visual_complete=AsyncMock(), checkpoint=AsyncMock(),
        persist_asset=AsyncMock(return_value="source-assets/fixture/image.png"), retained=cached,
        vision_batch_size=2, preview_chars=600)
    assert "проверяет подпись до выдачи" in package.selected([package.parts[0].id])[0]


def test_partition_cannot_drop_or_reorder_blocks_and_selection_is_source_order():
    blocks = [SourceBlock(id="block-" + digest(str(i))[:24], text=str(i), kind="text") for i in range(3)]
    parts = [SourcePart(id="part-" + digest("a" * 64 + b.id + b.id)[:24], title=b.text, role="learning",
                        reason="Chapter", first_block=b.id, last_block=b.id) for b in blocks]
    package = PreparedSource(original_blob_sha256="a" * 64, blocks=blocks, parts=parts)
    assert package.selected([parts[2].id, parts[0].id])[0] == "0\n\n2"
    with pytest.raises(ValueError, match="partition"):
        PreparedSource(original_blob_sha256="a" * 64, blocks=blocks, parts=parts[:2])


def test_lesson_images_bind_exact_frozen_asset_owner_and_reject_invented_id():
    course, lesson = uuid4(), uuid4()
    asset = "asset-" + "a" * 64
    inventory = {asset: {"id": asset, "document_id": str(uuid4())}}
    content, descriptors = bind_lesson_assets(f"Порядок\n![ПКО](source-asset:{asset})", inventory,
                                              course_id=course, lesson_id=lesson)
    assert f"/v1/courses/{course}/lessons/{lesson}/source-assets/{asset}" in content
    assert descriptors == [inventory[asset]]
    with pytest.raises(ValueError, match="unapproved"):
        bind_lesson_assets("![Other](source-asset:asset-" + "b" * 64 + ")", inventory,
                          course_id=course, lesson_id=lesson)


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_after", range(1, 8))
async def test_interruption_at_each_visual_checkpoint_never_repeats_the_post(stop_after):
    asset, block = native_image()
    native = NativeSource((block,), (asset,), None, ())
    retained = {}
    writes = 0

    async def checkpoint(key, value):
        nonlocal writes
        retained[key] = value
        writes += 1
        if writes == stop_after:
            raise InterruptedError("Simulated process exit after commit")

    visual = AsyncMock(return_value={"images": [{"id": asset.asset_id, "caption": "ПКО", "kind": "form",
        "text": "Основание", "description": "Поле основания", "uncertainties": []}]})
    partition = AsyncMock(return_value={"parts": [{"title": "Касса", "role": "learning", "reason": "Порядок",
                                                   "first_block": block.block_id, "last_block": block.block_id}]})
    common = dict(original_sha256="d" * 64, complete=partition, persist_asset=AsyncMock(return_value="image.png"),
                  preview_chars=600)
    try:
        await prepare_native_source(native, checkpoint=checkpoint, retained={}, visual_complete=visual,
                                    vision_batch_size=2, **common)
    except InterruptedError:
        pass
    no_post = AsyncMock(side_effect=AssertionError("Repeated POST"))
    try:
        await prepare_native_source(native, checkpoint=AsyncMock(), retained=retained, visual_complete=no_post,
                                    vision_batch_size=1, **common)
    except ValueError as error:
        assert str(error) == "source_preparation_visual_outcome_unknown"
    no_post.assert_not_called()


@pytest.mark.asyncio
async def test_completed_invalid_reply_remains_invalid_without_becoming_unknown_or_repeated():
    asset, block = native_image()
    key = POLICY + ":visual:" + digest("e" * 64 + asset.asset_id)
    no_post = AsyncMock()
    with pytest.raises(ValueError, match="source_preparation_visual_response_invalid"):
        await prepare_native_source(NativeSource((block,), (asset,), None, ()), original_sha256="e" * 64,
            complete=AsyncMock(), visual_complete=no_post, checkpoint=AsyncMock(), persist_asset=AsyncMock(),
            retained={key + ":response": {"value": "{broken"}, key + ":intent": {"state": "started"}},
            vision_batch_size=4, preview_chars=600)
    no_post.assert_not_called()


@pytest.mark.asyncio
async def test_noncontiguous_completed_batch_is_recovered_after_interruption():
    images = [native_image(i) for i in range(3)]
    native = NativeSource(tuple(b for _, b in images), tuple(a for a, _ in images), None, ())
    sha = "f" * 64
    def reading(asset):
        return {"id": asset.asset_id, "caption": "Экран", "kind": "screen", "text": "Сохранить",
                "description": "Кнопка сохранения", "uncertainties": []}
    selected = [images[0][0].asset_id, images[2][0].asset_id]
    key = POLICY + ":visual:" + digest(sha + ":".join(selected))
    retained = {POLICY + ":image:" + sha + ":" + images[1][0].sha256: reading(images[1][0]),
                key + ":response": {"original_sha256": sha, "asset_ids": selected,
                    "value": {"images": [reading(images[0][0]), reading(images[2][0])]}}}
    for asset in (images[0][0], images[2][0]):
        retained[POLICY + ":image-intent:" + sha + ":" + asset.sha256] = {"state": "started"}
    partition = AsyncMock(return_value={"parts": [{"title": "Сохранение", "role": "learning", "reason": "Порядок",
        "first_block": native.blocks[0].block_id, "last_block": native.blocks[-1].block_id}]})
    no_post = AsyncMock(side_effect=AssertionError("Repeated completed batch"))
    package = await prepare_native_source(native, original_sha256=sha, complete=partition,
        visual_complete=no_post, checkpoint=AsyncMock(), persist_asset=AsyncMock(return_value="image.png"),
        retained=retained, vision_batch_size=1, preview_chars=600)
    assert len(package.assets) == 3
    no_post.assert_not_called()
