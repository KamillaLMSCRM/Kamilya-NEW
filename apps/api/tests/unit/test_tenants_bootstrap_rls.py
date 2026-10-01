"""Bootstrap seams, compatibility and migration contract; database-free."""

import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException

from app.models.tenants import Tenant
from app.modules.auth import service, telegram
from app.modules.tenants import bootstrap

ROOT = Path(__file__).resolve().parents[4]


def scalar(value):
    return SimpleNamespace(scalar_one_or_none=lambda: value, scalars=lambda: SimpleNamespace(all=lambda: value))


@pytest.fixture
def migration(monkeypatch):
    path = ROOT / "apps/api/alembic/versions/0172_tenants_scoped_bootstrap_rls.py"
    spec = importlib.util.spec_from_file_location("tenant_migration_contract", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module.op, "get_context", lambda: SimpleNamespace(opts={"version_table_schema": "tenants_123456789abc"})
    )
    return module


def test_full_migration_preserves_superadmin_and_never_broadens_runtime(migration, monkeypatch):
    sql = []
    monkeypatch.setattr(migration.op, "execute", sql.append)
    migration.upgrade()
    joined = "\n".join(sql)
    assert migration.revision == "0172" and migration.down_revision == "0171"
    assert 'ALTER TABLE "tenants_123456789abc".tenants FORCE ROW LEVEL SECURITY' in joined
    assert 'DROP POLICY IF EXISTS service_access ON "tenants_123456789abc".tenants' in joined
    assert "FOR ALL TO lms_app" in joined
    assert joined.count("id = NULLIF(current_setting('app.tenant_id', true), '')::uuid") == 2
    assert "tenants_superadmin_session" not in joined
    assert "DISABLE" not in joined and "BYPASSRLS" not in joined and "GRANT SELECT" not in joined
    assert joined.count("SECURITY DEFINER SET search_path = pg_catalog") == 2
    assert joined.count("FROM PUBLIC") == 2
    assert joined.count("GRANT EXECUTE") == 2
    assert "function_owner IN ('lms_app', 'public')" in joined
    assert "function_owner IS DISTINCT FROM other_owner" in joined
    assert "FOR SELECT TO %I USING (true)" in joined  # only resolved non-app owner
    assert "public.tenants" not in joined


def test_expand_only_installs_bounded_reads_but_does_not_claim_isolation(migration, monkeypatch):
    sql = []
    monkeypatch.setattr(migration.op, "execute", sql.append)
    migration.install_bootstrap()
    joined = "\n".join(sql)
    assert "RETURNS uuid" in joined and "RETURNS boolean" in joined
    assert "slug = requested_slug" in joined and "id = requested_id" in joined
    assert joined.count("NULLIF(current_setting('app.tenant_id', true), '') IS NULL") == 2
    assert joined.count("current_setting('app.is_superadmin', true) IS DISTINCT FROM 'true'") == 2
    assert "archived" in joined and "suspended" in joined
    assert "service_access" not in joined and "ALTER TABLE" not in joined
    assert "billing" not in joined and "settings" not in joined


@pytest.mark.parametrize("schema", ["public;DROP", 'x"', "../public"])
def test_unsafe_schema_and_downgrade_fail_before_sql(migration, monkeypatch, schema):
    monkeypatch.setattr(migration.op, "get_context", lambda: SimpleNamespace(opts={"version_table_schema": schema}))
    execute = MagicMock()
    monkeypatch.setattr(migration.op, "execute", execute)
    with pytest.raises(ValueError, match="Unsafe tenants schema"):
        migration.upgrade()
    execute.assert_not_called()
    with pytest.raises(RuntimeError, match="roll-forward only"):
        migration.downgrade()


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, uuid4()])
async def test_exact_slug_bound_without_commit_or_row_output(value):
    db = SimpleNamespace(execute=AsyncMock(return_value=scalar(value)), commit=AsyncMock())
    slug = "literal' OR true --"
    assert await bootstrap.lookup_tenant_id_by_slug(db, slug) == value
    sql, params = db.execute.await_args.args
    assert str(sql) == "SELECT lookup_tenant_id_by_slug(:slug)" and params == {"slug": slug}
    assert slug not in str(sql)
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_bootstrap_binds_exact_returned_id_before_tenant_orm_read():
    tenant_id = uuid4()
    row = Tenant(id=tenant_id, name="Synthetic", slug="synthetic")
    db = SimpleNamespace(execute=AsyncMock(side_effect=[scalar(tenant_id), None, scalar(row)]))
    assert await bootstrap.get_bootstrap_tenant(db, "synthetic") is row
    calls = db.execute.await_args_list
    assert str(calls[1].args[0]) == "SELECT set_current_tenant(:tid)"
    assert calls[1].args[1] == {"tid": str(tenant_id)}
    assert calls[2].args[0].compile().params == {"id_1": tenant_id}


