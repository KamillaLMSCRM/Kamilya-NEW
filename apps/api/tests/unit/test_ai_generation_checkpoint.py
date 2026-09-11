import pytest

from app.modules.ai.generation_checkpoint import (
    AIGenerationCheckpointError,
    AIGenerationCheckpointRepository,
    AIGenerationIncompleteError,
    PlannedLesson,
)

TENANT_ID = "11111111-1111-1111-1111-111111111111"
RUN_ID = "22222222-2222-2222-2222-222222222222"


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def first(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class Session:
    def __init__(self):
        self.calls = []
        self.plan = None
        self.lessons = []
        self.source_job = True
        self.missing = []
        self.checkpoints = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}
        self.calls.append((sql, params))
        if "SELECT set_current_tenant" in sql:
            return Result()
        if "SELECT id FROM ai_jobs" in sql:
            return Result([(RUN_ID,)] if self.source_job else [])
        if "INSERT INTO ai_generation_runs" in sql:
            if self.plan is None:
                self.plan = {"id": RUN_ID, **params}
                return Result([(RUN_ID,)])
            return Result()
        if "INSERT INTO ai_generation_lesson_checkpoints" in sql:
            self.lessons.append(params.copy())
            return Result()
        if "FROM ai_generation_runs" in sql and "SELECT id, plan_revision" in sql:
            if self.plan is None:
                return Result()
            return Result([(RUN_ID, self.plan["plan_revision"], self.plan["source_job_id"], self.plan["plan_payload"])])
        if "FROM ai_generation_lesson_checkpoints" in sql and "SELECT module_key" in sql:
            return Result([(row["module_key"], row["lesson_key"], row["module_order"], row["lesson_order"]) for row in self.lessons])
        if "SELECT checkpoint.module_key" in sql and "checkpoint.content_payload" in sql:
            return Result(self.checkpoints)
        if "WITH candidate AS" in sql:
            return Result([("module-1", "lesson-1", 0, 0, 2)])
        if "RETURNING checkpoint.module_key" in sql:
            return Result([("module-1", "lesson-1", 0, 0, 2)])
        if "UPDATE ai_generation_lesson_checkpoints" in sql:
            return Result([(RUN_ID,)])
        if "JOIN ai_generation_runs" in sql:
            return Result(self.missing)
        raise AssertionError(sql)


def lessons():
    return (
        PlannedLesson("module-1", "lesson-1", 0, 0),
        PlannedLesson("module-1", "lesson-2", 0, 1),
    )


@pytest.mark.asyncio
async def test_create_and_load_plan_is_tenant_scoped_and_idempotent():
    session = Session()
    repository = AIGenerationCheckpointRepository()

    created = await repository.create_plan(
        session, tenant_id=TENANT_ID, generation_key="generation-1", plan_revision="plan-v1",
        source_job_id="job-1", plan_payload={"modules": []}, lessons=lessons(),
    )
    repeated = await repository.create_plan(
        session, tenant_id=TENANT_ID, generation_key="generation-1", plan_revision="plan-v1",
        source_job_id="job-1", plan_payload={"modules": []}, lessons=lessons(),
    )

    assert created == repeated
    assert created.lessons == lessons()
    tenant_contexts = [params for sql, params in session.calls if "set_current_tenant" in sql]
    assert tenant_contexts and all(item["tenant_id"] == TENANT_ID for item in tenant_contexts)
    assert any("ai_jobs WHERE id" in sql and "tenant_id" in sql for sql, _ in session.calls)


@pytest.mark.asyncio
async def test_create_plan_rejects_cross_tenant_or_conflicting_lineage():
    session = Session()
    session.source_job = False
    repository = AIGenerationCheckpointRepository()

    with pytest.raises(AIGenerationCheckpointError, match="source_job_not_found"):
        await repository.create_plan(
            session, tenant_id=TENANT_ID, generation_key="generation-1", plan_revision="plan-v1",
            source_job_id="job-1", plan_payload={}, lessons=(lessons()[0],),
        )


@pytest.mark.asyncio
async def test_create_plan_rejects_empty_lesson_plan_before_persistence():
    session = Session()
    with pytest.raises(AIGenerationCheckpointError, match="empty_generation_plan"):
        await AIGenerationCheckpointRepository().create_plan(
            session, tenant_id=TENANT_ID, generation_key="generation-1", plan_revision="plan-v1",
            source_job_id="job-1", plan_payload={}, lessons=(),
        )
    assert session.calls == []


