#!/usr/bin/env python3
"""Isolated DEV service-level proof of automated editorial receipt custody."""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_CHECKS = frozenset({
    'runtime_lms_app_force_rls_and_owned_schema',
    'clean_owned_completed_job_grants_content_acceptance_only',
    'no_role_or_publication_approval_derived',
    'forged_manifest_and_missing_receipt_denied',
    'foreign_tenant_and_foreign_job_denied',
    'source_and_content_edits_invalidate_receipt',
    'concurrent_official_course_edit_cannot_race_acceptance',
    'concurrent_source_update_cannot_race_acceptance',
    'history_retained_after_rejection',
    'owned_schema_cleanup_verified',
    'public_structure_counts_and_hashes_unchanged',
})


def assess(checks: dict[str, bool], *, executed: bool, cleanup_verified: bool, public_unchanged: bool) -> dict[str, Any]:
    """A dry run or missing/false evidence can never become a pass."""
    missing = sorted(name for name in REQUIRED_CHECKS if checks.get(name) is not True)
    passed = executed is True and cleanup_verified is True and public_unchanged is True and not missing
    return {'status': 'PASS' if passed else 'BLOCKED', 'executed': executed is True,
            'missing_checks': missing, 'cleanup_verified': cleanup_verified is True,
            'public_unchanged': public_unchanged is True}


def head() -> str:
    try:
        result = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True,
                                text=True, check=True, timeout=10)
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 'UNKNOWN'


def is_lock_timeout(exc: Exception) -> bool:
    original = getattr(exc, 'orig', None)
    return any(getattr(item, 'sqlstate', None) == '55P03' for item in
               (original, getattr(original, '__cause__', None)))


def canonical_env_file() -> Path:
    result = subprocess.run(['git','-C',str(ROOT),'rev-parse','--path-format=absolute','--git-common-dir'],
                            capture_output=True,text=True,check=True,timeout=10)
    return (Path(result.stdout.strip()).resolve().parent / '.env').resolve()


def source_hashes() -> dict[str, str]:
    paths = ('scripts/ops/autonomous_editorial_acceptance_dev_gate.py',
             'scripts/ops/course_uncertainty_dev_concurrency_gate.py',
             'apps/api/app/modules/courses/automated_editorial_acceptance.py',
             'apps/api/app/modules/courses/source_uncertainty.py',
             'apps/api/app/modules/courses/router.py',
             'apps/api/app/modules/lessons/service.py')
    return {path:hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths}


