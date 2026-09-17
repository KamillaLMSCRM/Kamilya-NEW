"""Expand organization units to a type-neutral hierarchy.

Revision ID: 0161
Revises: 0160

This is an expand migration.  ``departments`` remains the physical table for
legacy consumers; existing IDs, slugs, rules and root classifications are not
rewritten.  The downgrade is deliberately conservative and refuses to remove
any placement or nested/head-office data that the pre-v2 schema cannot express.
"""

import re

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0161"
down_revision = "0160"
branch_labels = None
depends_on = None

TENANT_EXPR = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
ALLOWED_UNIT_TYPES = (
    "organization",
    "branch",
    "management",
    "division",
    "department",
    "sector",
    "team",
    "other",
)


def _schema_name() -> str:
    schema = op.get_context().opts.get("version_table_schema") or "public"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Unsafe organization-hierarchy schema")
    return schema


def _table(schema: str, name: str) -> str:
    return f'"{schema}".{name}'


def _unit_trigger_sql(schema: str) -> tuple[str, str]:
    departments = _table(schema, "departments")
    users = _table(schema, "users")
    allowed = ", ".join(f"'{value}'" for value in ALLOWED_UNIT_TYPES)
    function_sql = f"""
    CREATE FUNCTION "{schema}".validate_organization_unit_v2()
    RETURNS trigger LANGUAGE plpgsql SET search_path="{schema}",pg_temp AS $$
    DECLARE
      parent_tenant uuid;
      parent_active boolean;
      head_tenant uuid;
      target_depth integer := 0;
      subtree_height integer := 0;
    BEGIN
      NEW.name := btrim(NEW.name);
      NEW.normalized_name := lower(regexp_replace(btrim(NEW.name), '\\s+', ' ', 'g'));
      NEW.external_key := NULLIF(btrim(NEW.external_key), '');

      IF NEW.unit_type NOT IN ({allowed}) THEN
        RAISE EXCEPTION 'organization unit type is not supported'
          USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.parent_id = NEW.id THEN
        RAISE EXCEPTION 'organization unit hierarchy cycle'
          USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.is_head_office AND NEW.parent_id IS NOT NULL THEN
        RAISE EXCEPTION 'head office must be a root organization unit'
          USING ERRCODE = 'check_violation';
      END IF;

      IF NEW.parent_id IS NOT NULL THEN
        SELECT tenant_id, is_active
          INTO parent_tenant, parent_active
          FROM {departments}
         WHERE id = NEW.parent_id;
        IF parent_tenant IS NULL OR parent_tenant <> NEW.tenant_id THEN
          RAISE EXCEPTION 'organization unit parent tenant mismatch'
            USING ERRCODE = 'foreign_key_violation';
        END IF;
        IF NOT parent_active THEN
          RAISE EXCEPTION 'organization unit parent is inactive'
            USING ERRCODE = 'check_violation';
        END IF;

        -- The recursive path is bounded by visited IDs, so a corrupt legacy
        -- cycle cannot make this trigger recurse forever during repair.
        IF EXISTS (
          WITH RECURSIVE ancestors(id, parent_id, depth, path) AS (
            SELECT id, parent_id, 1, ARRAY[id]
              FROM {departments}
             WHERE id = NEW.parent_id
            UNION ALL
            SELECT parent.id, parent.parent_id, a.depth + 1, a.path || parent.id
              FROM {departments} AS parent
              JOIN ancestors AS a ON parent.id = a.parent_id
             WHERE NOT parent.id = ANY(a.path)
          )
          SELECT 1 FROM ancestors
           WHERE id = NEW.id OR depth > 8
        ) THEN
          IF EXISTS (
            WITH RECURSIVE ancestors(id, parent_id, path) AS (
              SELECT id, parent_id, ARRAY[id]
                FROM {departments}
               WHERE id = NEW.parent_id
              UNION ALL
              SELECT parent.id, parent.parent_id, a.path || parent.id
                FROM {departments} AS parent
                JOIN ancestors AS a ON parent.id = a.parent_id
               WHERE NOT parent.id = ANY(a.path)
            )
            SELECT 1 FROM ancestors WHERE id = NEW.id
          ) THEN
            RAISE EXCEPTION 'organization unit hierarchy cycle'
              USING ERRCODE = 'check_violation';
          END IF;
          RAISE EXCEPTION 'organization unit hierarchy exceeds maximum depth of 8'
            USING ERRCODE = 'check_violation';
        END IF;

        WITH RECURSIVE parent_path(id, parent_id, path) AS (
          SELECT id, parent_id, ARRAY[id]
            FROM {departments}
           WHERE id = NEW.parent_id
          UNION ALL
          SELECT parent.id, parent.parent_id, p.path || parent.id
            FROM {departments} AS parent
            JOIN parent_path AS p ON parent.id = p.parent_id
           WHERE NOT parent.id = ANY(p.path)
        )
        SELECT count(*) INTO target_depth FROM parent_path;

        -- A move can keep the unit itself within the limit while pushing an
        -- existing descendant below it.  Enforce the complete resulting
        -- subtree depth at the database boundary, not only in the API.
        WITH RECURSIVE descendants(id, depth, path) AS (
          SELECT NEW.id, 0, ARRAY[NEW.id]
          UNION ALL
          SELECT child.id, d.depth + 1, d.path || child.id
            FROM {departments} AS child
            JOIN descendants AS d ON child.parent_id = d.id
           WHERE NOT child.id = ANY(d.path)
        )
        SELECT coalesce(max(depth), 0) INTO subtree_height FROM descendants;
        IF target_depth + subtree_height > 8 THEN
          RAISE EXCEPTION 'organization unit hierarchy exceeds maximum depth of 8'
            USING ERRCODE = 'check_violation';
        END IF;
      END IF;

      IF NEW.is_head_office AND NEW.is_active AND EXISTS (
        SELECT 1 FROM {departments}
         WHERE tenant_id = NEW.tenant_id
           AND is_head_office
           AND is_active
           AND id <> NEW.id
      ) THEN
        RAISE EXCEPTION 'tenant already has an active head office'
          USING ERRCODE = 'unique_violation';
      END IF;

      -- A tenant change on a referenced unit must not leave an existing child
      -- or employee placement pointing across tenants.
      IF TG_OP = 'UPDATE' AND NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
         AND (EXISTS (
           SELECT 1 FROM {departments}
            WHERE parent_id = NEW.id AND tenant_id <> NEW.tenant_id
         ) OR EXISTS (
           SELECT 1 FROM {users}
            WHERE organization_unit_id = NEW.id AND tenant_id <> NEW.tenant_id
         )) THEN
        RAISE EXCEPTION 'organization unit tenant change would break ownership'
          USING ERRCODE = 'foreign_key_violation';
      END IF;

      IF NEW.head_user_id IS NOT NULL THEN
        SELECT tenant_id INTO head_tenant FROM {users} WHERE id = NEW.head_user_id;
        IF head_tenant IS NULL OR head_tenant <> NEW.tenant_id THEN
          RAISE EXCEPTION 'organization unit head tenant mismatch'
            USING ERRCODE = 'foreign_key_violation';
        END IF;
      END IF;
      RETURN NEW;
    END $$;
    """
    trigger_sql = f"""
    CREATE TRIGGER trg_validate_organization_unit_v2
    BEFORE INSERT OR UPDATE ON {departments}
    FOR EACH ROW EXECUTE FUNCTION "{schema}".validate_organization_unit_v2();
    """
    return function_sql, trigger_sql


