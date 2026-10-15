# Assignment dialogue recovery V1.1

Status: Accepted for bounded repair, 2026-10-15.
Supersedes: ASSIGNMENT_DIALOGUE_V1.md only for recovery details below; all its
ownership, limits, scope, exclusions and verification obligations remain.
Approved by Root under current owner DEV/production assignment request.

Independent Test Runner R1 confirmed two product defects before release:
known409 was labeled unknown and trapped editing; reload forgot an in-flight
confirmation and could allow replacement while its commit remained unresolved.

Before confirm POST, synchronously persist only the opaque existing locator in
URL ?plan=<id>&confirming=1. This marker is never confirmation/execution authority:
it only restricts UI; owned GET and current fingerprint/revision remain required.
No raw instructions, candidate, credentials or private history in URL/storage.
Reload with marker and ready GET stays locked to that same plan/read/reconfirm.
Network/read failure preserves marker/locator and explicit same-ID read recovery.
Succeeded receipt removes only confirming marker and restores result navigation.

A typed API409 with a known deterministic confirmation conflict detail is a
definitive rejection, not a network-unknown result. Clear confirmation lock and
old preview/marker, show rejection and allow a new explicit command. Unknown409,
rate limits, gateway errors or message-only errors remain unknown. Never infer
server rejection from free-form exception prose. GET ready alone never unlocks.
No same-ID POST is sent automatically by restore/recovery.

Write scope stays V1; no API/schema/auth/state-owner change. Add regressions:
known typed409 vs unknown409/network, lostconfirm->reload->ready stays locked,
lostconfirm->reload->receipt closes marker, read failure preserves locator;
same-ID retry/idempotency and no extra assignment/model calls. Independent
review and Root acceptance required; no timeout/assertion weakening.
