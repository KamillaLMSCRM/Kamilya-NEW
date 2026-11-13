import asyncio
import json

from app.modules.ai.generation_checkpoint import AIGenerationCheckpointError


def jsonb_roundtrip(value):
    """Model JSON storage: object order changes, array order remains significant."""
    def ordered(item):
        if isinstance(item, dict):
            return {key: ordered(item[key]) for key in sorted(item, key=lambda key: (len(key.encode()), key.encode()))}
        if isinstance(item, list):
            return [ordered(child) for child in item]
        return item
    return ordered(json.loads(json.dumps(value, allow_nan=False)))


class Journal:
    tenant_id = "tenant-1"
    job_id = "job-1"

    def __init__(self):
        self.lock = asyncio.Lock()
        self.plans = {}
        self.values = {}
        self.repository = self
        self.fail_commit = False

    def _owned_key(self, key):
        return key

    def sessions(self):
        journal = self
        class Session:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_args):
                if journal.lock.locked():
                    journal.lock.release()
            async def commit(self):
                if journal.fail_commit:
                    raise TimeoutError("unknown")
        return Session()

    async def _lock_delivery(self, _session):
        await self.lock.acquire()

    async def load_plan(self, _session, *, tenant_id, generation_key):
        if generation_key not in self.plans:
            raise AIGenerationCheckpointError("generation_plan_not_found")
        return self.plans[generation_key]

    async def create_plan(self, _session, *, generation_key, plan_payload, **_kwargs):
        if generation_key in self.plans and self.plans[generation_key] != plan_payload:
            raise ValueError("plan_drift")
        self.plans[generation_key] = jsonb_roundtrip(plan_payload)

    async def read_owned_value_in_session(self, _session, key, expected):
        return self.values.get(key) if self.plans.get(key) == expected else None

    async def read_owned_value(self, key, expected):
        return await self.read_owned_value_in_session(None, key, expected)

    async def prepare(self, key, payload):
        if key in self.plans and self.plans[key] != payload:
            raise ValueError("plan_drift")
        self.plans[key] = jsonb_roundtrip(payload)
        return self.values.get(key)

    async def save_value(self, key, value):
        self.values[key] = jsonb_roundtrip(value)

    async def checkpoint_content(self, *_args, **_kwargs):
        pass

    async def checkpoint_review(self, *_args, **_kwargs):
        pass

    async def checkpoint_assessment(self, _session, *, generation_key, assessment_payload, **_kwargs):
        self.values[generation_key] = jsonb_roundtrip(assessment_payload)
