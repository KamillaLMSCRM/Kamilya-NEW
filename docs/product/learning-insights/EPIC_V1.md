# Learning insights: employee mistakes and course gaps

## Identity and authority

- Epic: LEARNING-INSIGHTS-01; Status: Accepted for implementation; document V1; template V2.
- Root owner: Kamilya Root Orchestrator, contracts, shared registration, migration, integration and acceptance.
- Product owner / Approved by: Kamilya owner, request “план реализации подробный и приступай”, 2026-09-06.
- Module owners: bounded backend worker (reporting), bounded frontend worker (methodologist workbench); root (schema and integration).
- Reviewer: independent read-only worker after implementation plus root evidence review.
- Change control: worker proposes evidence -> root reviews technical addendum -> product owner decides material scope changes; root may stop/cancel unsafe implementation. Accepted versions are immutable; extensions use versioned addenda.
- Supersedes: none. Scope of this decision is implementation and DEV verification; production publication is a later release gate.

## Outcome

A tenant methodologist can inspect the answers an employee got wrong, identify recurring question-level knowledge gaps, compare first and latest attempts, and record a follow-up decision without changing the original assessment evidence.

## Delivery sequence and acceptance

1. Reuse QuizAttempt.evidence_snapshot/evidence_sha256. Verify checksum, structural/identity consistency; never reconstruct historical answers from live question definitions.
2. Expose enrollment-scoped attempt history and question detail. Show selected/correct options, stored explanation, version, date, attempt order, and lesson link when source exists.
3. Expose course-level question statistics filtered by current employee department/position and completion date. Count unique employees per quiz/release/question version. Select first/latest completed quiz attempt over all history BEFORE period filtering on first completion. Latest comparison remains inside date_to when supplied. Label current organizational structure explicitly.
4. Add methodologist triage: unreviewed, train_staff, review_question, improve_material, resolved. Last-write-wins idempotent PUT; no free-form text or automatic messages/course mutation in V1.
5. Integrate within existing training log. Native enrollment rows offer “Разбор ответов”; course filter unlocks aggregate panel. Loading, empty, error/retry, incomplete-history and sample-size messages. RU/KK/EN strings.
6. Verify deterministic aggregation, HTTP roles/tenant boundaries, snapshot integrity, real PostgreSQL RLS and migration upgrade/downgrade/reupgrade in disposable Supabase DEV schema. Run frontend contract/render tests and typecheck plus affected journal regression; update AST Graphify once and compare dependency map.

## States and critical journeys

- Completed attempt -> verified snapshot -> question detail -> authorized triage -> reload persists triage.
- Missing/invalid snapshot -> explicit unavailable reason -> excluded from question metrics; no invented data.
- First failed + latest successful attempt from one employee -> first denominator 1, latest denominator 1, improved count 1.
- Another tenant/object, active admin or student -> 404/403 respectively with no evidence disclosure.
- More than 5,000 candidate completed attempts -> explicit 422 narrow-cohort error; never return silently truncated aggregate percentages.
- No course selected -> explanatory selection state, no aggregate API call.

## Module map and impact matrix

Training log UI -> Learning insights API -> existing QuizAttempt/Enrollment/Course/User/Position/Lesson/Module (read only).
Learning insights API -> LearningQuestionReview (sole annotation writer).
Root main router registration -> Learning insights router.

| Existing module | Class | Change | Preserved | Verification |
|---|---|---|---|---|
| quizzes | Consumer | Read immutable attempts only | grading, submission, attempts limit, learner answer exposure | snapshot and grading regressions |
| enrollments/courses/lessons | Consumer | verify ownership and resolve navigation/title | completion, release pinning, assignments | cross-tenant and missing source tests |
| users/positions | Consumer | current organizational cohort filters | role/session and staff data | tenant joins and filter tests |
| training log UI | Interface | inline analysis controls | CSV, evidence exports, journal filters/summary | journal regression + component tests |
| auth/main | Interface | register protected router using existing require_role | active-role checks and other routers | 401/403/404 tests |
| DB | Interface | additive annotation table, RLS, grants | no existing record/backfill/grading changes | isolated migration/RLS test |
| providers/workers/LLM | None | none | no network inference, sending or queues | no new imports/adapters |

Unlisted source changes require root addendum. Candidate assessment and SCORM internals are excluded: no per-question detail is invented for them. No new dashboard route, CSV export, automatic remedial assignment, ranking of employees, LLM analysis or punitive recommendation.

## Core mini-spec: reporting and triage (LI-API V1)

Responsibility: tenant-safe projections of immutable quiz evidence and unique-employee statistics. Stateless reporting; annotations are separate state. Non-responsibility: grading, evidence mutation, employee delivery, rewriting source material.

External interface (all below /api/v1/admin/learning-insights, require_role(methodologist, superadmin), tenant required; absent tenant -> 403):

- GET /enrollments/{enrollment_id}: {enrollment_id,user_name,course_id,course_title,attempts:AttemptDetail[]} ordered completed_at,id ascending; bounded 500 attempts, explicit 422 on overflow.
- GET /courses/{course_id}?department_id=&position_id=&date_from=&date_to=: CourseInsights; UUID query validation and aware ISO date validation; reversed range ->422.
- PUT /attempts/{attempt_id}/questions/{question_id}/review body {status:ReviewStatus}: Review. Verify same-tenant enrollment/course/attempt, valid snapshot and question membership; server derives key. 404 for unknown/foreign objects; 409 unavailable snapshot.

JSON contracts (UUID/dates strings, nullable values explicit):

