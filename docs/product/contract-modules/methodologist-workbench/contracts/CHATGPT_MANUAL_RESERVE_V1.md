# Manual ChatGPT reserve V1

Status: Accepted implementation boundary, not production approval
Approved by: product owner, 2026-10-15 (prepare connection, leave disabled,
superadmin activates manually). Root/module owner: root. Reviewer: independent
bounded reviewer before completion. Changes require a versioned addendum.

## Outcome and module map

Superadmin providers UI -> existing model-routing API/service -> existing singleton
route -> resilient generation client -> server-configured authenticated ChatGPT
gateway. No second enable flag or tenant-owned routing state is introduced.

The module owns manual inclusion/removal and readiness of one optional provider.
It does not own provider authentication, subscription eligibility or provisioning.
Official app-server managed auth is not permitted for commercial/hosted services;
the current workstation login is not exported or reused by this implementation.
The connector requires a separately authorized SIWC-compatible private gateway.
It is NOT a working subscription connection until that dependency exists.

## Interface, data and state

Existing GET/PUT `/admin/model-routing` gains catalog ID `chatgpt_reserve` and
nullable `activation_blocker`. POST `/admin/model-routing/chatgpt-readiness`
returns only `ready`, closed `reason` and timestamp, never credentials/URLs or raw
upstream output. It checks gateway readiness, not model inference. All endpoints
require the active superadmin role. PUT retains row locking/revision conflict
semantics, updated_by/time and sanitized route audit. Readiness is not persisted.
Global singleton retains its current RLS/retention/authorized writers. No tenant
tables or tenant permissions change. Route missing/read failure remains fail-closed.

The new migration expands only the closed route constraint; no route is enabled
or reordered. Disabled -> enabled requires explicit operator save plus fresh
readiness. Removal is always possible without contacting the gateway. Existing
jobs retain their resolved route; newly constructed clients read the saved route.

Server-owned URL must be a literal private/loopback address without userinfo,
query, fragment or redirects; token and model remain server settings. Gateway
must assert protocol `kamilya-chatgpt-reserve-v1`, authorization `siwc`, expected
model and ready=true. Transport uses the existing OpenAI-compatible chat contract,
zero retries and bounded connect/request timeouts; no executable, arbitrary
arguments, subscription tokens or login workflow are exposed by Kamilya.
No gateway is provisioned, started or enabled in this packet.

## Impact, privacy and failure

Interface: routing catalog/schemas/service/router and providers UI (RU/KK/EN).
Consumer: resilient client HTTP adapter. Migration: additive 0180 after 0179.
None: tenant BYOK, embeddings, lessons, assignments, auth, workers, voice,
provider keys, billing, public site and current persisted route/order.
No background readiness polling; GET status causes zero gateway calls. Explicit
readiness contains no tenant content. Generation may send only its existing
request messages when the operator enabled the route. Logs contain closed reasons,
revision/actor/order only. No provider error bodies are reflected to the browser.

Missing settings/unsupported auth/network timeout/protocol mismatch blocks
activation. A configured-but-unreachable selected reserve can fail over to the
next existing provider; no hidden extra retries or semantic-policy changes.
Settings removal omits the provider without activating an alternative by default.

## Verification, rollout and stop

Read scope: exact routing/config/LLM/UI paths and their tests. Write scope: those
paths, new readiness module, migration 0180, frontend component/lib/locales/tests,
existing task plan/ledger/changelog and internal documentation. No external writes.
CodeGraph source preflight previously failed under `--liftoff-only`; use bounded
source fallback, not stale graph edges. No graph-derived runtime/RLS claims.

Ready: current source seams checked and owner no-activation boundary recorded.
Done locally: default/off zero-I/O tests, readiness/activation failures, successful
opt-in/removal/conflict, secret-free responses, RBAC, BYOK and neighboring routing
regression; UI error/loading/cancel/explicit-confirm tests; type/lint and independent
review. Full DEV DB migration and live gateway are separate NOT VERIFIED gates.
Rollback: disable via existing route, then roll back code; downgrade refuses while
new ID is selected, never silently changes the operator's route.
Stop if credentials/provisioning/paid resources/production mutation are required,
or an unlisted module must change. Never mark a missing gateway as connected.
