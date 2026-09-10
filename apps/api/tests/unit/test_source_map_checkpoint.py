import asyncio
from uuid import uuid4

import pytest

from app.modules.ai.source_map_checkpoint import _WRITE_LUA, SourceMapCheckpointStore

TENANT_ID = "11111111-1111-1111-1111-111111111111"
JOB_ID = "22222222-2222-2222-2222-222222222222"
CONFIG_DIGEST = "a" * 64
BATCH_DIGEST = "b" * 64


class FakeRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, bytes]] = {}
        self.eval_calls: list[tuple[str, int, str, str, bytes, int, int]] = []
        self.closed = False

    async def hget(self, key: str, field: str):
        return self.hashes.get(key, {}).get(field)

    async def eval(
        self,
        script: str,
        numkeys: int,
        key: str,
        field: str,
        value: bytes,
        maximum: int,
        ttl: int,
    ):
        self.eval_calls.append((script, numkeys, key, field, value, maximum, ttl))
        values = self.hashes.setdefault(key, {})
        if field in values or len(values) < maximum:
            values[field] = value
            return 1
        return 0

    async def delete(self, *keys: str):
        for key in keys:
            self.hashes.pop(key, None)

    async def aclose(self):
        self.closed = True


def store(client: FakeRedis, **overrides) -> SourceMapCheckpointStore:
    return SourceMapCheckpointStore(
        overrides.get("tenant_id", TENANT_ID),
        overrides.get("job_id", JOB_ID),
        overrides.get("config_digest", CONFIG_DIGEST),
        client=client,
    )


@pytest.mark.asyncio
async def test_checkpoint_isolation_and_atomic_ttl_write():
    client = FakeRedis()
    primary = store(client)
    other_job = store(client, job_id="33333333-3333-3333-3333-333333333333")
    other_config = store(client, config_digest="c" * 64)

    await primary.save(BATCH_DIGEST, "validated map")

    assert await primary.load(BATCH_DIGEST) == "validated map"
    assert await other_job.load(BATCH_DIGEST) is None
    assert await other_config.load(BATCH_DIGEST) is None
    script, numkeys, _, _, _, maximum, ttl = client.eval_calls[-1]
    assert script == _WRITE_LUA
    assert numkeys == 1
    assert maximum == 64
    assert ttl == 3600
    assert len(client.hashes) == 1


@pytest.mark.asyncio
async def test_repeated_write_clear_and_injected_client_ownership():
    client = FakeRedis()
    checkpoint_store = store(client)

    await checkpoint_store.save(BATCH_DIGEST, "first")
    await checkpoint_store.save(BATCH_DIGEST, "second")
    assert await checkpoint_store.load(BATCH_DIGEST) == "second"

    await checkpoint_store.clear()
    assert await checkpoint_store.load(BATCH_DIGEST) is None
    assert client.hashes == {}
    await checkpoint_store.aclose()
    assert not client.closed


@pytest.mark.asyncio
async def test_corrupt_or_oversized_cached_values_are_safe_misses():
    client = FakeRedis()
    checkpoint_store = store(client)
    key = checkpoint_store._key()

    client.hashes[key] = {BATCH_DIGEST: b"wrong-digest\ncontent"}
    assert await checkpoint_store.load(BATCH_DIGEST) is None
    client.hashes[key][BATCH_DIGEST] = BATCH_DIGEST.encode() + b"\n" + (b"x" * (32 * 1024 + 1))
    assert await checkpoint_store.load(BATCH_DIGEST) is None


def same_old_slot_digests(count: int) -> list[str]:
    return [f"{index * 64:08x}" + ("d" * 56) for index in range(1, count + 1)]


@pytest.mark.asyncio
async def test_hash_retains_64_colliding_old_slots_and_rejects_only_65th_new_field():
    client = FakeRedis()
    checkpoint_store = store(client)
    digests = same_old_slot_digests(65)

    for index, digest in enumerate(digests[:64]):
        await checkpoint_store.save(digest, f"content-{index}")

    for index, digest in enumerate(digests[:64]):
        assert await checkpoint_store.load(digest) == f"content-{index}"
    assert len(client.hashes[checkpoint_store._key()]) == 64

    await checkpoint_store.save(digests[64], "declined")
    assert await checkpoint_store.load(digests[64]) is None
    assert len(client.hashes[checkpoint_store._key()]) == 64

    await checkpoint_store.save(digests[0], "updated")
    assert await checkpoint_store.load(digests[0]) == "updated"
    assert len(client.hashes[checkpoint_store._key()]) == 64


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tenant_id", str(uuid4()).upper()),
        ("job_id", "not-a-uuid"),
        ("config_digest", "A" * 64),
    ],
)
def test_constructor_rejects_unsafe_namespaces(field, value):
    kwargs = {field: value}
    with pytest.raises(ValueError):
        store(FakeRedis(), **kwargs)


@pytest.mark.asyncio
async def test_digest_and_content_bounds_are_enforced():
    checkpoint_store = store(FakeRedis())
    with pytest.raises(ValueError):
        await checkpoint_store.load("B" * 64)
    with pytest.raises(ValueError):
        await checkpoint_store.save(BATCH_DIGEST, "x" * (32 * 1024 + 1))


class FailingRedis(FakeRedis):
    async def hget(self, key: str, field: str):
        raise ConnectionError("unavailable")

    async def eval(self, *args):
        raise ConnectionError("unavailable")

    async def delete(self, *keys: str):
        raise ConnectionError("unavailable")


class BlockingRedis(FakeRedis):
    async def hget(self, key: str, field: str):
        await asyncio.sleep(10)


@pytest.mark.asyncio
async def test_outage_and_timeout_are_nonfatal_misses_or_noops():
    unavailable = store(FailingRedis())
    assert await unavailable.load(BATCH_DIGEST) is None
    await unavailable.save(BATCH_DIGEST, "content")
    await unavailable.clear()

    timed_out = store(BlockingRedis())
    assert await timed_out.load(BATCH_DIGEST) is None


@pytest.mark.asyncio
async def test_cancellation_propagates():
    checkpoint_store = store(BlockingRedis())
    task = asyncio.create_task(checkpoint_store.load(BATCH_DIGEST))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_one_cache_outage_does_not_add_a_timeout_for_every_batch():
    class CountingFailure(FailingRedis):
        calls = 0

        async def hget(self, *args):
            self.calls += 1
            raise ConnectionError("synthetic outage")

    client = CountingFailure()
    checkpoint_store = store(client)
    for _ in range(64):
        assert await checkpoint_store.load(BATCH_DIGEST) is None
        await checkpoint_store.save(BATCH_DIGEST, "synthetic")
    assert client.calls == 1