ReviewStatus = unreviewed | train_staff | review_question | improve_material | resolved.
Review = {status:ReviewStatus,updated_at:string|null}.
ChoiceDetail = {id:string,text:string,selected:boolean,correct:boolean}.
QuestionDetail = {question_id:string,question_key:string,text:string,type:string,explanation:string|null,is_correct:boolean,points_earned:number,points_possible:number,choices:ChoiceDetail[],review:Review}.
AttemptDetail = {id:string,quiz_id:string,quiz_title:string,content_release_id:string|null,completed_at:string,attempt_number:number,score_percent:number,passed:boolean,evidence_status:'verified'|'unavailable'|'invalid',lesson_id:string|null,questions:QuestionDetail[]}.
QuestionStats = {question_key:string,question_id:string,quiz_id:string,quiz_title:string,content_release_id:string|null,text:string,lesson_id:string|null,respondents:number,incorrect:number,incorrect_percent:number,latest_incorrect:number,latest_incorrect_percent:number,improved:number,regressed:number,wrong_choices:{id:string,text:string,count:number}[],review:Review,example_attempt_id:string}.
CourseInsights = {course_id:string,course_title:string,cohort_basis:'current_structure',attempt_basis:'first_completed',included_employees:number,excluded_attempts:number,questions:QuestionStats[]} sorted first incorrect_percent descending then respondents descending then stable question_key.

Data ownership: quizzes owns all evidence, no writes; learning_insights owns learning_question_reviews keyed (tenant_id,course_id,question_key). question_key is SHA256 of quiz ID, content release ID and canonical full question definition (without graded/selected values); different definitions/releases never mix. QuizAttempt DB identities and snapshot metadata must agree; integrity validation uses courses.release_service.canonical_json_sha256. Never select future attempts beyond date_to; missing/invalid first history must not silently promote a later valid attempt as first. Unknown questions in latest attempt do not count as recovery for the first-version question.

Security/privacy: methodologist and explicitly tenant-bound superadmin only; active admin/student forbidden. Query joins include tenant ownership throughout; all responses Cache-Control:no-store. Return names only for selected employee, aggregate has no PII. No raw evidence payload or hashes logged. Do not use email/phone in DTO. RLS/FORCE RLS annotation table; actor_id nullable only for non-tenant platform actor, otherwise same-tenant. Only SELECT/INSERT/UPDATE granted to lms_app. Annotation status does not edit evidence; unreviewed resets review status without deletion.

Errors: 404 unknown object; 403 role/no tenant; 409 unsupported annotation evidence; 422 invalid filter/cohort overflow; service outage -> normal 5xx error retry. Do not suppress corrupt evidence as success. Performance: bounded 5,001 probe; bulk review loading, no per-question database query. Database statements read existing columns only; no new dependencies.

Read scope: named consumed modules and their tests. Backend write scope: apps/api/app/modules/learning_insights/** EXCEPT models.py; apps/api/tests/unit/test_learning_insights*.py. Root owns models.py, migration, main.py, integration tests and docs. Root reviews producer-consumer tests against these JSON shapes.

## Core mini-spec: methodologist workbench (LI-UI V1)

Responsibility: actionable per-employee and collective interpretation; consumes LI-API exactly. Non-responsibility: computing statistics, changing course/grade, managing credentials. Interface: LearningInsightsPanel({courseId?,departmentId?,positionId?,dateFrom?,dateTo?}) and LearnerAnswers({enrollmentId,onClose}). Data ownership: transient React state only; durable review via PUT. Reopening/reload reads server state. Dismissal is not deletion.

Show first/latest denominators and low-sample notice for respondents<5, “По ключу теста” for correct answers and neutral mass-error copy. Missing historical evidence clearly indicated. Link existing /courses/{courseId}/learn?lessonId={lessonId} only if valid role route is supported; otherwise omit link or use verified course-editor route (root review).

Security: never request for active admin/student; no unsanitized HTML; names/question strings render as text. Loading/error/empty states and stale-response cancellation by request generation/cleanup required for changed course/enrollment. Keep dialog accessible, bounded scrolling, sensible narrow layout. Review mutations disable pending controls and show error/retry; failed save does not appear persisted.

Read scope: UI components, journal page, api/auth/i18n patterns. Write scope: apps/web/src/features/learning-insights/**; apps/web/tests/learningInsights*.tsx and *.ts; apps/web/src/app/admin/training-log/page.tsx. Own local feature translations RU/KK/EN; do not edit shared locale files, dependency/config/route registry. Root accepts compatibility at integration.

## Schema, rollback and verification gates

Root creates 0155 learning_question_reviews (uuid id; tenant_id FK tenants cascade; course_id FK courses cascade; question_key varchar64; status constrained; updated_by UUID nullable; updated_at timezone; unique tenant/course/key). Scope check and same-tenant course ownership enforced by DB policy, status validated DB and HTTP. Retention follows tenant/course deletion; no original evidence retention change. Downgrade drops ONLY the new annotation table (DEV disposable validation); production rollback uses previous app while keeping additive table and review records.

Ready: graph navigation and source confirmation recorded, contracts fixed, write owners assigned.
Done for implementation: source/types/tests pass; synthetic API tenant/RLS evidence recorded, docs updated, clean isolated branch reviewable. Production Done additionally requires exact candidate CI, approved additive migration, frontend/API release and synthetic methodologist readback; never imply local work is live.

AI-COURSE-01 is impacted by migration path: keep all six named required tests in docs/critical-journeys/ai-course-generation.json green; provider smoke remains required at production release. No current authorized external-provider calls for this local implementation.
