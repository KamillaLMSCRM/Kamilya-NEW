\set slot random(1, 1000)

BEGIN;
SELECT set_current_tenant(slots.tenant_id)
FROM loadtest.slots AS slots
WHERE slots.slot = :slot;

SELECT count(*)
FROM enrollments AS enrollment
JOIN loadtest.slots AS slots
  ON slots.slot = :slot
 AND slots.user_id = enrollment.user_id
 AND slots.tenant_id = enrollment.tenant_id;

SELECT
    course.id,
    course.status,
    count(DISTINCT module.id) AS module_count,
    count(DISTINCT lesson.id) AS lesson_count
FROM loadtest.slots AS slots
JOIN courses AS course ON course.id = slots.course_id
LEFT JOIN modules AS module ON module.course_id = course.id
LEFT JOIN lessons AS lesson ON lesson.module_id = module.id
WHERE slots.slot = :slot
GROUP BY course.id, course.status;

SELECT
    count(*) AS touched_lessons,
    count(*) FILTER (WHERE progress.completed) AS completed_lessons
FROM progress
JOIN loadtest.slots AS slots
  ON slots.slot = :slot
 AND slots.user_id = progress.user_id
 AND slots.course_id = progress.course_id
 AND slots.tenant_id = progress.tenant_id;
COMMIT;
