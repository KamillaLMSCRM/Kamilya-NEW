# DEV private model connection V1

Status: Accepted technical contract under the owner's 2026-10-16 DEV-only request.
Template: contract-module V2, compact epic/mini-spec combined. Supersedes: none.
Product owner: Askar. Root/integration/runtime-module owner: Codex /root.
GLM relay module owner: bounded relay implementation agent; root accepts its delta.
Independent reviewer: separate read-only agent, appointed before external mutation.
Approved by: root for technical decomposition, owner for DEV connection and tests;
no owner approval of production changes or external billing changes is claimed.
Change control: root reviews evidence, versions a material interface/security change
before implementation, and requests the owner for any authority expansion.

## Outcome, boundaries and module map

Existing Render DEV API and worker can use DeepSeek → ChatGPT → GLM without Qwen,
new paid resources, public model HTTP ingress, or changing production routing,
containers, auth files, image, database, application configuration or model order.
Existing official CLI managed auth is consumed only inside its installed connector;
never export subscription auth to Render. This is synthetic DEV technical acceptance,
not proof of commercial hosted entitlement or customer-content authorization.

`DEV native process -> supervised SSH local forwards -> existing proxy SSH transit
-> (existing private VM126 connector | new private ASUS fixed GLM TCP relay)`.

ASUS relay -> one fixed local-network GLM upstream. It has no application policy,
auth ownership, arbitrary URL parameter, HTTP gateway, model installation or GPU
configuration responsibility. The existing model-routing owner retains order and
readiness policy. Existing proxy stays SSH/WireGuard/Nginx only, no app runtime.

## Runtime module interface and state

Interface: launcher(config, child argv) -> child exit status. DEV environment only;
explicit opt-in and exact role required. Inputs: dedicated SSH private credential,
canonical pinned proxy host key, fixed SSH user, separate connector application
bearer and existing model settings. Outputs: local TCP ports and sanitized lifecycle
codes, never credentials, prompts, responses or raw subprocess/provider errors.

Allowed forwards only: loopback18999 ->10.77.77.2:18999 and loopback18889 ->
10.77.77.4:18005. SSH host: canonical public proxy92.38.49.167:22. Strict host-key
checking, no agent/password/ambient config/remote exec/arbitrary forwards. Runtime
process owns mode0600 temporary credential files; removes them on termination.
Neither local listener binds to0.0.0.0 or Render's public PORT. Child receives no
SSH private key environment variable. Start/restart health never grants model access
without the existing application's configured readiness and persisted order gate.

States: disabled -> existing child only; enabled -> validate -> private temp files
-> SSH start -> local listener check -> child running -> terminal cleanup. Invalid
configuration or SSH startup fails closed before child start. A subsequent SSH exit
terminates/reaps the child rather than leaving a stale hidden channel. Render can
restart its service normally; no separate paid worker, watcher or keep-awake job.
SIGTERM/SIGINT stop and reap owned children. No unbounded credential or connect retry.

## Relay interface and state

Interface: fixed TCP accept at10.77.77.4:18005 ->10.66.66.28:8888 only. No environment
or caller selects destinations. Reject connections not sourced from10.77.77.1,
the proxy WireGuard address. At most4 active connections; connect deadline5s,
wall-clock120s, bounded buffers and per-direction transfer<=4MiB; close both ends
on cancellation/timeout/overflow and release capacity. Do not log request bytes.
Implementation may inject private test constants only through direct in-process
test construction, never through argv/env/network input. Production entrypoint is
fixed. Errors do not include raw payloads or exceptions.

Runs as the existing unprivileged ASUS connector user in a new user-systemd unit
with verified existing linger and user manager. Files only under its new dedicated
relay directory and the one new unit; no sudo, existing units, model files, STT,
WireGuard, routes or firewall changes. Root stops if existing firewall denies it.

## Access, ownership and idempotency