@pytest.mark.asyncio
async def test_checkpoints_target_a_tenant_generation_and_missing_items_are_ordered():
    session = Session()
    session.missing = [("module-1", "lesson-1", 0, 0, "pending", "pending", "pending")]
    repository = AIGenerationCheckpointRepository()

    await repository.checkpoint_content(
        session, tenant_id=TENANT_ID, generation_key="generation-1", module_key="module-1",
        lesson_key="lesson-1", content_payload={"title": "Lesson"},
    )
    await repository.checkpoint_assessment(
        session, tenant_id=TENANT_ID, generation_key="generation-1", module_key="module-1",
        lesson_key="lesson-1", assessment_payload={"mcq": []},
    )
    await repository.checkpoint_review(
        session, tenant_id=TENANT_ID, generation_key="generation-1", module_key="module-1",
        lesson_key="lesson-1", review_payload={"quality_score": 9.0},
    )
    missing = await repository.enumerate_missing_items(session, tenant_id=TENANT_ID, generation_key="generation-1")

    assert [item.stage for item in missing] == ["content", "review", "assessment"]
    updates = [sql for sql, _ in session.calls if "UPDATE ai_generation_lesson_checkpoints" in sql]
    assert len(updates) == 3
    assert all("run.tenant_id = checkpoint.tenant_id" in sql for sql in updates)


@pytest.mark.asyncio
async def test_completed_checkpoint_accepts_identical_payload_but_rejects_replacement():
    class ConflictSession(Session):
        async def execute(self, statement, params=None):
            sql = str(statement)
            if "UPDATE ai_generation_lesson_checkpoints" in sql:
                self.calls.append((sql, params or {}))
                return Result()
            if "SELECT checkpoint.content_status" in sql:
                return Result([("completed", {"title": "first"})])
            return await super().execute(statement, params)

    session = ConflictSession()
    repository = AIGenerationCheckpointRepository()
    with pytest.raises(AIGenerationCheckpointError, match="content_checkpoint_conflict"):
        await repository.checkpoint_content(
            session, tenant_id=TENANT_ID, generation_key="generation-1", module_key="module-1",
            lesson_key="lesson-1", content_payload={"title": "second"},
        )

    normal = Session()
    await repository.checkpoint_content(
        normal, tenant_id=TENANT_ID, generation_key="generation-1", module_key="module-1",
        lesson_key="lesson-1", content_payload={"title": "same"},
    )
    sql = next(sql for sql, _ in normal.calls if "UPDATE ai_generation_lesson_checkpoints" in sql)
    assert "content_status <> 'completed'" in sql
    assert "content_payload = CAST(:payload AS jsonb)" in sql
    assert "lease_owner = NULL" in sql


@pytest.mark.asyncio
async def test_claim_missing_item_is_atomic_stage_scoped_and_recovers_expired_lease():
    session = Session()
    claimed = await AIGenerationCheckpointRepository().claim_missing_item(
        session, tenant_id=TENANT_ID, generation_key="generation-1", stage="assessment",
        lease_owner="worker-1", lease_duration_seconds=300,
    )

    assert claimed is not None
    assert (claimed.stage, claimed.lease_owner, claimed.attempt_count) == ("assessment", "worker-1", 2)
    sql = next(sql for sql, _ in session.calls if "WITH candidate AS" in sql)
    assert "checkpoint.assessment_status <> 'completed'" in sql
    assert "checkpoint.lease_expires_at <= now()" in sql
    assert "FOR UPDATE OF checkpoint SKIP LOCKED" in sql
    assert "attempt_count = checkpoint.attempt_count + 1" in sql
    assert "run.tenant_id = checkpoint.tenant_id" in sql


@pytest.mark.asyncio
async def test_claim_exact_item_is_stage_ordered_and_owner_scoped():
    session = Session()
    repository = AIGenerationCheckpointRepository()

    claimed = await repository.claim_item(
        session,
        tenant_id=TENANT_ID,
        generation_key="generation-1",
        module_key="module-1",
        lesson_key="lesson-1",
        stage="assessment",
        lease_owner="delivery-1",
    )

    assert claimed is not None
    sql = next(sql for sql, _ in session.calls if "RETURNING checkpoint.module_key" in sql)
    assert "checkpoint.assessment_status <> 'completed'" in sql
    assert "checkpoint.review_status = 'completed'" in sql
    assert "checkpoint.module_key = :module_key" in sql
    assert "checkpoint.lesson_key = :lesson_key" in sql
    assert "checkpoint.lease_expires_at <= now()" in sql


