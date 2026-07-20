\set slot random(1, 1000)

BEGIN;
SELECT set_current_tenant(slots.tenant_id)
FROM loadtest.slots AS slots
WHERE slots.slot = :slot;

INSERT INTO progress (
    id,
    tenant_id,
    user_id,
    course_id,
    lesson_id,
    completed,
    completion_percent,
    percent,
    completed_at,
    last_at
)
SELECT
    gen_random_uuid(),
    slots.tenant_id,
    slots.user_id,
    slots.course_id,
    slots.lesson_id,
    true,
    100,
    100,
    now(),
    now()
FROM loadtest.slots AS slots
WHERE slots.slot = :slot
ON CONFLICT (tenant_id, user_id, lesson_id)
DO UPDATE SET
    completed = true,
    completion_percent = 100,
    percent = 100,
    completed_at = COALESCE(progress.completed_at, now()),
    last_at = now();

SELECT count(*)
FROM progress
JOIN loadtest.slots AS slots
  ON slots.slot = :slot
 AND slots.user_id = progress.user_id
 AND slots.tenant_id = progress.tenant_id;
COMMIT;
