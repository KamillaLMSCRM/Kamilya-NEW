"""Custody and replay checks without generating another course."""
from hashlib import sha256
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.source_preparation.domain import POLICY, PreparedSource, SourceBlock, SourcePart, digest
from app.modules.source_preparation.extraction import NativeAsset, NativeBlock, NativeSource
from app.modules.source_preparation.lesson_assets import bind_lesson_assets
from app.modules.source_preparation.preparation import (
    VisualReading,
    VisualRequestRejected,
    _read_images,
    prepare_native_source,
)


async def accept_visual_proposal(messages):
    import json
    hints = json.loads(messages[1]["content"][0]["text"])
    return {"images": [hint["proposed_reading"] for hint in hints]}


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
                  preview_chars=600, visual_review_complete=accept_visual_proposal)
    package = await prepare_native_source(native, visual_complete=visual, retained={}, vision_batch_size=2, **kwargs)
    saved = {key: value for key, value in saved.items() if key.startswith((POLICY + ":image:", POLICY + ":reviewed-image:"))}
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
        vision_batch_size=2, preview_chars=600, visual_review_complete=accept_visual_proposal)
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
                  preview_chars=600, visual_review_complete=accept_visual_proposal)
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
async def test_completed_invalid_reply_gets_one_addressed_correction():
    asset, block = native_image()
    key = POLICY + ":visual:" + digest("e" * 64 + asset.asset_id)
    corrected = {"images": [{"id": asset.asset_id, "caption": "Page", "kind": "scan",
                              "text": "Actual source", "description": "Page", "uncertainties": []}]}
    call = AsyncMock(return_value=corrected)
    result = await _read_images(NativeSource((block,), (asset,), None, ()), original_sha256="e" * 64,
        visual_complete=call, checkpoint=AsyncMock(),
        retained={key + ":response": {"value": "{broken"}, key + ":intent": {"state": "started"}},
        vision_batch_size=4)
    assert result[asset.asset_id].text == "Actual source"
    assert call.await_count == 1
    messages = call.await_args.args[0]
    assert "untrusted" in messages[1]["content"][-1]["text"].lower()
    assert any(item.get("type") == "image_url" for item in messages[1]["content"])


def visual_row(asset, **changes):
    return {"id": asset.asset_id, "caption": "Page", "kind": "scan", "text": "Source",
            "description": "Page", "uncertainties": [], **changes}


@pytest.mark.asyncio
@pytest.mark.parametrize("is_review", [False, True])
async def test_rejected_batch_checkpoint_survives_interruption_and_regroups_safely(is_review):
    images = [native_image(i) for i in range(2)]
    native = NativeSource(tuple(b for _, b in images), tuple(a for a, _ in images), None, ())
    proposals = {asset.asset_id: VisualReading.model_validate(visual_row(asset)) for asset, _ in images} if is_review else None
    batch_prefix = POLICY + (":visual-review:" if is_review else ":visual:")
    image_prefix = POLICY + (":reviewed-image-intent:" if is_review else ":image-intent:")
    saved = {}
    async def checkpoint(key, value):
        saved[key] = value
        if key.startswith(batch_prefix) and key.endswith(":intent") and value.get("state") == "rejected":
            raise InterruptedError("after durable batch rejection before per-image updates")
    rejected = AsyncMock(side_effect=VisualRequestRejected("provider rejected"))
    with pytest.raises(InterruptedError):
        await _read_images(native, original_sha256="6" * 64, visual_complete=rejected,
                           checkpoint=checkpoint, retained={}, vision_batch_size=2, proposals=proposals)
    assert rejected.await_count == 1
    image_intents = [value for key, value in saved.items() if key.startswith(image_prefix)]
    assert len(image_intents) == 2 and all(value["state"] == "started" for value in image_intents)

    resumed = AsyncMock(side_effect=[{"images": [visual_row(asset)]} for asset, _ in images])
    result = await _read_images(native, original_sha256="6" * 64, visual_complete=resumed,
                                checkpoint=AsyncMock(), retained=saved, vision_batch_size=1, proposals=proposals)
    assert set(result) == {asset.asset_id for asset, _ in images}
    assert resumed.await_count == 2


@pytest.mark.asyncio
async def test_old_rejection_does_not_clear_a_later_different_started_batch():
    images = [native_image(i) for i in range(2)]
    native = NativeSource(tuple(b for _, b in images), tuple(a for a, _ in images), None, ())
    saved = {}
    async def checkpoint(key, value):
        saved[key] = value
    with pytest.raises(VisualRequestRejected):
        await _read_images(native, original_sha256="7" * 64,
            visual_complete=AsyncMock(side_effect=VisualRequestRejected("rejected")),
            checkpoint=checkpoint, retained={}, vision_batch_size=2)
    with pytest.raises(TimeoutError):
        await _read_images(native, original_sha256="7" * 64,
            visual_complete=AsyncMock(side_effect=TimeoutError("unknown")),
            checkpoint=checkpoint, retained=saved, vision_batch_size=1)
    no_post = AsyncMock(side_effect=AssertionError("unknown later request repeated"))
    with pytest.raises(ValueError, match="source_preparation_visual_outcome_unknown"):
        await _read_images(native, original_sha256="7" * 64, visual_complete=no_post,
                           checkpoint=checkpoint, retained=saved, vision_batch_size=2)
    no_post.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("linked_ids", [[{}], [1], [], ["duplicate", "duplicate"]])