@pytest.mark.asyncio
async def test_release_leases_clears_only_the_current_delivery_owner():
    session = Session()
    await AIGenerationCheckpointRepository().release_leases(
        session,
        tenant_id=TENANT_ID,
        generation_key="generation-1",
        lease_owner="delivery-1",
    )

    sql, params = next(
        (sql, params)
        for sql, params in session.calls
        if "checkpoint.lease_owner = :lease_owner" in sql
        and "SET lease_owner = NULL" in sql
    )
    assert "run.generation_key = :generation_key" in sql
    assert params["lease_owner"] == "delivery-1"


@pytest.mark.asyncio
async def test_claim_rejects_unbounded_lease_or_unknown_stage():
    repository = AIGenerationCheckpointRepository()
    with pytest.raises(AIGenerationCheckpointError, match="invalid_lease_duration"):
        await repository.claim_missing_item(
            Session(), tenant_id=TENANT_ID, generation_key="generation-1", stage="content",
            lease_owner="worker-1", lease_duration_seconds=901,
        )
    with pytest.raises(AIGenerationCheckpointError, match="invalid_checkpoint_stage"):
        await repository.claim_missing_item(
            Session(), tenant_id=TENANT_ID, generation_key="generation-1", stage="both",
            lease_owner="worker-1",
        )


@pytest.mark.asyncio
async def test_load_checkpoints_is_ordered_tenant_scoped_and_decodes_completed_payloads():
    session = Session()
    session.checkpoints = [
        ("module-2", "lesson-1", 1, 0, "completed", "pending", "pending", '{"title":"Second"}', None, None),
        ("module-1", "lesson-2", 0, 1, "completed", "completed", "completed", {"title": "First"}, '{"quality_score":9}', '{"mcq":[]}'),
    ]
    snapshots = await AIGenerationCheckpointRepository().load_checkpoints(
        session, tenant_id=TENANT_ID, generation_key="generation-1"
    )

    assert [(item.module_key, item.lesson_key) for item in snapshots] == [
        ("module-2", "lesson-1"), ("module-1", "lesson-2"),
    ]
    assert snapshots[0].content_payload == {"title": "Second"}
    assert snapshots[0].assessment_payload is None
    assert snapshots[1].review_payload == {"quality_score": 9}
    assert snapshots[1].assessment_payload == {"mcq": []}
    sql = next(sql for sql, _ in session.calls if "SELECT checkpoint.module_key" in sql)
    assert "checkpoint.tenant_id = CAST(:tenant_id AS uuid)" in sql
    assert "run.tenant_id = checkpoint.tenant_id" in sql
    assert "run.generation_key = :generation_key" in sql
    assert "ORDER BY checkpoint.module_order ASC, checkpoint.lesson_order ASC" in sql


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("row", "error"),
    [
        (("module-1", "lesson-1", 0, 0, "completed", "pending", "pending", "not-json", None, None), "invalid_persisted_content_payload"),
        (("module-1", "lesson-1", 0, 0, "pending", "completed", "pending", None, "[]", None), "invalid_persisted_review_payload"),
        (("module-1", "lesson-1", 0, 0, "pending", "pending", "completed", None, None, "[]"), "invalid_persisted_assessment_payload"),
    ],
)
async def test_load_checkpoints_rejects_malformed_stored_payloads(row, error):
    session = Session()
    session.checkpoints = [row]
    with pytest.raises(AIGenerationCheckpointError, match=error):
        await AIGenerationCheckpointRepository().load_checkpoints(
            session, tenant_id=TENANT_ID, generation_key="generation-1"
        )


@pytest.mark.asyncio
async def test_completion_assertion_fails_until_every_stage_is_checkpointed():
    session = Session()
    session.missing = [("module-1", "lesson-1", 0, 0, "completed", "completed", "pending")]
    repository = AIGenerationCheckpointRepository()

    with pytest.raises(AIGenerationIncompleteError, match="generation_incomplete"):
        await repository.assert_complete(session, tenant_id=TENANT_ID, generation_key="generation-1")

    session.missing = []
    await repository.assert_complete(session, tenant_id=TENANT_ID, generation_key="generation-1")


def test_plan_keys_and_lesson_identity_are_bounded_before_persistence():
    repository = AIGenerationCheckpointRepository()
    session = Session()

    with pytest.raises(AIGenerationCheckpointError, match="invalid_generation_key"):
        import asyncio
        asyncio.run(repository.load_plan(session, tenant_id=TENANT_ID, generation_key=" " * 161))
    with pytest.raises(AIGenerationCheckpointError, match="duplicate_planned_lesson"):
        import asyncio
        asyncio.run(repository.create_plan(
            session, tenant_id=TENANT_ID, generation_key="generation-1", plan_revision="v1",
            source_job_id="job-1", plan_payload={}, lessons=(lessons()[0], lessons()[0]),
        ))