async def run_gate(owner_url: str, runtime_url: str, supabase_url: str) -> dict[str, Any]:
    """Use the canonical isolated schema; no API publication or external side effects."""
    from sqlalchemy import select, text
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.ext.asyncio import AsyncSession
    from fastapi import HTTPException
    from course_uncertainty_dev_concurrency_gate import (
        setup_schema, qschema, set_context, terminate_lingering_test_sessions,
        public_business_row_snapshot,
    )
    from source_actuality_dev_gate import public_snapshot
    from app.models.ai_job import AIJob
    from app.modules.courses.models import Course
    from app.modules.courses.automated_editorial_acceptance import bind_automated_acceptance, KEY
    from app.modules.courses.source_uncertainty import require_current_draft_review
    from app.modules.lessons.service import update_content_block

    schema = 'uncertainty_' + uuid4().hex[:12]
    owner = runtime = None
    created = False
    pids: set[int] = set()
    checks: dict[str, bool] = {}
    cleanup_verified = public_unchanged = False
    error = None
    initial_head = head()
    if re.fullmatch(r'[0-9a-f]{40}', initial_head) is None:
        raise ValueError('source_head_unavailable')
    initial_hashes = source_hashes()

    async def context(session: AsyncSession, tenant: Any) -> None:
        await set_context(session, schema, str(tenant), confirmed_pids=pids)
        await session.execute(text("SET LOCAL statement_timeout = '15s'"))
        await session.execute(text("SET LOCAL lock_timeout = '500ms'"))

    async def ai_public_snapshot(conn: Any) -> tuple[int, str]:
        row = (await conn.execute(text("SELECT count(*), coalesce(md5(string_agg(md5(row_to_json(t)::text), '' ORDER BY t.id)), 'empty') FROM public.ai_jobs t"))).one()
        return int(row[0]), str(row[1])

    try:
        owner, runtime, f, created, structure_before, public_before = await setup_schema(
            owner_url, runtime_url, supabase_url, schema, confirmed_pids=pids)
        async with owner.begin() as conn:
            ai_before = await ai_public_snapshot(conn)
            await conn.execute(text(f'CREATE TABLE {qschema(schema)}.ai_jobs (LIKE public.ai_jobs INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING INDEXES)'))
            await conn.execute(text(f'REVOKE ALL ON {qschema(schema)}.ai_jobs FROM PUBLIC, lms_app'))
            await conn.execute(text(f'GRANT SELECT,INSERT,UPDATE,DELETE ON {qschema(schema)}.ai_jobs TO lms_app'))
            await conn.execute(text(f'ALTER TABLE {qschema(schema)}.ai_jobs ENABLE ROW LEVEL SECURITY'))
            await conn.execute(text(f'ALTER TABLE {qschema(schema)}.ai_jobs FORCE ROW LEVEL SECURITY'))
            await conn.execute(text(f"CREATE POLICY acceptance_tenant_jobs ON {qschema(schema)}.ai_jobs FOR ALL TO lms_app USING (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid)"))
            policy = (await conn.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:schema AND c.relname='ai_jobs'"), {'schema':schema})).one()
            if tuple(policy) != (True, True): raise RuntimeError('jobs_rls_not_forced')
        tenant, foreign = f['tenant_a'], f['tenant_b']
        source_fp, draft_fp = 'a' * 64, 'b' * 64
        manifest = {'version':'p30-editorial-draft-v1','generation_status':'draft_prepared',
            'self_review_status':'passed','human_review_required':True,'content_review_required':False,
            'source_fingerprint':source_fp,'draft_fingerprint':draft_fp,'issues':[],'observations':[],
            'automated_acceptance':{'policy':'v3-practical-source-review-v33',
                'source_fingerprint':source_fp,'draft_fingerprint':draft_fp}}
        analysis = {'source_documents':[{'id':str(f['doc_a']),'revision':f['doc_rev_initial']}],
            'evidence_v3':{'v3_review_policy':'v3-practical-source-review-v33',
                'automated_review_passed':True,'requires_source_review':False,'quality_verdict':'verified',
                'draft_review':manifest}, 'resolutions_history':[{'marker':'synthetic-history-retained'}]}
        async with owner.begin() as conn:
            await conn.execute(text(f'UPDATE {qschema(schema)}.courses SET source_analysis=CAST(:a AS jsonb) WHERE id=:id'),
                               {'a':json.dumps(analysis), 'id':f['course_a']})
        job_id = 'synthetic-' + uuid4().hex
        async with AsyncSession(runtime,expire_on_commit=False) as db:
            await context(db,tenant)
            course = (await db.execute(select(Course).where(Course.id==f['course_a']).with_for_update())).scalar_one()
            job = AIJob(id=job_id,tenant_id=tenant,user_id=f['actor_a'],course_id=course.id,status='completed',stage='completed',progress=100,result={})
            db.add(job); await bind_automated_acceptance(db,course=course,job=job)
            owned_receipt = copy.deepcopy(job.result)
            await db.commit()
        checks['runtime_lms_app_force_rls_and_owned_schema'] = True

        async def guard(db: AsyncSession) -> Course:
            course = (await db.execute(select(Course).where(Course.id==f['course_a']).with_for_update())).scalar_one()
            await require_current_draft_review(db,course)
            return course

        async with AsyncSession(runtime,expire_on_commit=False) as db:
            await context(db,tenant); course = await guard(db)
            checks['clean_owned_completed_job_grants_content_acceptance_only'] = True
            checks['no_role_or_publication_approval_derived'] = course.status == 'draft' and course.review_status != 'approved'
            await db.rollback()
        async with AsyncSession(runtime,expire_on_commit=False) as db:
            await context(db,tenant)
            job = (await db.execute(select(AIJob).where(AIJob.id==job_id))).scalar_one()
            job.result = {}; await db.flush()
            try:
                await guard(db)
                raise AssertionError('forged_manifest_accepted')
            except HTTPException as exc:
                if exc.status_code != 409: raise
            checks['forged_manifest_and_missing_receipt_denied'] = True
            await db.rollback()
        async with AsyncSession(runtime,expire_on_commit=False) as db:
            await context(db,foreign)
            hidden_course = (await db.execute(select(Course).where(Course.id==f['course_a']))).scalar_one_or_none()
            hidden_job = (await db.execute(select(AIJob).where(AIJob.id==job_id))).scalar_one_or_none()
            if hidden_course is not None or hidden_job is not None: raise AssertionError('cross_tenant_visible')
            await db.rollback()
        # A foreign-tenant job naming this course must not serve as its receipt.
        async with owner.begin() as conn:
            await conn.execute(text(f"INSERT INTO {qschema(schema)}.ai_jobs(id,tenant_id,user_id,course_id,status,stage,progress,result) VALUES (:id,:tenant,:actor,:course,'completed','completed',100,CAST(:result AS jsonb))"),
                {'id':'foreign-'+uuid4().hex,'tenant':foreign,'actor':f['actor_b'],'course':f['course_a'],
                 'result':json.dumps(owned_receipt)})
        async with AsyncSession(runtime,expire_on_commit=False) as db:
            await context(db,tenant)
            job = (await db.execute(select(AIJob).where(AIJob.id==job_id))).scalar_one()
            job.result = {}; await db.flush()
            try:
                await guard(db); raise AssertionError('foreign_job_accepted')
            except HTTPException as exc:
                if exc.status_code != 409: raise
            checks['foreign_tenant_and_foreign_job_denied'] = True
            await db.rollback()

        # Exercise the same Course->Document lock ordering as the approval guard,
        # then challenge it using the real content-block service and document write.
        async with AsyncSession(runtime,expire_on_commit=False) as reader:
            await context(reader,tenant); await guard(reader)
            async with AsyncSession(runtime,expire_on_commit=False) as writer:
                await context(writer,tenant)
                try:
                    await update_content_block(writer,f['blk_1'],tenant,content='synthetic concurrent edit')
                    await writer.commit()
                    raise AssertionError('concurrent_edit_not_blocked')
                except DBAPIError as exc:
                    if not is_lock_timeout(exc): raise
                    await writer.rollback()
            checks['concurrent_official_course_edit_cannot_race_acceptance'] = True
            async with AsyncSession(runtime,expire_on_commit=False) as writer:
                await context(writer,tenant)
                try:
                    await writer.execute(text('UPDATE documents SET content_sha256=:sha WHERE id=:id'),{'sha':'e'*64,'id':f['doc_a']})
                    await writer.commit()
                    raise AssertionError('concurrent_source_update_not_blocked')
                except DBAPIError as exc:
                    if not is_lock_timeout(exc): raise
                    await writer.rollback()
            checks['concurrent_source_update_cannot_race_acceptance'] = True
            await reader.rollback()
        async with AsyncSession(runtime,expire_on_commit=False) as db:
            await context(db,tenant); await update_content_block(db,f['blk_1'],tenant,content='synthetic committed edit'); await db.commit()
        async with AsyncSession(runtime,expire_on_commit=False) as db:
            await context(db,tenant)
            try:
                await guard(db); raise AssertionError('stale_content_accepted')
            except HTTPException as exc:
                if exc.status_code != 409: raise
            course = (await db.execute(select(Course).where(Course.id==f['course_a']))).scalar_one()
            checks['history_retained_after_rejection'] = course.source_analysis.get('resolutions_history') == [{'marker':'synthetic-history-retained'}]
            await db.rollback()
        # Restore the original content, rebind a fresh receipt, then change only source revision.
        async with AsyncSession(runtime,expire_on_commit=False) as db:
            await context(db,tenant); await update_content_block(db,f['blk_1'],tenant,content='Initial content block in lesson 1')
            course = (await db.execute(select(Course).where(Course.id==f['course_a']).with_for_update())).scalar_one()
            job = (await db.execute(select(AIJob).where(AIJob.id==job_id))).scalar_one()
            await bind_automated_acceptance(db,course=course,job=job); await db.commit()
        async with AsyncSession(runtime,expire_on_commit=False) as db:
            await context(db,tenant); await db.execute(text('UPDATE documents SET content_sha256=:sha WHERE id=:id'),{'sha':'e'*64,'id':f['doc_a']}); await db.commit()
        async with AsyncSession(runtime,expire_on_commit=False) as db:
            await context(db,tenant)
            try:
                await guard(db); raise AssertionError('stale_source_accepted')
            except HTTPException as exc:
                if exc.status_code != 409: raise
            checks['source_and_content_edits_invalidate_receipt'] = True
            await db.rollback()
    except Exception as exc:
        error = type(exc).__name__
    finally:
        if runtime is not None: await runtime.dispose()
        if owner is not None:
            try:
                if pids: await terminate_lingering_test_sessions(owner,pids)
                if created:
                    async with owner.begin() as conn: await conn.execute(text(f'DROP SCHEMA IF EXISTS {qschema(schema)} CASCADE'))
                    async with owner.connect() as conn:
                        cleanup_verified = not await conn.scalar(text('SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=:name)'),{'name':schema})
                    async with owner.begin() as conn:
                        public_unchanged = (structure_before == await public_snapshot(conn) and
                            public_before == await public_business_row_snapshot(conn) and ai_before == await ai_public_snapshot(conn))
            except Exception as exc:
                error = error or type(exc).__name__
            finally: await owner.dispose()
    checks['owned_schema_cleanup_verified'] = cleanup_verified
    checks['public_structure_counts_and_hashes_unchanged'] = public_unchanged
    result = assess(checks,executed=True,cleanup_verified=cleanup_verified,public_unchanged=public_unchanged)
    result.update({'error_class':error,'schema':schema,'checks':checks,'head':head(),
        'timestamp_utc':datetime.now(timezone.utc).isoformat(), 'proof_scope':'isolated DEV service-level, not hosted API or publication',
        'remote_head':'NOT_VERIFIED_NO_GIT_NETWORK', 'source_sha256':initial_hashes,
        'provider_calls':0,'model_calls':0,'publication_calls':0})
    if head() != initial_head or source_hashes() != initial_hashes:
        result['status'] = 'BLOCKED'; result['error_class'] = 'source_identity_changed'
    if error: result['status'] = 'BLOCKED'
    receipt_dir = ROOT / '.release-evidence'; receipt_dir.mkdir(exist_ok=True)
    receipt = receipt_dir / f'autonomous-editorial-acceptance-{schema}.json'
    with receipt.open('x',encoding='utf-8') as out: json.dump(result,out,indent=2,sort_keys=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({'status':'READY_DRY_RUN','head':head(),'network_attempted':False,
            'required_checks':sorted(REQUIRED_CHECKS),'proof_scope':'isolated DEV service-level'}))
        return 0
    if args.env_file is None or not args.env_file.is_file():
        print(json.dumps({'status':'BLOCKED','reason':'canonical_env_file_required'})); return 1
    sys.path[:0] = [str(ROOT / 'scripts/ops'),str(ROOT / 'apps/api')]
    from dotenv import dotenv_values, load_dotenv
    from kb_rag_isolated_dev_gate import normalize_database_url
    try:
        if args.env_file.resolve() != canonical_env_file():
            raise ValueError('canonical_env_file_mismatch')
        values = dotenv_values(args.env_file)
        load_dotenv(args.env_file, override=True)
        result = asyncio.run(run_gate(normalize_database_url(values.get('MIGRATION_DATABASE_URL') or ''),
            normalize_database_url(values.get('DATABASE_URL') or ''),values.get('SUPABASE_URL') or ''))
        print(json.dumps(result,sort_keys=True)); return 0 if result['status'] == 'PASS' else 1
    except Exception as exc:
        print(json.dumps({'status':'BLOCKED','error_class':type(exc).__name__})); return 1


if __name__ == '__main__':
    raise SystemExit(main())
