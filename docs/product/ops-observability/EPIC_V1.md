# Superadmin operational observability V1

Status: Accepted
Version: V1
Approved by: product owner through explicit implementation request on 2026-09-25
Change control: the root owner may correct implementation details that preserve this contract; any new metric, mutation, alert, infrastructure action, or change to another product workflow requires a versioned addendum and product-owner approval.

## Roles

- Root owner: root Codex agent; owns the interface, integration, final diff, release gates and runtime readback.
- Module owners: root Codex agent for the API contract and web integration; delegated workers may only perform bounded read-only review.
- Product owner: current Kamilya owner/user; owns outcome, exclusions and production authority.
- Reviewer: independent delegated reviewer before release; root verifies every finding and check.

## Observable outcome

An authenticated platform superadmin can open `/admin/super/operations` and tell, without host access, whether host memory or disk pressure exists and whether each required Celery role (`fast`, `documents`, `ai`) is reachable and attached to its expected queues. Partial failure remains visible instead of collapsing into one worker count.

## Exclusions

- No database migration, tenant data, alert delivery, worker restart, watchdog change, disk cleanup, provider configuration, billing change, or new external dependency.
- No hostnames, broker URLs, worker node names, file paths, secrets, tenant names, document names, job payloads or PII in the response.
- Existing cleanup, stale-job recovery, CRM requeue, routes, roles, task registration and queue routing remain unchanged.

## Directed module map and public seams

```text
psutil + bounded Celery inspect
  -> GET /api/v1/admin/super/operations/summary
  -> OperationsSummary JSON
  -> /admin/super/operations
  -> superadmin-visible health cards
```

The executable producer-consumer seam is the `OperationsSummary` JSON returned by the existing GET route. The UI consumes the same fields. Authorization remains the existing `require_role("superadmin")` boundary.

## Module OPS-RUNTIME V1

- Responsibility: collect safe host CPU/RAM/filesystem metrics and classify the three code-owned Celery roles from one bounded control-plane inspection.
- Non-responsibilities: service management, alerting, repair, queue mutation, worker naming disclosure or infrastructure discovery.
- User-visible contribution: truthful per-role health and host pressure data.
- External interface: `OperationsSummary.host`, `.filesystem`, and `.celery`.
- Inputs/outputs: local `psutil` data and Celery `registered`/`active_queues` maps produce nullable metrics and code-owned role summaries.
- Data ownership: stateless derived runtime snapshot; no persistence.
- Invariants: partial data is returned as unavailable fields; one missing role does not hide healthy roles; only expected role/queue/task names may leave the API.
- Error modes: metric failure yields nulls; inspect timeout/broker failure yields three unavailable role summaries without raw exception text.
- Security/privacy: superadmin-only; sanitize node identity and infrastructure details.
- Idempotency/concurrency: read-only and repeatable; one bounded inspect interaction per summary request.
- Performance/configuration: existing Celery timeout plus outer margin remains; no new setting.
- Verification: public model literals plus route-contract tests with synthetic psutil and Celery responses.
- Read scope: current operations module, Celery routing and focused tests.
- Write scope: operations module and focused operations tests only.
- Stop conditions: another endpoint, worker route, setting, dependency or infrastructure mutation becomes necessary.
- Ready: existing route, topology and expected queues are confirmed in source/runbook.
- Done: focused contract tests prove normal, partial and unavailable behavior without sensitive output.

## Module OPS-WEB V1

- Responsibility: render RAM, disk and each code-owned worker role with clear normal/warning/critical states.
- Non-responsibilities: repair controls, alert configuration, worker logs or new navigation.
- User-visible contribution: a superadmin can identify the failed resource or role and knows when data is stale.
- External interface: existing operations page consuming `OperationsSummary`.
- Inputs/outputs: API JSON to accessible cards, labels and status text in RU/KK/EN.
- Data ownership: stateless client rendering.
- Invariants: loading/error/stale behavior remains; nullable data is not shown as zero; partial worker failure is visible; desktop and mobile remain readable.
- Error modes: existing successful data stays visible and marked stale when refresh fails.
- Security/privacy: render only API-safe fields; never infer or display node names.
- Dependencies: existing UI primitives, i18n and auth store only.
- Verification: frontend typecheck/build plus focused rendering/source contract where the current stack supports it; browser acceptance in DEV and production.
- Read scope: operations page, its locale entries and existing frontend test pattern.
- Write scope: operations page, its locale entries and one focused test if needed.
- Stop conditions: shared API client, auth, navigation or unrelated component redesign becomes necessary.
- Ready: API contract is fixed by OPS-RUNTIME tests.
- Done: all three roles and memory metrics render with human-readable degraded states.

## Impact and negative space

| Existing area | Impact | Required proof |
|---|---|---|
| Operations summary API | Compatible interface extension | producer-consumer contract test |
| Superadmin operations page | Consumer update | typecheck/build and browser QA |
| RBAC | None | existing route remains superadmin-only |
| Celery routing/task registration | None | no routing/config diff; synthetic inspect tests |
| Database/tenant isolation | None | no schema/query ownership change |
| Existing operational mutations | None | focused existing operations suite remains green |

## Critical journeys and acceptance

1. Healthy snapshot: RAM/disk are numeric and `fast`, `documents`, `ai` are independently healthy with expected queues.
2. Partial degradation: one role is missing or has a wrong queue; healthy roles remain green and the affected role is explicitly degraded.
3. Control-plane failure: the page loads other snapshot data, all roles are unavailable, and no exception, hostname or broker detail is exposed.
4. Authorization: a non-superadmin cannot obtain the snapshot.
5. Release: DEV first, then the unchanged exact candidate in production; independently read back API/frontend SHA and visually verify the page.

Rollback is the previous immutable API/frontend release. No persisted data requires rollback.