def _user_trigger_sql(schema: str) -> tuple[str, str]:
    departments = _table(schema, "departments")
    function_sql = f"""
    CREATE FUNCTION "{schema}".validate_user_organization_unit_ownership()
    RETURNS trigger LANGUAGE plpgsql SET search_path="{schema}",pg_temp AS $$
    DECLARE unit_tenant uuid;
    BEGIN
      IF NEW.organization_unit_id IS NOT NULL THEN
        SELECT tenant_id INTO unit_tenant
          FROM {departments}
         WHERE id = NEW.organization_unit_id;
        IF unit_tenant IS NULL OR NEW.tenant_id IS NULL OR unit_tenant <> NEW.tenant_id THEN
          RAISE EXCEPTION 'user organization unit tenant mismatch'
            USING ERRCODE = 'foreign_key_violation';
        END IF;
      END IF;
      RETURN NEW;
    END $$;
    """
    trigger_sql = f"""
    CREATE TRIGGER trg_validate_user_organization_unit_ownership
    BEFORE INSERT OR UPDATE OF tenant_id, organization_unit_id ON "{schema}".users
    FOR EACH ROW EXECUTE FUNCTION "{schema}".validate_user_organization_unit_ownership();
    """
    return function_sql, trigger_sql


def _legacy_unit_trigger_sql(schema: str) -> tuple[str, str]:
    departments = _table(schema, "departments")
    users = _table(schema, "users")
    function_sql = f"""
    CREATE FUNCTION "{schema}".validate_organization_unit_ownership()
    RETURNS trigger LANGUAGE plpgsql SET search_path="{schema}",pg_temp AS $$
    DECLARE
      parent_tenant uuid;
      parent_type text;
      parent_active boolean;
      head_tenant uuid;
    BEGIN
      NEW.name := btrim(NEW.name);
      NEW.normalized_name := lower(regexp_replace(btrim(NEW.name), '\\s+', ' ', 'g'));
      NEW.external_key := NULLIF(btrim(NEW.external_key), '');
      IF NEW.unit_type = 'branch' AND NEW.parent_id IS NOT NULL THEN
        RAISE EXCEPTION 'branch must be a root organization unit'
          USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.unit_type = 'department' AND NEW.parent_id IS NULL
         AND NOT NEW.legacy_root THEN
        RAISE EXCEPTION 'department requires a branch parent'
          USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.parent_id = NEW.id THEN
        RAISE EXCEPTION 'organization unit hierarchy cycle'
          USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.parent_id IS NOT NULL THEN
        SELECT tenant_id, unit_type, is_active
          INTO parent_tenant, parent_type, parent_active
          FROM {departments}
         WHERE id = NEW.parent_id;
        IF parent_tenant IS NULL OR parent_tenant <> NEW.tenant_id THEN
          RAISE EXCEPTION 'organization unit parent tenant mismatch'
            USING ERRCODE = 'foreign_key_violation';
        END IF;
        IF NEW.unit_type <> 'department' OR parent_type <> 'branch' OR NOT parent_active THEN
          RAISE EXCEPTION 'department parent must be an active branch'
            USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      IF NEW.head_user_id IS NOT NULL THEN
        SELECT tenant_id INTO head_tenant FROM {users} WHERE id = NEW.head_user_id;
        IF head_tenant IS NULL OR head_tenant <> NEW.tenant_id THEN
          RAISE EXCEPTION 'organization unit head tenant mismatch'
            USING ERRCODE = 'foreign_key_violation';
        END IF;
      END IF;
      RETURN NEW;
    END $$;
    """
    trigger_sql = f"""
    CREATE TRIGGER trg_validate_organization_unit_ownership
    BEFORE INSERT OR UPDATE ON {departments}
    FOR EACH ROW EXECUTE FUNCTION "{schema}".validate_organization_unit_ownership();
    """
    return function_sql, trigger_sql


