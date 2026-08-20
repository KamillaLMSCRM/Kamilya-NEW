# Kamilya LMS — P0 security remediation

Дата старта: 2026-08-20

## Scope

Исправления выполняются последовательно, по одному finding за цикл `red -> green`:

1. SEC-001: stored XSS в содержании урока;
2. SEC-002: kiosk impersonation;
3. SEC-003: SCORM trust boundary;
4. SEC-005: production monitoring на фактический KZ контур.

Существующие параллельные изменения не откатываются. Commit, push, deploy и production mutation выполняются только после локального зелёного gate и отдельного release review.

## Task graph

```text
P0-01 safe lesson renderer
  -> P0-02 kiosk capability redesign
     -> P0-03 isolated SCORM design/implementation
        -> P0-04 KZ environment monitoring source of truth
           -> P0-05 full regression and release review
```

## Seams and gates

| ID | Public seam | Red evidence | Green gate | Status |
|---|---|---|---|---|
| P0-01 | Course player renders persisted lesson content | Malicious HTML becomes DOM nodes | No active/raw HTML DOM; basic emphasis/newlines remain | COMPLETE |
| P0-02 | `POST /kiosks/{token}/identify` and kiosk-authorized course access | URL + personnel number issues broad JWT | Second factor, lockout, generic errors, narrow scope | COMPLETE (DB runtime gate pending) |
| P0-03 | Learner launches and commits SCORM | Frame blocked or trusted-origin JS | Separate untrusted origin + sandbox/bridge | COMPLETE (production ingress/E2E gate pending) |
| P0-04 | Production smoke/health/runbook | Old Render/Supabase can satisfy checks | KZ target + deployment identity/readiness | COMPLETE (production rollout/fault-injection gate pending) |
| P0-05 | Full regression/release | N/A | unit/integration/web/build/Graphify + independent diff review | COMPLETE LOCALLY (DB/production gates pending) |

## Safety gates

- No production exploit or load test.
- No credential, token, PII or raw client content in tests/logs/docs.
- Kiosk schema/migration must be additive and tenant/RLS safe.
- SCORM must not be fixed by weakening app/API frame protection.
- Monitoring must distinguish production from dev/demo/rollback.
