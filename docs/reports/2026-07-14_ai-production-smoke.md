# Production AI Smoke Report

**Date:** 2026-07-14  
**Environment:** production API, Supabase Postgres, VPS Celery worker  
**Result:** passed after worker fixes

## Scope

The smoke test covered the first-tenant AI path end to end:

1. Temporary trial tenant and administrator creation.
2. Production health check and email/password login.
3. Job-description generation.
4. Quiz generation.
5. Document upload and embedding completion.
6. Course-generation job through Redis-compatible broker, Celery, LLM fallback, review, assessment, and database persistence.
7. Generated-course preview validation.

## Final result

The final run completed successfully:

- AI job reached `completed` at `100%`.
- Course was persisted with 1 module, 6 lessons, and 4 quizzes.
- Qwen was unavailable at `qwen.kml.kz` and returned Cloudflare `530`.
- DeepSeek fallback responded successfully and carried the generation pipeline.
- The embedding path completed successfully.

## Fixes applied during the smoke

### Provider configuration

The DeepSeek key existed locally under a lowercase variable name and the Celery worker had the canonical uppercase variable empty. The key was normalized to `DEEPSEEK_API_KEY` locally, on the VPS worker, and in Render without exposing its value.

### Worker dependency

The VPS virtual environment was missing the repository-declared `json-repair` dependency. It was installed from `apps/api/requirements.txt` and verified by import.

### SQLAlchemy metadata isolation

The Celery worker initialization reloaded `app.core.db` after disposing the engine. That created a second declarative `Base`, splitting model metadata and causing the generated-course save to fail on the `quizzes.lesson_id -> lessons.id` foreign key. The reload was removed; the inherited connection pool is disposed while the existing model registry remains intact.

## Remaining operational item

Qwen on the DGX/WireGuard path is still unavailable: the VPS cannot reach `10.66.66.7:8555` and the public endpoint returns Cloudflare `530`. DeepSeek currently provides the working fallback. The Qwen origin/tunnel should be restored separately before treating the primary provider as healthy.

