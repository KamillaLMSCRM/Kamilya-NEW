"""Real PostgreSQL checks for private durable lesson dialogue; fake provider only."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kb_rag_isolated_dev_gate import GateBlocked
from workbench_document_dev_gate import set_context


def tenant_fixture_sql(qualified_schema: str) -> str:
    """Anchor reused tenant binds as UUID before deriving synthetic slugs."""
    return (
        f"INSERT INTO {qualified_schema}.tenants"
        "(id,name,slug,status,plan,settings,is_demo,is_financial_organization) VALUES"
        "(CAST(:tenant AS uuid),'Dialogue synthetic',"
        "'dialogue-'||CAST(CAST(:tenant AS uuid) AS text),"
        "'trial','free','{}'::jsonb,false,false),"
        "(CAST(:foreign AS uuid),'Foreign synthetic',"
        "'dialogue-'||CAST(CAST(:foreign AS uuid) AS text),"
        "'trial','free','{}'::jsonb,false,false)"
    )


def _user(user_id: UUID, tenant_id: UUID, role: str = "methodologist") -> Any:
    return SimpleNamespace(id=user_id, tenant_id=tenant_id, role=role)


async def _expect_http(call: Any, status: int) -> HTTPException:
    try:
        await call
    except HTTPException as exc:
        if exc.status_code == status:
            return exc
        raise GateBlocked("unexpected_http_status") from None
    raise GateBlocked("expected_http_error_missing")


async def _insert_exchange(
    runtime_engine: Any,
    schema: str,
    context: Any,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    course_id: UUID,
    lesson_id: UUID,
    language: str = "ru",
    message: str = "Synthetic bounded question",
    reply: str = "Synthetic bounded answer",
    history_eligible: bool = True,
    exchange_id: UUID | None = None,
) -> UUID:
    exchange_id = exchange_id or uuid4()
    response = json.dumps(
        {
            "reply": reply,
            "history_eligible": history_eligible,
            "apply_lesson_id": None,
            "apply_lesson_content": None,
            "apply_lesson_title_hint": None,
            "audience_recommendation": None,
        }
    )
    async with runtime_engine.begin() as connection:
        await context(connection, schema, tenant_id, actor_id)
        await connection.execute(
            text(
                "INSERT INTO ai_lesson_dialogue_exchanges"
                "(id,tenant_id,actor_id,course_id,lesson_id,language,fingerprint,message,state) "
                "VALUES(:id,:tenant,:actor,:course,:lesson,:language,:fingerprint,:message,'pending')"
            ),
            {
                "id": exchange_id,
                "tenant": tenant_id,
                "actor": actor_id,
                "course": course_id,
                "lesson": lesson_id,
                "language": language,
                "fingerprint": exchange_id.hex * 2,
                "message": message,
            },
        )
        updated = await connection.execute(
            text(
                "UPDATE ai_lesson_dialogue_exchanges SET state='completed',"
                "response=CAST(:response AS jsonb) WHERE id=:id AND state='pending'"
            ),
            {"id": exchange_id, "response": response},
        )
        if updated.rowcount != 1:
            raise GateBlocked("synthetic_exchange_transition_failed")
    return exchange_id


async def _seed_fixture(owner_engine: Any, schema: str, context: Any) -> dict[str, UUID]:
    ids = {
        name: uuid4()
        for name in (
            "tenant",
            "foreign_tenant",
            "actor",
            "sibling",
            "foreign_actor",
            "course",
            "second_course",
            "foreign_course",
            "module",
            "second_module",
            "foreign_module",
            "lesson",
            "context_lesson",
            "paging_lesson",
            "move_lesson",
            "cascade_lesson",
            "purge_lesson",
            "race_lesson",
            "absent_lesson",
            "expired_lesson",
            "foreign_lesson",
        )
    }
    q = f'"{schema}"'
    async with owner_engine.begin() as connection:
        await context(connection, schema, ids["tenant"], ids["actor"])
        await connection.execute(
            text(tenant_fixture_sql(q)),
            {"tenant": ids["tenant"], "foreign": ids["foreign_tenant"]},
        )
        await connection.execute(
            text(
                f"INSERT INTO {q}.users(id,tenant_id,first_name,last_name,role,is_active,status) VALUES"
                "(:actor,:tenant,'Owner','Synthetic','methodologist',true,'active'),"
                "(:sibling,:tenant,'Sibling','Synthetic','methodologist',true,'active'),"
                "(:foreign_actor,:foreign,'Foreign','Synthetic','methodologist',true,'active')"
            ),
            {
                "actor": ids["actor"],
                "sibling": ids["sibling"],
                "foreign_actor": ids["foreign_actor"],
                "tenant": ids["tenant"],
                "foreign": ids["foreign_tenant"],
            },
        )
        await connection.execute(
            text(
                f"INSERT INTO {q}.user_roles(id,user_id,tenant_id,role) VALUES"
                "(:owner_role,:actor,:tenant,'methodologist'),"
                "(:sibling_role,:sibling,:tenant,'methodologist'),"
                "(:foreign_role,:foreign_actor,:foreign,'methodologist')"
            ),
            {
                "owner_role": uuid4(),
                "sibling_role": uuid4(),
                "foreign_role": uuid4(),
                "actor": ids["actor"],
                "sibling": ids["sibling"],
                "foreign_actor": ids["foreign_actor"],
                "tenant": ids["tenant"],
                "foreign": ids["foreign_tenant"],
            },
        )
        await connection.execute(
            text(
                f"INSERT INTO {q}.courses"
                "(id,tenant_id,title,description,status,delivery_type,ai_generated,"
                "source_document_ids,source_strategy,source_analysis,review_status) VALUES"
                "(:course,:tenant,'Dialogue course','','draft','native',false,"
                "'[]'::jsonb,'single_topic','{}'::jsonb,'pending'),"
                "(:second_course,:tenant,'Second dialogue course','','draft','native',false,"
                "'[]'::jsonb,'single_topic','{}'::jsonb,'pending'),"
                "(:foreign_course,:foreign,'Foreign course','','draft','native',false,"
                "'[]'::jsonb,'single_topic','{}'::jsonb,'pending')"
            ),
            {
                "course": ids["course"],
                "second_course": ids["second_course"],
                "foreign_course": ids["foreign_course"],
                "tenant": ids["tenant"],
                "foreign": ids["foreign_tenant"],
            },
        )
        await connection.execute(
            text(
                f"INSERT INTO {q}.modules"
                "(id,tenant_id,course_id,title,description,order_index,ai_generated) VALUES"
                "(:module,:tenant,:course,'Dialogue module','',0,false),"
                "(:second_module,:tenant,:second_course,'Second dialogue module','',0,false),"
                "(:foreign_module,:foreign,:foreign_course,'Foreign module','',0,false)"
            ),
            {
                "module": ids["module"],
                "second_module": ids["second_module"],
                "foreign_module": ids["foreign_module"],
                "course": ids["course"],
                "second_course": ids["second_course"],
                "foreign_course": ids["foreign_course"],
                "tenant": ids["tenant"],
                "foreign": ids["foreign_tenant"],
            },
        )
        local_lessons = (
            "lesson",
            "context_lesson",
            "paging_lesson",
            "move_lesson",
            "cascade_lesson",
            "purge_lesson",
            "race_lesson",
            "absent_lesson",
            "expired_lesson",
        )
        for index, key in enumerate(local_lessons):
            await connection.execute(
                text(
                    f"INSERT INTO {q}.lessons"
                    "(id,tenant_id,module_id,title,content_type,content,order_index,"
                    "ai_generated,source_document_ids,source_references,source_validation_status) "
                    "VALUES(:id,:tenant,:module,:title,'text','Synthetic lesson content',"
                    ":order_index,false,'[]'::jsonb,'[]'::jsonb,'not_applicable')"
                ),
                {
                    "id": ids[key],
                    "tenant": ids["tenant"],
                    "module": ids["module"],
                    "title": f"Synthetic {key}",
                    "order_index": index,
                },
            )
        await connection.execute(
            text(
                f"INSERT INTO {q}.lessons"
                "(id,tenant_id,module_id,title,content_type,content,order_index,"
                "ai_generated,source_document_ids,source_references,source_validation_status) "
                "VALUES(:id,:tenant,:module,'Foreign lesson','text','Foreign content',0,"
                "false,'[]'::jsonb,'[]'::jsonb,'not_applicable')"
            ),
            {
                "id": ids["foreign_lesson"],
                "tenant": ids["foreign_tenant"],
                "module": ids["foreign_module"],
            },
        )
    return ids


async def verify_dialogue(
    owner_engine: Any,
    runtime_engine: Any,
    schema: str,
    checks: list[str],
    *,
    runtime_connections: Any,
    migration: Any,
) -> None:
    from app.modules.ai import lesson_dialogue as service
    from app.modules.ai import router as ai_router
    from app.modules.ai.schemas import AIChatRequest, AIChatResponse
    from app.modules.admin.superadmin.service import (
        TENANT_DELETE_SQL,
        SuperadminService,
    )

    q = f'"{schema}"'
    context = set_context
    ids = await _seed_fixture(owner_engine, schema, context)
    actor = _user(ids["actor"], ids["tenant"])
    sibling = _user(ids["sibling"], ids["tenant"])
    foreign = _user(ids["foreign_actor"], ids["foreign_tenant"])

    async with owner_engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT c.relrowsecurity,c.relforcerowsecurity,"
                    "has_table_privilege('lms_app',c.oid,'SELECT,INSERT,UPDATE,DELETE'),"
                    "has_table_privilege('lms_app',c.oid,'TRUNCATE,REFERENCES,TRIGGER'),"
                    "EXISTS(SELECT 1 FROM aclexplode(COALESCE(c.relacl,acldefault('r',c.relowner))) a WHERE a.grantee=0) "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname=:schema AND c.relname='ai_lesson_dialogue_exchanges'"
                ),
                {"schema": schema},
            )
        ).one()
        policies = set(
            (
                await connection.execute(
                    text(
                        "SELECT policyname FROM pg_policies WHERE schemaname=:schema "
                        "AND tablename='ai_lesson_dialogue_exchanges'"
                    ),
                    {"schema": schema},
                )
            ).scalars()
        )
    if row != (True, True, True, False, False) or policies != {
        "lesson_dialogue_read",
        "lesson_dialogue_insert",
        "lesson_dialogue_update",
        "lesson_dialogue_purge",
    }:
        raise GateBlocked("dialogue_acl_rls_mismatch")
    checks.append("table_acl_force_rls")

    async with runtime_engine.connect() as connection:
        await context(connection, schema)
        if await connection.scalar(text("SELECT count(*) FROM ai_lesson_dialogue_exchanges")) != 0:
            raise GateBlocked("no_context_read_visible")
        try:
            async with connection.begin_nested():
                await connection.execute(
                    text(
                        "INSERT INTO ai_lesson_dialogue_exchanges"
                        "(id,tenant_id,actor_id,course_id,lesson_id,language,fingerprint,message,state) "
                        "VALUES(:id,:tenant,:actor,:course,:lesson,'ru',:fingerprint,'No context','pending')"
                    ),
                    {
                        "id": uuid4(),
                        "tenant": ids["tenant"],
                        "actor": ids["actor"],
                        "course": ids["course"],
                        "lesson": ids["lesson"],
                        "fingerprint": "a" * 64,
                    },
                )
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) != "42501":
                raise GateBlocked("no_context_wrong_sqlstate") from None
        else:
            raise GateBlocked("no_context_insert_accepted")
    checks.append("no_context_denied")

    provider_calls: list[AIChatRequest] = []
    provider_inferences = 0
    provider_release_observations: list[bool] = []
    async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
        await context(db, schema, ids["tenant"], ids["actor"])

        async def router_generate(model_request: AIChatRequest) -> AIChatResponse:
            provider_calls.append(model_request)
            return await ai_router._chat_once(
                model_request, db=db, user=actor, release_reads=True
            )

        class FakeLLM:
            async def ainvoke(self, _messages: Any) -> Any:
                nonlocal provider_inferences
                provider_release_observations.append(
                    not db.in_transaction() and runtime_connections() == 0
                )
                provider_inferences += 1
                return SimpleNamespace(content="Synthetic fake provider response")

        async def fake_factory(*_args: Any, **_kwargs: Any) -> FakeLLM:
            return FakeLLM()

        request = AIChatRequest(
            course_id=ids["course"],
            context="lesson",
            target_id=ids["lesson"],
            message="Explain the synthetic lesson",
            language="ru",
            durable_request_id=uuid4(),
        )
        with patch.object(
            ai_router.ResilientLLMClient, "from_settings_async", fake_factory
        ):
            first = await service.send_durable(request, db, actor, router_generate)
            replay = await service.send_durable(request, db, actor, router_generate)
            if first != replay or len(provider_calls) != 1 or provider_inferences != 1:
                raise GateBlocked("sequential_replay_failed")
            if provider_release_observations != [True]:
                raise GateBlocked("provider_connection_not_released")
            checks += [
                "provider_connection_released",
                "sequential_replay_one_fake_call",
            ]
            changed = request.model_copy(update={"message": "Changed synthetic body"})
            await _expect_http(
                service.send_durable(changed, db, actor, router_generate), 409
            )
            if len(provider_calls) != 1 or provider_inferences != 1:
                raise GateBlocked("changed_body_called_provider")
    checks.append("changed_body_conflict")

    async with runtime_engine.connect() as connection:
        for caller, expected in ((sibling, "sibling_actor_denied"), (foreign, "foreign_tenant_denied")):
            await context(connection, schema, caller.tenant_id, caller.id)
            visible = await connection.scalar(
                text("SELECT count(*) FROM ai_lesson_dialogue_exchanges WHERE id=:id"),
                {"id": request.durable_request_id},
            )
            if visible != 0:
                raise GateBlocked("private_exchange_visible")
            await connection.rollback()
            checks.append(expected)

    # The API wrapper must preserve actor, tenant and locale isolation.  The
    # same callers also cannot forge INSERT ownership or mutate the owner's row.
    async with owner_engine.connect() as connection:
        owner_row_before = (
            await connection.execute(
                text(f"SELECT * FROM {q}.ai_lesson_dialogue_exchanges WHERE id=:id"),
                {"id": request.durable_request_id},
            )
        ).mappings().one()
    forged_ids: list[UUID] = []
    for caller, check_name, expected_status in (
        (sibling, "sibling_api_private", None),
        (foreign, "foreign_api_private", 404),
    ):
        async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
            await context(db, schema, caller.tenant_id, caller.id)
            if expected_status is None:
                result = await ai_router.lesson_chat_history(
                    course_id=ids["course"],
                    lesson_id=ids["lesson"],
                    db=db,
                    user=caller,
                    language="ru",
                    before=None,
                )
                if (
                    result["exchanges"]
                    or result["pending_request_id"] is not None
                    or result["interrupted_request_id"] is not None
                ):
                    raise GateBlocked("sibling_api_history_visible")
            else:
                await _expect_http(
                    ai_router.lesson_chat_history(
                        course_id=ids["course"],
                        lesson_id=ids["lesson"],
                        db=db,
                        user=caller,
                        language="ru",
                        before=None,
                    ),
                    expected_status,
                )
        forged_id = uuid4()
        forged_ids.append(forged_id)
        async with runtime_engine.connect() as connection:
            await context(connection, schema, caller.tenant_id, caller.id)
            try:
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "INSERT INTO ai_lesson_dialogue_exchanges"
                            "(id,tenant_id,actor_id,course_id,lesson_id,language,"
                            "fingerprint,message,state) VALUES"
                            "(:id,:tenant,:actor,:course,:lesson,'ru',:fingerprint,"
                            "'Forged private write','pending')"
                        ),
                        {
                            "id": forged_id,
                            "tenant": ids["tenant"],
                            "actor": ids["actor"],
                            "course": ids["course"],
                            "lesson": ids["lesson"],
                            "fingerprint": forged_id.hex * 2,
                        },
                    )
            except DBAPIError as exc:
                if getattr(exc.orig, "sqlstate", None) != "42501":
                    raise GateBlocked("actor_private_insert_wrong_sqlstate") from None
            else:
                raise GateBlocked("actor_private_insert_accepted")
            updated = await connection.execute(
                text(
                    "UPDATE ai_lesson_dialogue_exchanges SET message='Forged update' "
                    "WHERE id=:id"
                ),
                {"id": request.durable_request_id},
            )
            if updated.rowcount != 0:
                raise GateBlocked("actor_private_update_visible")
        checks.append(check_name)
    async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
        await context(db, schema, ids["tenant"], ids["actor"])
        language_page = await ai_router.lesson_chat_history(
            course_id=ids["course"],
            lesson_id=ids["lesson"],
            db=db,
            user=actor,
            language="kk",
            before=None,
        )
    if (
        language_page["exchanges"]
        or language_page["pending_request_id"] is not None
        or language_page["interrupted_request_id"] is not None
    ):
        raise GateBlocked("different_language_history_visible")
    checks.append("different_language_api_empty")
    async with owner_engine.connect() as connection:
        owner_row_after = (
            await connection.execute(
                text(f"SELECT * FROM {q}.ai_lesson_dialogue_exchanges WHERE id=:id"),
                {"id": request.durable_request_id},
            )
        ).mappings().one()
        forged_count = await connection.scalar(
            text(
                f"SELECT count(*) FROM {q}.ai_lesson_dialogue_exchanges "
                "WHERE id IN (:sibling_id,:foreign_id)"
            ),
            {"sibling_id": forged_ids[0], "foreign_id": forged_ids[1]},
        )
    if owner_row_after != owner_row_before or forged_count != 0:
        raise GateBlocked("actor_private_row_changed")

    async with runtime_engine.connect() as connection:
        await context(connection, schema, ids["tenant"], ids["actor"])
        try:
            async with connection.begin_nested():
                await connection.execute(
                    text(
                        "UPDATE ai_lesson_dialogue_exchanges SET state='failed',"
                        "error_code='interrupted' WHERE id=:id"
                    ),
                    {"id": request.durable_request_id},
                )
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) != "23514":
                raise GateBlocked("terminal_immutability_wrong_sqlstate") from None
        else:
            raise GateBlocked("terminal_mutation_accepted")
    checks.append("terminal_immutable")

    # Revocation must hide already persisted content at the database boundary.
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(f"UPDATE {q}.users SET role='student' WHERE id=:actor"),
            {"actor": ids["actor"]},
        )
        await connection.execute(
            text(f"DELETE FROM {q}.user_roles WHERE user_id=:actor"),
            {"actor": ids["actor"]},
        )
    async with runtime_engine.connect() as connection:
        await context(connection, schema, ids["tenant"], ids["actor"])
        if await connection.scalar(text("SELECT count(*) FROM ai_lesson_dialogue_exchanges")) != 0:
            raise GateBlocked("revoked_dialogue_visible")
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(f"UPDATE {q}.users SET role='methodologist' WHERE id=:actor"),
            {"actor": ids["actor"]},
        )
        await connection.execute(
            text(
                f"INSERT INTO {q}.user_roles(id,user_id,tenant_id,role) "
                "VALUES(:id,:actor,:tenant,'methodologist')"
            ),
            {"id": uuid4(), "actor": ids["actor"], "tenant": ids["tenant"]},
        )
    checks.append("role_revocation_denied")

    # Course/lesson linkage is evaluated at mutation time, not trusted from IDs.
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(f"UPDATE {q}.lessons SET module_id=:module WHERE id=:lesson"),
            {"module": ids["foreign_module"], "lesson": ids["move_lesson"]},
        )
    moved_request = request.model_copy(
        update={"target_id": ids["move_lesson"], "durable_request_id": uuid4()}
    )
    async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
        await context(db, schema, ids["tenant"], ids["actor"])

        async def forbidden_moved_provider(_request: AIChatRequest) -> AIChatResponse:
            raise GateBlocked("moved_scope_called_provider")

        await _expect_http(
            service.send_durable(moved_request, db, actor, forbidden_moved_provider),
            404,
        )
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(f"UPDATE {q}.lessons SET module_id=:module WHERE id=:lesson"),
            {"module": ids["module"], "lesson": ids["move_lesson"]},
        )
    checks.append("moved_scope_refused")

    # A GET never receives a provider and therefore cannot infer.  Calls remain exact.
    calls_before_read = len(provider_calls)
    async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
        await context(db, schema, ids["tenant"], ids["actor"])
        page = await service.history_page(
            db, actor, ids["course"], ids["lesson"], "ru"
        )
    if len(page["exchanges"]) != 1 or len(provider_calls) != calls_before_read:
        raise GateBlocked("history_read_invoked_model_or_lost_row")
    checks.append("history_read_no_model")

    # The first concurrent owner reserves durably.  A peer conflicts without a
    # second callback, and a terminal closer wins over the late callback.
    concurrent_id = uuid4()
    concurrent_request = request.model_copy(
        update={"target_id": ids["purge_lesson"], "durable_request_id": concurrent_id}
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    concurrent_calls = 0

    async def first_sender() -> Any:
        nonlocal concurrent_calls
        async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
            await context(db, schema, ids["tenant"], ids["actor"])

            async def router_generate(model_request: AIChatRequest) -> AIChatResponse:
                return await ai_router._chat_once(
                    model_request, db=db, user=actor, release_reads=True
                )

            class WaitingLLM:
                async def ainvoke(self, _messages: Any) -> Any:
                    nonlocal concurrent_calls
                    provider_release_observations.append(
                        not db.in_transaction() and runtime_connections() == 0
                    )
                    concurrent_calls += 1
                    entered.set()
                    await release.wait()
                    return SimpleNamespace(content="Late synthetic result")

            async def waiting_factory(*_args: Any, **_kwargs: Any) -> WaitingLLM:
                return WaitingLLM()

            with patch.object(
                ai_router.ResilientLLMClient,
                "from_settings_async",
                waiting_factory,
            ):
                return await service.send_durable(
                    concurrent_request, db, actor, router_generate
                )

    task = asyncio.create_task(first_sender())
    await asyncio.wait_for(entered.wait(), timeout=30)
    async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
        await context(db, schema, ids["tenant"], ids["actor"])

        async def forbidden_provider(_request: AIChatRequest) -> AIChatResponse:
            raise GateBlocked("concurrent_peer_called_provider")

        await _expect_http(
            service.send_durable(concurrent_request, db, actor, forbidden_provider), 409
        )
    if concurrent_calls != 1:
        raise GateBlocked("concurrent_provider_count_mismatch")
    checks.append("concurrent_pending_dedup")
    async with owner_engine.begin() as connection:
        result = await connection.execute(
            text(
                f"UPDATE {q}.ai_lesson_dialogue_exchanges SET state='failed',"
                "error_code='interrupted' WHERE id=:id AND state='pending'"
            ),
            {"id": concurrent_id},
        )
        if result.rowcount != 1:
            raise GateBlocked("late_fixture_closure_failed")
    release.set()
    try:
        await task
    except HTTPException as exc:
        if exc.status_code != 409:
            raise GateBlocked("late_completion_wrong_status") from None
    else:
        raise GateBlocked("late_completion_accepted")
    async with owner_engine.connect() as connection:
        state = await connection.scalar(
            text(f"SELECT state FROM {q}.ai_lesson_dialogue_exchanges WHERE id=:id"),
            {"id": concurrent_id},
        )
    if state != "failed" or concurrent_calls != 1:
        raise GateBlocked("late_completion_changed_terminal")
    if not provider_release_observations[-1]:
        raise GateBlocked("provider_connection_not_released")
    checks.append("late_completion_refused")

    # Re-parenting a lesson to another course in the same tenant after model
    # inference starts must fail the final locked authorization and close the
    # owned reservation as interrupted, never archive the late result.
    race_request = request.model_copy(
        update={"target_id": ids["race_lesson"], "durable_request_id": uuid4()}
    )
    race_entered = asyncio.Event()
    race_release = asyncio.Event()
    race_provider_calls = 0

    async def race_sender() -> Any:
        nonlocal race_provider_calls
        async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
            await context(db, schema, ids["tenant"], ids["actor"])

            async def router_generate(model_request: AIChatRequest) -> AIChatResponse:
                return await ai_router._chat_once(
                    model_request, db=db, user=actor, release_reads=True
                )

            class RaceLLM:
                async def ainvoke(self, _messages: Any) -> Any:
                    nonlocal race_provider_calls
                    provider_release_observations.append(
                        not db.in_transaction() and runtime_connections() == 0
                    )
                    race_provider_calls += 1
                    race_entered.set()
                    await race_release.wait()
                    return SimpleNamespace(content="Race synthetic result")

            async def race_factory(*_args: Any, **_kwargs: Any) -> RaceLLM:
                return RaceLLM()

            with patch.object(
                ai_router.ResilientLLMClient,
                "from_settings_async",
                race_factory,
            ):
                return await service.send_durable(
                    race_request, db, actor, router_generate
                )

    race_task = asyncio.create_task(race_sender())
    await asyncio.wait_for(race_entered.wait(), timeout=30)
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(f"UPDATE {q}.lessons SET module_id=:module WHERE id=:lesson"),
            {"module": ids["second_module"], "lesson": ids["race_lesson"]},
        )
    race_release.set()
    try:
        await race_task
    except HTTPException as exc:
        if exc.status_code != 404:
            raise GateBlocked("same_tenant_move_wrong_status") from None
    else:
        raise GateBlocked("same_tenant_move_completed")
    async with owner_engine.connect() as connection:
        race_row = (
            await connection.execute(
                text(
                    f"SELECT state,error_code,response FROM {q}.ai_lesson_dialogue_exchanges "
                    "WHERE id=:id"
                ),
                {"id": race_request.durable_request_id},
            )
        ).one()
    if (
        race_provider_calls != 1
        or not provider_release_observations[-1]
        or race_row != ("failed", "interrupted", None)
    ):
        raise GateBlocked("same_tenant_move_not_interrupted")
    checks.append("same_tenant_move_interrupted")

    # A relation that disappears before the durable router reaches inference
    # must return 404 without constructing/calling even the fake provider.
    absent_request = request.model_copy(
        update={"target_id": ids["absent_lesson"], "durable_request_id": uuid4()}
    )
    absent_provider_calls = 0
    async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
        await context(db, schema, ids["tenant"], ids["actor"])

        class ForbiddenAbsentLLM:
            async def ainvoke(self, _messages: Any) -> Any:
                nonlocal absent_provider_calls
                absent_provider_calls += 1
                return SimpleNamespace(content="Forbidden absent result")

        async def absent_factory(*_args: Any, **_kwargs: Any) -> ForbiddenAbsentLLM:
            return ForbiddenAbsentLLM()

        async def move_then_generate(model_request: AIChatRequest) -> AIChatResponse:
            async with owner_engine.begin() as connection:
                await connection.execute(
                    text(f"UPDATE {q}.lessons SET module_id=:module WHERE id=:lesson"),
                    {
                        "module": ids["second_module"],
                        "lesson": ids["absent_lesson"],
                    },
                )
            return await ai_router._chat_once(
                model_request, db=db, user=actor, release_reads=True
            )

        with patch.object(
            ai_router.ResilientLLMClient,
            "from_settings_async",
            absent_factory,
        ):
            await _expect_http(
                service.send_durable(
                    absent_request, db, actor, move_then_generate
                ),
                404,
            )
    async with owner_engine.connect() as connection:
        absent_row = (
            await connection.execute(
                text(
                    f"SELECT state,error_code,response FROM {q}.ai_lesson_dialogue_exchanges "
                    "WHERE id=:id"
                ),
                {"id": absent_request.durable_request_id},
            )
        ).one()
    if absent_provider_calls != 0 or absent_row != ("failed", "interrupted", None):
        raise GateBlocked("absent_target_not_interrupted")
    checks.append("absent_target_interrupted_no_inference")

    # Insert through the real guard and preserve its database-owned timestamp.
    # Only the application clock used by this one GET is advanced; this is not
    # evidence that ten real minutes elapsed.
    expired_id = uuid4()
    async def dialogue_guard_enabled() -> bool:
        async with owner_engine.connect() as connection:
            return bool(
                await connection.scalar(
                    text(
                        "SELECT t.tgenabled='O' FROM pg_trigger t "
                        "JOIN pg_class c ON c.oid=t.tgrelid "
                        "JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname=:schema "
                        "AND c.relname='ai_lesson_dialogue_exchanges' "
                        "AND t.tgname='lesson_dialogue_guard'"
                    ),
                    {"schema": schema},
                )
            )

    if not await dialogue_guard_enabled():
        raise GateBlocked("dialogue_guard_not_enabled")
    async with runtime_engine.begin() as connection:
        await context(connection, schema, ids["tenant"], ids["actor"])
        await connection.execute(
            text(
                "INSERT INTO ai_lesson_dialogue_exchanges"
                "(id,tenant_id,actor_id,course_id,lesson_id,language,fingerprint,"
                "message,state) VALUES"
                "(:id,:tenant,:actor,:course,:lesson,'ru',:fingerprint,"
                "'Expired synthetic pending','pending')"
            ),
            {
                "id": expired_id,
                "tenant": ids["tenant"],
                "actor": ids["actor"],
                "course": ids["course"],
                "lesson": ids["expired_lesson"],
                "fingerprint": expired_id.hex * 2,
            },
        )
    async with owner_engine.connect() as connection:
        expired_created_at = await connection.scalar(
            text(
                f"SELECT created_at FROM {q}.ai_lesson_dialogue_exchanges "
                "WHERE id=:id"
            ),
            {"id": expired_id},
        )
    if not isinstance(expired_created_at, datetime):
        raise GateBlocked("expired_pending_timestamp_missing")
    fixed_now = (expired_created_at + timedelta(minutes=11)).astimezone(UTC)

    class FixedDialogueDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
        await context(db, schema, ids["tenant"], ids["actor"])
        with patch.object(service, "datetime", FixedDialogueDateTime):
            expired_page = await ai_router.lesson_chat_history(
                course_id=ids["course"],
                lesson_id=ids["expired_lesson"],
                db=db,
                user=actor,
                language="ru",
                before=None,
            )
    if (
        expired_page["exchanges"]
        or expired_page["pending_request_id"] is not None
        or expired_page["interrupted_request_id"] != expired_id
    ):
        raise GateBlocked("expired_pending_not_reported")
    if not await dialogue_guard_enabled():
        raise GateBlocked("dialogue_guard_changed_during_clock_probe")
    checks.append("expired_pending_get_interrupted")

    # Model admission: false is excluded, then newest four whole pairs are
    # reduced by the 32k code-point budget without splitting an exchange.
    for index in range(5):
        await _insert_exchange(
            runtime_engine,
            schema,
            context,
            tenant_id=ids["tenant"],
            actor_id=ids["actor"],
            course_id=ids["course"],
            lesson_id=ids["context_lesson"],
            message=f"eligible-{index}",
            reply=f"eligible-{index}-" + ("x" * 9000),
        )
    await _insert_exchange(
        runtime_engine,
        schema,
        context,
        tenant_id=ids["tenant"],
        actor_id=ids["actor"],
        course_id=ids["course"],
        lesson_id=ids["context_lesson"],
        message="excluded-refusal-marker",
        reply="excluded-refusal-marker",
        history_eligible=False,
    )
    captured: list[AIChatRequest] = []
    bounded_request = request.model_copy(
        update={"target_id": ids["context_lesson"], "durable_request_id": uuid4()}
    )
    async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
        await context(db, schema, ids["tenant"], ids["actor"])

        async def router_generate(model_request: AIChatRequest) -> AIChatResponse:
            captured.append(model_request)
            return await ai_router._chat_once(
                model_request, db=db, user=actor, release_reads=True
            )

        class CaptureLLM:
            async def ainvoke(self, _messages: Any) -> Any:
                provider_release_observations.append(
                    not db.in_transaction() and runtime_connections() == 0
                )
                return SimpleNamespace(content="Bounded context result")

        async def capture_factory(*_args: Any, **_kwargs: Any) -> CaptureLLM:
            return CaptureLLM()

        with patch.object(
            ai_router.ResilientLLMClient, "from_settings_async", capture_factory
        ):
            await service.send_durable(bounded_request, db, actor, router_generate)
    if not provider_release_observations[-1]:
        raise GateBlocked("provider_connection_not_released")
    history = captured[0].history if captured else None
    if history is None or len(history.turns) % 2 or len(history.turns) > 8:
        raise GateBlocked("bounded_history_shape_invalid")
    contents = [turn.content for turn in history.turns]
    if (
        any("excluded-refusal-marker" in item for item in contents)
        or sum(len(item) for item in contents) > 32000
        or len(history.turns) != 6
    ):
        raise GateBlocked("history_admission_invalid")
    checks.append("refusal_excluded_context_bounded")

    # Twenty-item page, stable cursor, no actor/language/scope bleed.
    paging_ids = []
    for index in range(22):
        paging_ids.append(
            await _insert_exchange(
                runtime_engine,
                schema,
                context,
                tenant_id=ids["tenant"],
                actor_id=ids["actor"],
                course_id=ids["course"],
                lesson_id=ids["paging_lesson"],
                message=f"page-{index}",
                reply=f"page-answer-{index}",
            )
        )
    await _insert_exchange(
        runtime_engine,
        schema,
        context,
        tenant_id=ids["tenant"],
        actor_id=ids["sibling"],
        course_id=ids["course"],
        lesson_id=ids["paging_lesson"],
        message="sibling-page-marker",
    )
    async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
        await context(db, schema, ids["tenant"], ids["actor"])
        first_page = await service.history_page(
            db, actor, ids["course"], ids["paging_lesson"], "ru"
        )
        second_page = await service.history_page(
            db,
            actor,
            ids["course"],
            ids["paging_lesson"],
            "ru",
            first_page["next_before"],
        )
    first_ids = {item["id"] for item in first_page["exchanges"]}
    second_ids = {item["id"] for item in second_page["exchanges"]}
    if (
        not first_page["has_more"]
        or first_page["next_before"] is None
        or len(first_ids) != 20
        or second_page["has_more"]
        or len(second_ids) != 2
        or first_ids & second_ids
        or first_ids | second_ids != set(paging_ids)
    ):
        raise GateBlocked("history_paging_invalid")
    checks.append("scoped_history_paging")

    cascade_id = await _insert_exchange(
        runtime_engine,
        schema,
        context,
        tenant_id=ids["tenant"],
        actor_id=ids["actor"],
        course_id=ids["course"],
        lesson_id=ids["cascade_lesson"],
    )
    async with owner_engine.begin() as connection:
        await connection.execute(
            text(f"DELETE FROM {q}.lessons WHERE id=:id"),
            {"id": ids["cascade_lesson"]},
        )
        remaining = await connection.scalar(
            text(f"SELECT count(*) FROM {q}.ai_lesson_dialogue_exchanges WHERE id=:id"),
            {"id": cascade_id},
        )
    if remaining != 0:
        raise GateBlocked("dialogue_fk_cascade_failed")
    checks.append("fk_cascade")

    purge_id = await _insert_exchange(
        runtime_engine,
        schema,
        context,
        tenant_id=ids["tenant"],
        actor_id=ids["actor"],
        course_id=ids["course"],
        lesson_id=ids["purge_lesson"],
    )
    foreign_id = await _insert_exchange(
        runtime_engine,
        schema,
        context,
        tenant_id=ids["foreign_tenant"],
        actor_id=ids["foreign_actor"],
        course_id=ids["foreign_course"],
        lesson_id=ids["foreign_lesson"],
        message="Foreign preserved marker",
        reply="Foreign preserved answer",
    )
    normalized_purge = [statement.strip() for statement in TENANT_DELETE_SQL]
    dialogue_statement = "DELETE FROM ai_lesson_dialogue_exchanges WHERE tenant_id = :tenant_id"
    lesson_statement = "DELETE FROM lessons WHERE tenant_id = :tenant_id"
    if (
        dialogue_statement not in normalized_purge
        or normalized_purge.index(dialogue_statement) + 1
        != normalized_purge.index(lesson_statement)
    ):
        raise GateBlocked("dialogue_purge_source_order_invalid")
    async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
        await context(db, schema, ids["tenant"], ids["actor"])
        discovered = [
            statement.strip()
            for statement in await SuperadminService(db)._tenant_delete_statements()
        ]
    if dialogue_statement not in discovered:
        raise GateBlocked("dialogue_purge_not_discovered")
    checks.append("purge_source_order")
    async with owner_engine.connect() as connection:
        foreign_before = (
            await connection.execute(
                text(f"SELECT * FROM {q}.ai_lesson_dialogue_exchanges WHERE id=:id"),
                {"id": foreign_id},
            )
        ).mappings().one()
    async with runtime_engine.begin() as connection:
        await context(connection, schema)
        no_context_delete = await connection.execute(
            text("DELETE FROM ai_lesson_dialogue_exchanges WHERE id=:id"),
            {"id": purge_id},
        )
    async with runtime_engine.begin() as connection:
        await context(connection, schema, ids["tenant"], ids["actor"])
        ordinary_delete = await connection.execute(
            text("DELETE FROM ai_lesson_dialogue_exchanges WHERE id=:id"),
            {"id": purge_id},
        )
    async with runtime_engine.begin() as connection:
        await context(connection, schema, ids["tenant"], ids["actor"])
        await connection.execute(text("SELECT set_config('app.is_superadmin','true',true)"))
        foreign_delete = await connection.execute(
            text("DELETE FROM ai_lesson_dialogue_exchanges WHERE id=:id"),
            {"id": foreign_id},
        )
        own_delete = await connection.execute(
            text("DELETE FROM ai_lesson_dialogue_exchanges WHERE id=:id"),
            {"id": purge_id},
        )
    async with owner_engine.connect() as connection:
        foreign_after = (
            await connection.execute(
                text(f"SELECT * FROM {q}.ai_lesson_dialogue_exchanges WHERE id=:id"),
                {"id": foreign_id},
            )
        ).mappings().one()
    if (
        no_context_delete.rowcount != 0
        or ordinary_delete.rowcount != 0
        or foreign_delete.rowcount != 0
        or own_delete.rowcount != 1
        or foreign_after != foreign_before
    ):
        raise GateBlocked("guarded_purge_scope_failed")
    checks.append("guarded_tenant_purge_visibility")

    async with owner_engine.connect() as connection:
        try:
            await migration(connection, schema, "downgrade")
        except RuntimeError:
            await connection.rollback()
        else:
            raise GateBlocked("populated_downgrade_accepted")
    checks.append("populated_downgrade_refused")
