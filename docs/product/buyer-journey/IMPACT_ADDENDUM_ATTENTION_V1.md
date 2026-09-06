# BUYER-JOURNEY attention presentation V1

Status: Accepted. Supplements EPIC_V1; supersedes none. Root accepted within
owner-approved dashboard action-priority objective, 2026-09-06.
Root becomes sole START writer after Planck handoff.

Consume existing GET `/v1/admin/training-log/summary` in a methodologist-only
`TrainingOverview` component. Inputs: active session token, tenant, locale.
Output: real assigned/in-progress/overdue counts and existing training-log link.
No invented failed-test count: this endpoint has no such classification. The
interactive example explains failure analysis; the working log retains scores.
Backend remains data owner; no changes to API, permissions, DB or records.
Loading/error/missing field must show unknown, never fabricated zero. Cancel or
ignore stale responses on identity change/unmount, and never render previous
identity data. No fetch for other roles. Component-local copy is RU/KK/EN.
New paths: `apps/web/src/components/admin/TrainingOverview.tsx` and
`apps/web/tests/trainingOverview.test.tsx`; root inserts into dashboard before
start options and AI queue. Existing test mocks may gain the read-only seam.
Run component tests for counts/error/role/identity, existing dashboard and log
regressions, typecheck and browser gate. Rollback component and consumer import.
No new config, retention, logging, writes, retries, schedules or provider.

Artifact integration addendum: root owns landing `.gitattributes` binary rules
for presentation PDF/PNG, preventing CRLF corruption, and focused deck tests.
No global Git configuration changes. PDF is a visual browser-capture edition
with preserved clickable links and outlines; HTML remains editable/searchable.

Browser QA addendum: root also owns a presentation-only min-width/word-wrap
correction in landing `components/Pricing.tsx`. The longer KK two-start label
exposed a 391px grid on a 390px viewport. Preserve pricing, consent and lead
handlers; verify no horizontal overflow on mobile after the correction.
