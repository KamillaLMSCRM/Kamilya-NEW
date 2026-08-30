# Authenticated question-assistant preview HTTP packet

## Scope

- Publish only `POST /api/v1/quizzes/{quiz_id}/questions/{question_id}/assistant/preview`.
- Enforce tenant entitlement and trial state through `get_current_active_user`, then derive tenant, authenticated actor, and effective role only from that server-side user.
- Reject tenantless and impersonated platform contexts during side-effect-free server-principal projection. Enforce persisted inactive/banned actor state exactly once inside `QuestionPreviewUseCase`, before context, persistence, preview claim, or provider resolution.
- Reuse the accepted preview use case, durable request/repository seams, coordinator, and provider-key-aware async chain.
- Add no apply endpoint, UI, migration, telemetry, deployment, or production change.

## Test seam

The public FastAPI route is the seam. Composition tests retain the real use case,
durable request service, and coordinator while replacing only bounded in-memory
persistence, context, and provider seams. Provider-key resolution is lazy and
occurs only after tenant access, actor authorization, context resolution, durable
request creation/reuse, and preview claim.

## Gates

1. Focused route and composition tests, including every typed error, active-tenant and persisted-account gates, replay, changed preview keys, lazy provider resolution, and authority-negative cases.
2. Existing editor-assistant use-case and schema regression tests.
3. Focused Ruff on changed Python files.
4. Established backend mypy command; report legacy/unrelated findings separately.
5. `graphify update .` after code changes.

## Exclusions

- No frontend or apply behavior.
- No database, network, Docker, provider, deploy, or production operation.
- No client-authored authority or impersonation support.
