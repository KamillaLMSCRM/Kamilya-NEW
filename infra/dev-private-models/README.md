# Private DEV model transport

Owner: root; canonical topology and access: `docs/PROJECT-CONTEXT.md` and
`docs/VPS_CONNECTION_GUIDE.md`. Contract: `DEV_PRIVATE_MODEL_CONNECTION_V2.md`.
This directory is DEV-only infrastructure, not a public HTTP model gateway.

## Installed and deferred

The proxy principal `kamilya-dev-models` has locked password, no sessions and no
privileges. Separate API and worker keys permit only local TCP forwarding to
`10.77.77.2:18999` (existing ChatGPT connector) and `10.77.77.4:18005` (reserved GLM
relay). The existing SSH listener and independently pinned Ed25519 host key are
used; no port is opened. Existing users' effective policies must remain unchanged.

ASUS is owner-confirmed down on2026-10-16. Do not install or probe its relay until
the owner reports recovery. `glm_relay.py` and the new user unit are prepared,
not installed. No old Qwen/GLM unit is modified. A configured forwarding slot
does not prove destination connectivity or qualify a model.

## Existing Render Free API and worker

Preserve each original command verbatim as the launcher child:

```
python ../../scripts/ops/dev_private_model_runtime.py -- <original command>
```

Set only the owned keys using single-key writes and independent readback:
`DEV_MODEL_SSH_ENABLED=true`, `DEV_MODEL_SSH_ROLE=api|worker`,
`DEV_MODEL_SSH_KEY_B64`, `DEV_MODEL_SSH_KNOWN_HOST`, `CHATGPT_RESERVE_URL`,
`CHATGPT_RESERVE_TOKEN`, `CHATGPT_RESERVE_MODEL`, `CHATGPT_RESERVE_AUTH_MODE`.
Keys/bearer are provider secrets, never CLI arguments, logs, reports or Git files.
The role/environment pairs are exactly `api/render-development` and
`worker/render-development-worker`; production is refused. The SSH key is removed
from the application child environment and its temporary private file is0600.
Loss of the owned SSH process stops the consumer; the supervisor reaps children.

Short startup errors are drained with buffered read1, not a size-filling read;
the private tail remains bounded64KiB and only fixed error codes are published.
Native connected/retry/blocked markers carry one generated startup_id and a
one-way hash of the optional provider instance ID. Group by startup_id before
inferring retry continuity; historical uncorrelated service logs may contain
different process invocations. This adds no reconnect loop or retry category.
Bounded fixed phase markers distinguish forward_starting, forward_ready,
forward_cleanup, forward_stopped and consumer_starting. Attempt is1or2 with
the same generated startup identity/hash; no destination, raw stderr, key or
application input is logged. A later rollback/restart's connected marker does
not accept an earlier failed deployment.

Reset-phase follow-up020: OpenSSH DEBUG1 stays inside the same bounded private
stderr drain. On a failed attempt, `forward_failure` emits only fixed `stage`
(unknown/tcp_established/peer_banner/key_exchange/authenticated) and `operation`
(unknown/connect/banner_read/banner_write) codes, with the existing correlation.
No raw diagnostic, server banner, address or key path is published. Unknown or
truncated diagnostics stay unknown. This is phase evidence, not proof of the
resetting physical node; combine it with the corresponding proxy header/journal
window before attributing cause. Retry count, timeouts, trust and policy remain.

The loopback URL is `http://127.0.0.1:18999/v1`. Pin the existing approved model and
CLI auth mode; do not export subscription authentication. The application bearer
does not replace managed CLI login or establish commercial hosted-use entitlement.
Use the normal superadmin readiness/revision-checked routing API, never direct DB
writes or a readiness bypass. Target order is DeepSeek → ChatGPT → GLM; Qwen is
not part of the DEV target. Production is outside this operation.

## One-shot synthetic acceptance

Only on the exact CI-passing DEV candidate, set a unique `DEV_MODEL_ACCEPTANCE_ID`
matching `DEV-PRIVATE-20261016-[A-Z0-9]{1,12}`, an aware UTC
`DEV_MODEL_ACCEPTANCE_UNTIL` no more than20minutes ahead, and scope
`DEV_MODEL_ACCEPTANCE_SCOPE=primary_chatgpt` while ASUS is down. The launcher sets
the role. API/worker each claim their run once in existing DEV Redis before any
inference; worker waits for the matching successful API terminal marker. The
diagnostic process uses pool1/overflow0, no public endpoint and no customer data.

The normal case calls real DeepSeek. A request-local loopback503 forces the next
case through real ChatGPT using the installed resilient client. This never saves
a failed endpoint in model routing. Receipts are content-free native Render log
lines beginning `DEV_MODEL_ACCEPTANCE|`; preserve failed runs and exact source,
deployment IDs, provider order, latency and JSON validity. Partial scope must
report `PARTIAL_PASS`, not full-chain PASS. GLM remains explicitly NOT RUN.

After the run, remove only the three acceptance env keys and these exact Redis
keys for the run ID: `qa:dev-private-models:<id>:api`, `...:worker`,
`...:api:terminal`. Never clear Redis broadly. An unknown deployment/write outcome
is reconciled by GET, not repeated blindly. A new run ID requires a material
correction or a separately documented acceptance run, not automatic retries.

## Rollback and verification

Assignment-only extension2026-10-16: scope `assignment_intent` is API-only and
requires the same explicit DEV/expiry/NX gate. It calls the actual intent
application as the fixed canonical QA actor with tenant/user RLS and marker
validation. Normal DeepSeek case then invocation-local primary8s hang→ChatGPT;
the ephemeral route has at most2providers, never owner-deferred ASUS. No preview
or confirmation is executed by this probe. Before/after counts and budget
estimate/request deltas are independently read back. Content-free receipt is also
durable at `qa:dev-private-models:<id>:api:receipt`, not stdout alone.

After copying terminal proof, remove opt-in env keys. Preserve the NX claim until
the immutable opt-in expiry; exact3API-marker TTLs may be capped to that expiry
(round up, never early). This is safe automatic test-marker expiry, not a global
Redis cleanup. Remove exact expired keys only if still present. Missing durable
receipt is NOT acceptance; never repeat inference to replace absent telemetry.

Restore the original DEV start commands and owned environment snapshots; verify
the original API/worker health and queues. Restore automatic deployment if it was
temporarily disabled for the exact-SHA CI gate. Remove only this operation's
verified restricted keys/policy/account using the digest-bound rollback script;
revoke keys before removing the restrictive policy. Shell installers refuse
foreign files/state. No general prune, password reset, global SSH edit or grant.
The ASUS rollback removes only the new user unit/owned files, never old services.

Before installation, review exact hashes, run shell syntax tests and independently
verify canonical host trust. Afterward, test both keys: approved readiness,
denied session, denied known-reachable arbitrary destination, denied reverse
forward, unchanged existing users and no new public listener. Local unit tests
are necessary but do not substitute for those runtime checks or real inference.
