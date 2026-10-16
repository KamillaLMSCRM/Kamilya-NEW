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
