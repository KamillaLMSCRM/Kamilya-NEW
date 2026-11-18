#!/usr/bin/env python3
"""0189 in one owned Supabase DEV schema; public source/course/audit rows untouched."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values, load_dotenv
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from editorial_revision_settings_dev_gate import ROOT, apply_migration
from kb_rag_isolated_dev_gate import GateBlocked, assert_sanitized_evidence, normalize_database_url, same_supabase_project
from runtime_settings_dev_gate import migration as base_migration, safe_schema
from source_actuality_dev_gate import public_snapshot, verify_runtime_role

SOURCE = ROOT / 'apps/api/alembic/versions/0189_literal_source_access_settings.py'
PRIOR = (ROOT / 'apps/api/alembic/versions/0186_source_preparation_settings.py',
         ROOT / 'apps/api/alembic/versions/0187_editorial_revision_settings.py')


async def run(owner_url, runtime_url, supabase_url):
    if not all(same_supabase_project(v, supabase_url) for v in (owner_url, runtime_url)):
        raise GateBlocked('canonical_supabase_dev_identity_mismatch')
    if (make_url(runtime_url).username or '').split('.')[0] != 'lms_app':
        raise GateBlocked('runtime_role_mismatch')
    schema = 'runtime_cfg_' + uuid4().hex[:12]
    qualified = safe_schema(schema)
    owner = create_async_engine(owner_url, poolclass=NullPool, hide_parameters=True)
    runtime = create_async_engine(runtime_url, poolclass=NullPool, hide_parameters=True)
    created = cleanup = neutral = False
    failure = before = None
    stage = 'preflight'
    checks = []
    actor = uuid4()
    source_hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (*PRIOR, SOURCE)}

    async def context(db, platform=False):
        await db.execute(text(f'SET LOCAL search_path TO {qualified},pg_catalog'))
        await db.execute(text("SELECT set_config('app.is_superadmin',:v,true),set_config('app.tenant_id','',true)"),
                         {'v': str(platform).lower()})
        for table in ('runtime_settings', 'runtime_settings_history', 'users'):
            actual = await db.scalar(text('SELECT n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.oid=to_regclass(:t)'), {'t':table})
            if actual != schema:
                raise GateBlocked('unsafe_public_table_resolution')

    async def custody(db):
        records = []
        for table, order in (('runtime_settings','id'), ('runtime_settings_history','revision')):
            records.append((await db.execute(text(f'SELECT row_to_json(t)::text FROM (SELECT * FROM {qualified}.{table} ORDER BY {order}) t'))).scalars().all())
        return hashlib.sha256(json.dumps(records).encode()).hexdigest()

    try:
        async with runtime.connect() as db:
            await verify_runtime_role(db)
        stage = 'owned_expand'
        async with owner.begin() as db:
            before = await public_snapshot(db)
            await db.execute(text(f'CREATE SCHEMA {qualified}'))
            created = True
            await db.execute(text(f'REVOKE ALL ON SCHEMA {qualified} FROM PUBLIC'))
            await db.execute(text(f'GRANT USAGE ON SCHEMA {qualified} TO lms_app'))
            await db.execute(text(f'CREATE TABLE {qualified}.users(id uuid PRIMARY KEY)'))
            await db.execute(text(f'INSERT INTO {qualified}.users(id) VALUES(:id)'), {'id':actor})
            await base_migration(db,schema)
            for source in PRIOR:
                await apply_migration(db,schema,source)
            baseline = await custody(db)
            await apply_migration(db,schema,SOURCE)
            await apply_migration(db,schema,SOURCE,downgrade=True)
            await apply_migration(db,schema,SOURCE)
            if await custody(db) != baseline:
                raise GateBlocked('migration_changed_settings_or_history')
            flags = (await db.execute(text("SELECT relrowsecurity,relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:s AND c.relname IN ('runtime_settings','runtime_settings_history')"), {'s':schema})).all()
            if len(flags)!=2 or any(tuple(x)!=(True,True) for x in flags):
                raise GateBlocked('force_rls_missing')
        checks += ['non_super_non_bypass_runtime','force_rls_preserved','upgrade_downgrade_reupgrade_no_data_change']
        stage = 'runtime_audit_and_validation'
        from app.models.registry import load_all_models
        from app.modules.admin.runtime_configuration.service import RuntimeSettingsService
        load_all_models()
        async with AsyncSession(runtime,expire_on_commit=False) as db:
            await context(db)
            changed = await db.execute(text('UPDATE runtime_settings SET revision=2 WHERE id=1'))
            if changed.rowcount != 0:
                raise GateBlocked('ordinary_runtime_write_permitted')
            await db.rollback()
            await context(db,True)
            result = await RuntimeSettingsService(db).update(revision=1,
                changes={'generation.reference_literal_chars':120000,'generation.reference_lookup_rounds':3},
                reason='Synthetic source access upper bounds',actor_id=actor)
            if result['revision']!=2:
                raise GateBlocked('audited_setting_update_failed')
            await context(db,True)
            history = await RuntimeSettingsService(db).history()
            if len(history)!=1 or history[0]['after']['generation.reference_literal_chars']!=120000:
                raise GateBlocked('new_settings_audit_missing')
            for key,bad in [('generation.reference_literal_chars',999),('generation.reference_literal_chars',120001),
                            ('generation.reference_literal_chars',True),('generation.reference_literal_chars',1000.5),
                            ('generation.reference_lookup_rounds',-1),('generation.reference_lookup_rounds',4),
                            ('generation.reference_lookup_rounds',None),('generation.reference_lookup_rounds','2')]:
                try:
                    async with db.begin_nested():
                        await db.execute(text('UPDATE runtime_settings SET overrides=CAST(:v AS jsonb) WHERE id=1'),{'v':json.dumps({key:bad})})
                except DBAPIError as exc:
                    if getattr(exc.orig,'sqlstate',None) not in {'23514','22P02'}:
                        raise
                else:
                    raise GateBlocked('raw_invalid_setting_accepted')
        stage = 'downgrade_guard'
        async with owner.begin() as db:
            prior = await custody(db)
            try:
                async with db.begin_nested():
                    await apply_migration(db,schema,SOURCE,downgrade=True)
            except DBAPIError as exc:
                if getattr(exc.orig,'sqlstate',None)!='23514':
                    raise
            else:
                raise GateBlocked('downgrade_erased_active_settings')
            if await custody(db)!=prior:
                raise GateBlocked('failed_downgrade_changed_audit')
        async with AsyncSession(runtime,expire_on_commit=False) as db:
            await context(db,True)
            await RuntimeSettingsService(db).update(revision=2,
                changes={'generation.reference_literal_chars':1000,'generation.reference_lookup_rounds':0},
                reason='Synthetic lower bounds',actor_id=actor)
            await context(db,True)
            await RuntimeSettingsService(db).revert(revision=3,target_revision=1,reason='Restore synthetic defaults',actor_id=actor)
        async with owner.begin() as db:
            prior=await custody(db)
            await apply_migration(db,schema,SOURCE,downgrade=True)
            await apply_migration(db,schema,SOURCE)
            if await custody(db)!=prior:
                raise GateBlocked('reupgrade_changed_audit')
        checks += ['ordinary_write_denied','audited_upper_and_lower_bounds','invalid_sql_rejected','active_override_downgrade_denied','revert_reupgrade_history_preserved']
    except Exception as exc:
        failure = str(exc) if isinstance(exc,GateBlocked) else type(exc).__name__
    finally:
        if created:
            try:
                async with owner.begin() as db:
                    await db.execute(text(f'DROP SCHEMA {qualified} CASCADE'))
                async with owner.connect() as db:
                    cleanup = not await db.scalar(text('SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:s)'),{'s':schema})
                    neutral = await public_snapshot(db)==before
            except Exception:
                cleanup=False
        await runtime.dispose()
        await owner.dispose()
    if any(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=sha for p,sha in source_hashes.items()):
        failure='migration_source_changed'
    return {'status':'PASS' if failure is None and cleanup and neutral else 'BLOCKED','stage':stage,'failure':failure,
        'scope':'owned_supabase_dev_literal_source_access0189','checks':checks,'cleanup':cleanup,
        'public_schema_neutral':neutral,'public_business_row_equivalence':'NOT_VERIFIED_NOT_WRITTEN',
        'public_migration':'NOT_RUN','production_actions':0,'source_hashes':source_hashes}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--env-file',type=Path,required=True)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args()
    if not args.execute:
        print(json.dumps({'status':'BLOCKED','reason':'execute_required'}))
        return 2
    config=dotenv_values(args.env_file)
    load_dotenv(args.env_file,override=True)
    try:
        result=asyncio.run(run(*(normalize_database_url(config.get(k)or'')for k in('MIGRATION_DATABASE_URL','DATABASE_URL')),config.get('SUPABASE_URL')or''))
    except Exception as exc:
        result={'status':'BLOCKED','failure':str(exc) if isinstance(exc,GateBlocked) else type(exc).__name__}
    assert_sanitized_evidence(result)
    args.evidence.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))
    return 0 if result['status']=='PASS'else 1


if __name__=='__main__':
    raise SystemExit(main())