async def test_malformed_rejection_linked_ids_fail_closed(linked_ids):
    asset, block = native_image()
    source_sha = "8" * 64
    batch = POLICY + ":visual:" + "a" * 64
    retained = {POLICY + ":image-intent:" + source_sha + ":" + asset.sha256:
                {"state": "started", "batch_key": batch},
                batch + ":intent": {"state": "rejected", "asset_ids": linked_ids,
                                    "original_sha256": source_sha}}
    no_post = AsyncMock(side_effect=AssertionError("invalid rejection was trusted"))
    with pytest.raises(ValueError, match="source_preparation_visual_outcome_unknown"):
        await _read_images(NativeSource((block,), (asset,), None, ()), original_sha256=source_sha,
                           visual_complete=no_post, checkpoint=AsyncMock(), retained=retained, vision_batch_size=1)
    no_post.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_reply", ["{broken", {"images": [{"id": "missing-fields"}]},
    {"images": [{"id": "asset-" + "f" * 64, "caption": "Page", "kind": "scan", "text": "Wrong",
                 "description": "Page", "uncertainties": []}]}])
async def test_one_recovery_post_and_invalid_second_response_stays_invalid(bad_reply):
    asset, block = native_image()
    saved = {}
    async def checkpoint(key, value):
        saved[key] = value
    call = AsyncMock(side_effect=[bad_reply, {"images": [visual_row(asset, kind="invalid")]}])
    kwargs = dict(native=NativeSource((block,), (asset,), None, ()), original_sha256="1" * 64,
                  visual_complete=call, checkpoint=checkpoint, vision_batch_size=1)
    with pytest.raises(ValueError, match="source_preparation_visual_response_invalid"):
        await _read_images(retained={}, **kwargs)
    assert call.await_count == 2
    assert sum(key.endswith(":schema-recovery:response") for key in saved) == 1
    no_post = AsyncMock(side_effect=AssertionError("Repeated correction"))
    with pytest.raises(ValueError, match="source_preparation_visual_response_invalid"):
        await _read_images(**{**kwargs, "visual_complete": no_post}, retained=saved)
    no_post.assert_not_called()


@pytest.mark.asyncio
async def test_recovery_uses_good_sibling_and_unknown_intent_blocks_repost():
    first, second = native_image(0), native_image(1)
    native = NativeSource((first[1], second[1]), (first[0], second[0]), None, ())
    source_sha = "2" * 64
    saved = {}
    async def checkpoint(key, value):
        saved[key] = value
    call = AsyncMock(side_effect=[{"images": [visual_row(first[0]), visual_row(second[0], kind="bad")]},
                                 TimeoutError("Unknown provider outcome")])
    with pytest.raises(TimeoutError):
        await _read_images(native, original_sha256=source_sha, visual_complete=call,
                           checkpoint=checkpoint, retained={}, vision_batch_size=2)
    no_post = AsyncMock(side_effect=AssertionError("Repeated unknown correction"))
    with pytest.raises(ValueError, match="source_preparation_visual_outcome_unknown"):
        await _read_images(native, original_sha256=source_sha, visual_complete=no_post,
                           checkpoint=checkpoint, retained=saved, vision_batch_size=1)
    no_post.assert_not_called()
    assert POLICY + ":image:" + source_sha + ":" + first[0].sha256 in saved


@pytest.mark.asyncio
async def test_recovery_response_survives_crash_and_regrouping():
    asset, block = native_image()
    native = NativeSource((block,), (asset,), None, ())
    saved = {}
    async def checkpoint(key, value):
        saved[key] = value
        if key.endswith(":schema-recovery:response"):
            raise InterruptedError("committed before process exit")
    call = AsyncMock(side_effect=["{bad", {"images": [visual_row(asset)]}])
    with pytest.raises(InterruptedError):
        await _read_images(native, original_sha256="3" * 64, visual_complete=call,
                           checkpoint=checkpoint, retained={}, vision_batch_size=2)
    no_post = AsyncMock(side_effect=AssertionError("Repeated correction"))
    result = await _read_images(native, original_sha256="3" * 64, visual_complete=no_post,
                                checkpoint=AsyncMock(), retained=saved, vision_batch_size=1)
    assert result[asset.asset_id].text == "Source"
    no_post.assert_not_called()


