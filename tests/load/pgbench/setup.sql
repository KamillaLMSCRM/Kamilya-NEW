\set ON_ERROR_STOP on

DROP SCHEMA IF EXISTS loadtest CASCADE;
CREATE SCHEMA loadtest;

CREATE UNLOGGED TABLE loadtest.slots (
    slot integer PRIMARY KEY,
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    course_id uuid NOT NULL,
    lesson_id uuid NOT NULL
);

WITH selected_tenant AS (
    SELECT tenant_id
    FROM users
    WHERE tenant_id IS NOT NULL
    GROUP BY tenant_id
    ORDER BY count(*) DESC
    LIMIT 1
),
base AS MATERIALIZED (
    SELECT
        row_number() OVER (ORDER BY u.id, l.id)::integer AS rn,
        u.tenant_id,
        u.id AS user_id,
        e.course_id,
        l.id AS lesson_id
    FROM selected_tenant AS selected
    JOIN users AS u ON u.tenant_id = selected.tenant_id
    JOIN enrollments AS e
      ON e.tenant_id = u.tenant_id
     AND e.user_id = u.id
    JOIN modules AS m
      ON m.tenant_id = e.tenant_id
     AND m.course_id = e.course_id
    JOIN lessons AS l
      ON l.tenant_id = m.tenant_id
     AND l.module_id = m.id
),
slot_numbers AS (
    SELECT generate_series(1, 1000) AS slot
),
base_count AS (
    SELECT count(*)::integer AS value FROM base
)
INSERT INTO loadtest.slots (slot, tenant_id, user_id, course_id, lesson_id)
SELECT
    numbers.slot,
    base.tenant_id,
    base.user_id,
    base.course_id,
    base.lesson_id
FROM slot_numbers AS numbers
CROSS JOIN base_count
JOIN base ON base.rn = ((numbers.slot - 1) % base_count.value) + 1;

DO $$
BEGIN
    IF (SELECT count(*) FROM loadtest.slots) <> 1000 THEN
        RAISE EXCEPTION 'Load-test slot preparation failed';
    END IF;
END$$;

GRANT USAGE ON SCHEMA loadtest TO lms_app;
GRANT SELECT ON loadtest.slots TO lms_app;