@pytest.mark.asyncio
async def test_missing_slug_never_establishes_tenant_context():
    db = SimpleNamespace(execute=AsyncMock(return_value=scalar(None)))
    assert await bootstrap.get_bootstrap_tenant(db, "missing") is None
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_new_tenant_allocates_server_uuid_before_any_write():
    tenant = Tenant(name="Synthetic", slug="synthetic")
    db = SimpleNamespace(execute=AsyncMock(), add=MagicMock(), flush=AsyncMock(), commit=AsyncMock())
    await bootstrap.bind_new_tenant(db, tenant)
    assert isinstance(tenant.id, UUID)
    assert db.execute.await_args.args[1] == {"tid": str(tenant.id)}
    assert "true" in str(db.execute.await_args.args[0])
    db.add.assert_not_called()
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()
    with pytest.raises(ValueError, match="server allocated"):
        await bootstrap.bind_new_tenant(db, tenant)
    assert db.execute.await_count == 1


@pytest.fixture
def auth(monkeypatch):
    monkeypatch.setattr(service, "get_user_roles", AsyncMock(return_value=["methodologist"]))
    monkeypatch.setattr(service, "ph", SimpleNamespace(verify=MagicMock(return_value=True)))
    monkeypatch.setattr(service, "create_access_token", lambda payload: "synthetic-access")
    monkeypatch.setattr(service, "create_refresh_token", lambda payload: "synthetic-refresh")
    return SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), password_hash="synthetic", is_active=True, role="methodologist"
    )


@pytest.mark.asyncio
async def test_password_domain_select_is_scoped_before_user_query(auth):
    db = SimpleNamespace(execute=AsyncMock(side_effect=[scalar(auth.tenant_id), None, scalar(auth)]), flush=AsyncMock())
    assert (await service.authenticate_user(db, "synthetic@example.invalid", "synthetic"))[0] is auth
    calls = db.execute.await_args_list
    assert calls[0].args[1] == {"slug": "example.invalid"}
    assert calls[1].args[1] == {"tid": str(auth.tenant_id)}
    query = calls[2].args[0].compile()
    assert query.params["tenant_id_1"] == auth.tenant_id
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 1, 2])
async def test_legacy_password_preserves_unambiguous_match_and_scope_cleanup(auth, count):
    answers = [scalar(None), None, scalar([auth] * count), None]
    if count == 1:
        answers.append(None)
    db = SimpleNamespace(execute=AsyncMock(side_effect=answers), flush=AsyncMock())
    if count == 1:
        assert (await service.authenticate_user(db, "legacy@example.invalid", "synthetic"))[0] is auth
        assert db.execute.await_args_list[4].args[1] == {"tid": str(auth.tenant_id)}
    else:
        with pytest.raises(HTTPException) as error:
            await service.authenticate_user(db, "legacy@example.invalid", "synthetic")
        assert error.value.status_code == 401
        db.flush.assert_not_awaited()
    calls = db.execute.await_args_list
    query = str(calls[2].args[0])
    assert "tenant_login_eligible(users.tenant_id)" in query and "JOIN tenants" not in query
    assert "users.is_active IS true" in query
    assert str(calls[1].args[0]).endswith("'true', true)")
    assert str(calls[3].args[0]).endswith("'false', true)")


@pytest.mark.asyncio
async def test_wrong_password_and_inactive_domain_match_do_not_flush(auth):
    db = SimpleNamespace(execute=AsyncMock(side_effect=[scalar(auth.tenant_id), None, scalar(auth)]), flush=AsyncMock())
    service.ph.verify.side_effect = VerifyMismatchError("synthetic")
    with pytest.raises(HTTPException) as error:
        await service.authenticate_user(db, "qa@example.invalid", "wrong")
    assert error.value.status_code == 401
    db.flush.assert_not_awaited()
    service.ph.verify.side_effect = None
    auth.is_active = False
    db.execute.side_effect = [scalar(auth.tenant_id), None, scalar(auth)]
    with pytest.raises(HTTPException) as error:
        await service.authenticate_user(db, "qa@example.invalid", "synthetic")
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_lookup_sql_failure_propagates_for_request_rollback():
    db = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("synthetic failure")), commit=AsyncMock())
    with pytest.raises(RuntimeError, match="synthetic failure"):
        await bootstrap.get_bootstrap_tenant(db, "synthetic")
    assert db.execute.await_count == 1
    db.commit.assert_not_awaited()