def upgrade() -> None:
    schema = _schema_name()
    departments = _table(schema, "departments")
    users = _table(schema, "users")

    op.add_column(
        "departments",
        sa.Column("is_head_office", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema=schema,
    )
    op.add_column(
        "users",
        sa.Column("organization_unit_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=schema,
    )
    op.create_foreign_key(
        "fk_users_organization_unit_id",
        "users",
        "departments",
        ["organization_unit_id"],
        ["id"],
        source_schema=schema,
        referent_schema=schema,
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_users_tenant_organization_unit",
        "users",
        ["tenant_id", "organization_unit_id"],
        schema=schema,
    )
    op.create_index(
        "uq_departments_active_head_office",
        "departments",
        ["tenant_id"],
        unique=True,
        schema=schema,
        postgresql_where=sa.text("is_head_office AND is_active"),
    )

    # The old trigger/checks are the only restrictions that encode
    # branch->department. Remove them before installing the generic trigger.
    op.execute(f"ALTER TABLE {departments} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {users} NO FORCE ROW LEVEL SECURITY")
    for constraint in (
        "ck_departments_department_parent",
        "ck_departments_branch_root",
        "ck_departments_unit_type",
    ):
        op.execute(f"ALTER TABLE {departments} DROP CONSTRAINT IF EXISTS {constraint}")
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_validate_organization_unit_ownership ON {departments}"
    )
    op.execute(f'DROP FUNCTION IF EXISTS "{schema}".validate_organization_unit_ownership()')

    # Backfill only through the existing, exact position FK.  The legacy text
    # field is intentionally absent from this statement: ambiguous text never
    # becomes an employee placement, and no department is classified here.
    op.execute(
        f"""
        UPDATE {users} AS u
           SET organization_unit_id = p.department_id
          FROM {schema}.positions AS p
         WHERE u.position_id = p.id
           AND u.tenant_id IS NOT NULL
           AND p.department_id IS NOT NULL
           AND p.tenant_id = u.tenant_id
           AND EXISTS (
                 SELECT 1 FROM {departments} AS d
                  WHERE d.id = p.department_id
                    AND d.tenant_id = u.tenant_id
           )
        """
    )

    op.create_check_constraint(
        "ck_departments_unit_type_v2",
        "departments",
        "unit_type IN ('organization', 'branch', 'management', 'division', 'department', 'sector', 'team', 'other')",
        schema=schema,
    )
    op.create_check_constraint(
        "ck_departments_head_office_root",
        "departments",
        "NOT is_head_office OR parent_id IS NULL",
        schema=schema,
    )

    for statement in _unit_trigger_sql(schema):
        op.execute(statement)
    for statement in _user_trigger_sql(schema):
        op.execute(statement)

    op.execute(f"ALTER TABLE {departments} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {departments} FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {users} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {users} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {departments}")
    op.execute(f"DROP POLICY IF EXISTS tenant_organization_units_isolation ON {departments}")
    op.execute(
        f"CREATE POLICY tenant_organization_units_isolation ON {departments} "
        f"FOR ALL TO lms_app USING ({TENANT_EXPR}) WITH CHECK ({TENANT_EXPR})"
    )
    op.execute(f"REVOKE ALL ON TABLE {departments} FROM PUBLIC, lms_app")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {departments} TO lms_app")


def downgrade() -> None:
    schema = _schema_name()
    departments = _table(schema, "departments")
    users = _table(schema, "users")

    # Do not silently discard placement, arbitrary nesting, new types, or the
    # explicit head-office marker. The pre-v2 schema cannot represent any of
    # those values, so downgrade must be stopped before destructive DDL.
    op.execute(f"ALTER TABLE {departments} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {users} NO FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM {users} WHERE organization_unit_id IS NOT NULL)
             OR EXISTS (
               SELECT 1
                 FROM {departments} AS child
                 LEFT JOIN {departments} AS parent ON parent.id = child.parent_id
                WHERE child.is_head_office
                   OR child.unit_type NOT IN ('branch', 'department')
                   OR (
                     child.parent_id IS NOT NULL
                     AND NOT (
                       child.unit_type = 'department'
                       AND parent.unit_type = 'branch'
                       AND parent.parent_id IS NULL
                     )
                   )
             ) THEN
            RAISE EXCEPTION
              '0161 downgrade refused: v2-only organization placement or nested structure exists';
          END IF;
        END $$;
        """
    )

    op.execute(f"DROP TRIGGER IF EXISTS trg_validate_user_organization_unit_ownership ON {users}")
    op.execute(f'DROP FUNCTION IF EXISTS "{schema}".validate_user_organization_unit_ownership()')
    op.execute(f"DROP TRIGGER IF EXISTS trg_validate_organization_unit_v2 ON {departments}")
    op.execute(f'DROP FUNCTION IF EXISTS "{schema}".validate_organization_unit_v2()')
    op.execute(f"ALTER TABLE {departments} DROP CONSTRAINT IF EXISTS ck_departments_head_office_root")
    op.execute(f"ALTER TABLE {departments} DROP CONSTRAINT IF EXISTS ck_departments_unit_type_v2")

    op.create_check_constraint(
        "ck_departments_unit_type",
        "departments",
        "unit_type IN ('branch', 'department')",
        schema=schema,
    )
    for statement in _legacy_unit_trigger_sql(schema):
        op.execute(statement)
    op.create_check_constraint(
        "ck_departments_branch_root",
        "departments",
        "unit_type <> 'branch' OR parent_id IS NULL",
        schema=schema,
    )
    op.create_check_constraint(
        "ck_departments_department_parent",
        "departments",
        "unit_type <> 'department' OR parent_id IS NOT NULL OR legacy_root",
        schema=schema,
    )
    op.drop_index("uq_departments_active_head_office", table_name="departments", schema=schema)
    op.drop_index("ix_users_tenant_organization_unit", table_name="users", schema=schema)
    op.drop_constraint(
        "fk_users_organization_unit_id",
        "users",
        type_="foreignkey",
        schema=schema,
    )
    op.drop_column("users", "organization_unit_id", schema=schema)
    op.drop_column("departments", "is_head_office", schema=schema)

    op.execute(f"ALTER TABLE {departments} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {departments} FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {users} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {users} FORCE ROW LEVEL SECURITY")