@pytest.mark.asyncio
async def test_verifier_wrapper_is_not_unwrapped_and_corrected_with_same_proposal_and_pixels():
    asset, block = native_image()
    proposal = VisualReading.model_validate(visual_row(asset))
    wrapper = {"images": [{"id": asset.asset_id, "page_scan": True,
                           "proposed_reading": proposal.model_dump()}]}
    saved = {}
    async def checkpoint(key, value):
        saved[key] = value
    call = AsyncMock(side_effect=[wrapper, {"images": [visual_row(asset, text="Corrected")]}])
    native = NativeSource((block,), (asset,), None, ())
    kwargs = dict(native=native, original_sha256="4" * 64, checkpoint=checkpoint,
                  vision_batch_size=1, proposals={asset.asset_id: proposal})
    result = await _read_images(visual_complete=call, retained={}, **kwargs)
    assert result[asset.asset_id].text == "Corrected" and call.await_count == 2
    correction = call.await_args.args[0]
    assert correction[0]["content"].startswith("[VISUAL_REVIEW_V1]")
    assert "do not nest" in correction[0]["content"]
    assert any(row.get("type") == "image_url" for row in correction[1]["content"])
    assert any("proposed_reading" in row.get("text", "") for row in correction[1]["content"])
    no_post = AsyncMock(side_effect=AssertionError("Repeated completed correction"))
    assert (await _read_images(visual_complete=no_post, retained=saved, **kwargs))[asset.asset_id].text == "Corrected"
    no_post.assert_not_called()


@pytest.mark.asyncio
async def test_valid_foreign_id_is_never_accepted_as_requested_image():
    asset, block = native_image()
    foreign, _ = native_image(1)
    call = AsyncMock(side_effect=[{"images": [visual_row(foreign)]}, {"images": [visual_row(foreign)]}])
    with pytest.raises(ValueError, match="source_preparation_visual_response_invalid"):
        await _read_images(NativeSource((block,), (asset,), None, ()), original_sha256="5" * 64,
                           visual_complete=call, checkpoint=AsyncMock(), retained={}, vision_batch_size=1)
    assert call.await_count == 2


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
        retained=retained, vision_batch_size=1, preview_chars=600, visual_review_complete=accept_visual_proposal)
    assert len(package.assets) == 3
    no_post.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_after", range(1, 8))
async def test_visual_verification_has_its_own_durable_replay_fence(stop_after):
    asset, block = native_image()
    source_sha = "b" * 64
    proposal = {"id": asset.asset_id, "caption": "Страница", "kind": "scan", "text": "Исходное правило.",
                "description": "Страница", "uncertainties": []}
    author_cache = {POLICY + ":image:" + source_sha + ":" + asset.sha256: proposal}
    retained = dict(author_cache)
    writes = 0

    async def checkpoint(key, value):
        nonlocal writes
        retained[key] = value
        writes += 1
        if writes == stop_after:
            raise InterruptedError("Simulated committed verification checkpoint")

    partition = AsyncMock(return_value={"parts": [{"title": "Порядок", "role": "learning", "reason": "Процедура",
        "first_block": block.block_id, "last_block": block.block_id}]})
    native = NativeSource((block,), (asset,), None, ())
    common = dict(original_sha256=source_sha, complete=partition,
                  persist_asset=AsyncMock(return_value="image.png"), vision_batch_size=2, preview_chars=600)
    author = AsyncMock(side_effect=AssertionError("Repeated author call"))
    review = AsyncMock(return_value={"images": [{**proposal, "text": "Исправленное полное правило."}]})
    try:
        await prepare_native_source(native, checkpoint=checkpoint, retained=author_cache,
            visual_complete=author, visual_review_complete=review, **common)
    except InterruptedError:
        pass
    no_review = AsyncMock(side_effect=AssertionError("Repeated verification call"))
    try:
        package = await prepare_native_source(native, checkpoint=AsyncMock(), retained=retained,
            visual_complete=author, visual_review_complete=no_review, **common)
        assert "Исправленное полное правило." in package.blocks[0].text
    except ValueError as error:
        assert str(error) == "source_preparation_visual_outcome_unknown"
    author.assert_not_called()
    no_review.assert_not_called()


@pytest.mark.asyncio
async def test_visual_editor_receives_pixels_and_proposal_and_correction_becomes_source():
    asset, block = native_image()
    proposal = {"id": asset.asset_id, "caption": "Правило", "kind": "scan",
        "text": "Основания: кодекс и внутренние правила.", "description": "Видимый текст", "uncertainties": []}
    captured = []

    async def review(messages):
        import json
        captured.append(messages)
        hints = json.loads(messages[1]["content"][0]["text"])
        assert hints[0]["proposed_reading"] == proposal
        assert any(row.get("type") == "image_url" for row in messages[1]["content"])
        return {"images": [{**proposal, "text": "Основания: кодекс, договор и внутренние правила."}]}

    package = await prepare_native_source(NativeSource((block,), (asset,), None, ()), original_sha256="c" * 64,
        complete=AsyncMock(return_value={"parts": [{"title": "Основания", "role": "learning", "reason": "Норма",
            "first_block": block.block_id, "last_block": block.block_id}]}),
        visual_complete=AsyncMock(return_value={"images": [proposal]}), visual_review_complete=review,
        checkpoint=AsyncMock(), persist_asset=AsyncMock(return_value="image.png"), retained={},
        vision_batch_size=2, preview_chars=600)
    assert "кодекс, договор и внутренние правила" in package.blocks[0].text
    assert len(captured) == 1