Proxy: one new locked-password non-sudo DEV-only SSH user, two per-service dedicated
keys. Match-user policy: local TCP forwarding only to the two fixed destinations,
no remote/Unix-socket/tun/X11/agent/session/PTY/password access. Validate sshd config
before reload; verify effective policy and actual denied destinations and sessions.
Never export an admin key or add Render to administrative groups. Existing users
must retain the same effective SSH policy. Port22 already exists; no new public port.

No tenant tables/migrations. Credentials belong to the infra owner, stored only in
existing provider secrets and protected runtime files; reports retain fingerprints
and exact source/receipts only. No credential in command args, code, Git, images,
UI or artifacts. Installer refuses foreign/pre-existing target files/accounts;
same owned configuration can reconcile exactly, never overwrite unrelated state.

## Impact, rollout, rollback and stop conditions

| Module | Change | Negative-space protection |
|---|---|---|
| DEV API/worker | Opt-in launcher/start command, private model settings | Existing Free tier, source, DB/schema, queues/pool bounds, auth and frontend unchanged |
| model routing | Normal DEV API update to three-model target after ready | DeepSeek first, no Qwen, no direct DB/readiness bypass; production row unchanged |
| proxy SSH | New restricted principal/key policy only | Existing users, TLS/HTTP/WG/firewall/DNS and production upstreams unchanged |
| ASUS | New fixed private relay and user unit | Existing models and units unchanged; no sudo/new packages |
| VM126 | Read existing application bearer and connector readiness only | No restart, install, config/auth/routing/container change |

Install only after focused tests and independent security review. Snapshot exact
DEV start/env settings in memory or protected canonical secret storage without
printing them. Verify ownership/host identities, then install relay, restricted
access, DEV config/start command and deploy exact DEV candidate on existing tier.
Only after readiness passes save the normal DEV route with optimistic revision.
On failure: disable added DEV route first if enabled, restore only owned DEV
settings/start command, revoke new proxy keys/principal/policy and stop/remove only
new owned ASUS unit/files. Do not delete existing histories or alter production.

Stop on host-key mismatch, unknown mutation outcome (reconcile read-only), foreign
target, denied required privilege, unexpected production drift, unavailable fixed
upstream, increased price/tier/resource, missing rollback, unsafe effective SSH
permissions, or failed mandatory tests. Record and root-dispose the exact blocker;
never guess credentials or expose a public gateway as a workaround.

## Verification and completion

Focused/contract: launcher negative config, argv/no secret environment, loopback
bind, failed/unknown SSH, child exit/signals/cleanup; relay real socket duplex,
source rejection, limits, fixed target and cancellation. Use canonical pytest wrapper.
Native Render SSH availability must be observed, not assumed from a workstation.

Integration on actual DEV API and worker: exact runtime/source/tier readback;
authenticated readiness; direct successful synthetic DeepSeek call; controlled
ephemeral primary failure -> real ChatGPT answer; controlled primary+ChatGPT failure
-> real GLM answer, using installed resilient client and a harmless JSON oracle.
No global primary outage or invalid-key settings. At most one call per case/role;
retry only after a material corrected assumption. Record provider attempt order,
elapsed, validity and transport classes, never content. A catalog/readiness/HTTP200
alone is not completed inference. Test opt-in is one-shot with a hard expiry, removed
after acceptance; cold starts must not create repeated paid inference.

Independent final readback: route persists after reload, new SSH principal denies
shell/arbitrary/remote forwarding, production route/health/config identities unchanged.
Existing GLM is discovered as GLM-5.3-Flash-EXL3 at8888; DEV-only model identity is
updated only after actual synthetic response, not renamed to match the old NVFP4.
No claim of model-quality equivalence. Full production release is NOT IN SCOPE.

Definition of Ready: this contract, exact source/targets, current owner request and
bounded read-only preflights agree; independent reviewer and focused tests precede
mutation. Definition of Done: all actual DEV integration cases/negative boundaries
pass, source/config are recoverable, one-shot probes are disabled, no unowned state
changed, root accepts the final diff and documents any residual limits explicitly.