@pytest.mark.parametrize(
    "path", ["app/modules/tenants/router.py", "app/modules/auth/telegram_register.py", "app/modules/auth/router.py"]
)
def test_each_public_creation_binds_before_its_add_and_flush(path):
    tree = ast.parse((ROOT / "apps/api" / path).read_text(encoding="utf-8"))
    creators = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            statements = list(ast.walk(node))
            creation = [
                part.lineno
                for part in statements
                if isinstance(part, ast.Assign)
                and isinstance(part.value, ast.Call)
                and isinstance(part.value.func, ast.Name)
                and part.value.func.id == "Tenant"
            ]
            if creation:
                binds = [
                    part.lineno
                    for part in statements
                    if isinstance(part, ast.Call)
                    and isinstance(part.func, ast.Name)
                    and part.func.id == "bind_new_tenant"
                ]
                adds = [
                    part.lineno
                    for part in statements
                    if isinstance(part, ast.Call)
                    and isinstance(part.func, ast.Attribute)
                    and part.func.attr == "add"
                    and part.args
                    and isinstance(part.args[0], ast.Name)
                    and part.args[0].id == "tenant"
                ]
                assert len(creation) == len(binds) == len(adds) == 1
                assert creation[0] < binds[0] < adds[0]
                creators.append(node.name)
    assert len(creators) == 1


@pytest.mark.asyncio
async def test_telegram_resolved_identity_binds_before_role_and_tenant_payload(monkeypatch):
    """Caller ordering only; initial User visibility under real RLS is not covered."""
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), role="student", first_name="Synthetic", last_name="User")
    tenant = SimpleNamespace(id=user.tenant_id, name="Synthetic", slug="synthetic", is_demo=False, plan="free")
    db = SimpleNamespace(execute=AsyncMock(side_effect=[scalar([user]), None, scalar("methodologist"), scalar(tenant)]))
    request = SimpleNamespace(
        headers={"X-Telegram-Bot-Api-Secret-Token": "synthetic"},
        json=AsyncMock(return_value={"message": {"text": "123456", "from": {"id": 123}, "chat": {"id": 123}}}),
    )
    monkeypatch.setattr(
        telegram, "settings", SimpleNamespace(TELEGRAM_BOT_TOKEN="synthetic", TELEGRAM_WEBHOOK_SECRET="synthetic")
    )
    monkeypatch.setattr(telegram, "send_telegram_message", AsyncMock())
    monkeypatch.setattr(telegram, "verify_code", AsyncMock(return_value=True))
    assert await telegram.handle_telegram_webhook(request, db) == {"ok": True}
    calls = db.execute.await_args_list
    assert "users.telegram_id" in str(calls[0].args[0])
    assert str(calls[1].args[0]) == "SELECT set_current_tenant(:tid)"
    assert calls[1].args[1] == {"tid": str(user.tenant_id)}
    assert "user_roles" in str(calls[2].args[0]) and "tenants" in str(calls[3].args[0])
    payload = telegram.verify_code.await_args.args[2]
    assert payload["tenant_id"] == user.tenant_id and payload["tenant"]["id"] == str(user.tenant_id)
    assert payload["role"] == "methodologist"
    telegram.send_telegram_message.assert_awaited_once()


@pytest.fixture
def dev_gate(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts/ops"))
    spec = importlib.util.spec_from_file_location("tenant_gate_contract", ROOT / "scripts/ops/tenants_rls_dev_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("schema", ["public", "tenants_", "tenants_123456789abc;DROP", "tenants_123456789abcd"])
def test_owned_dev_gate_rejects_nonexact_schema(dev_gate, schema):
    with pytest.raises(dev_gate.GateBlocked, match="unsafe_tenants_schema"):
        dev_gate.safe_schema(schema)
    assert dev_gate.safe_schema("tenants_123456789abc") == '"tenants_123456789abc"'


def test_owned_dev_gate_requires_execute_before_loading_credentials(dev_gate, monkeypatch, capsys):
    monkeypatch.setattr(dev_gate.sys, "argv", ["gate", "--env-file", "never-read.env"])
    dotenv = MagicMock(side_effect=AssertionError("credential read before execute"))
    monkeypatch.setattr(dev_gate, "dotenv_values", dotenv)
    assert dev_gate.main() == 2
    dotenv.assert_not_called()
    assert '"reason": "execute_required"' in capsys.readouterr().out


def test_owned_dev_gate_evidence_labels_pass_shared_sanitizer(dev_gate):
    tree = ast.parse((ROOT / "scripts/ops/tenants_rls_dev_gate.py").read_text(encoding="utf-8"))
    labels = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if "stage" in names and isinstance(node.value, ast.Constant):
                labels.append(node.value.value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "checks" and node.func.attr == "append":
                labels.append(ast.literal_eval(node.args[0]))
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id == "checks":
            labels.extend(ast.literal_eval(node.value))
    assert len(labels) >= 20
    dev_gate.assert_sanitized_evidence({"labels": labels})
