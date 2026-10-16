# DEV private model connection V2 — ASUS outage split

Status: Accepted technical impact addendum,2026-10-16. Supersedes V1 rollout order
only; V1 security, ownership, full-chain objective and remaining obligations remain.
Root/module owner: Codex /root. Product owner: Askar. Reviewer: independent private
security review agent. Approved by: root technical disposition under current owner
request; owner explicitly confirmed all ASUS are down and deferred their connectivity
checks. Production changes, billing changes and a public gateway remain forbidden.

## Evidence and disposition

The first bootstrap stopped before all external writes on a harness assumption:
worker environment is `render-development-worker`, not the API's `render-development`.
The corrected bootstrap then stopped before writes on ASUS SSH TimeoutError. The
canonical OpenSSH alias also timed out. One independently authorized root read of
the documented WG transit failed. Owner confirmed the ASUS outage; do not repeat
ASUS probes until the owner reports recovery or another explicit state change.

Root accepts independent delivery of the private ChatGPT connection now. No GLM
relay/user unit is installed during this phase, no GLM endpoint/model is changed,
and no GLM inference/readiness is implied. The two fixed local SSH forwarding slots
and restricted proxy policy may be installed as designed, but only the existing
ChatGPT destination is required/qualified for this phase; the unused GLM slot does
not establish connectivity. No other destination or key privilege is added.

## Interface and acceptance delta

Canonical runtime environment is an exact role/environment pair:
`api/render-development`, `worker/render-development-worker`. Cross-pairing fails
closed; neither accepts production. This reflects fresh existing provider settings,
not a provider-environment change.

The one-shot acceptance scope may be `primary_chatgpt` or `full_chain` (default).
Partial mode executes exactly the first two original cases on API and worker,
records `PARTIAL_PASS` rather than full PASS, and leaves GLM NOT_RUN_OWNER_DEFERRED.
Worker waits for the matching API scope's terminal success. Redis claim/expiry,
real installed-client/provider invocation and content-free receipts remain required.
An expired/failed/unclaimed API run cannot release worker inference. No failure
injection is installed in production or persisted in global provider settings.

## Rollout, negative space and completion

Install only restricted proxy access, verify existing-user policies and negative
probes, qualify authenticated private ChatGPT readiness, then stage only SSH and
ChatGPT settings in the existing Free DEV API/worker. Deploy an exact CI-passing
DEV source and save the normal three-provider target only after ChatGPT readiness.
GLM may remain a configured last-resort catalog entry but is explicitly unavailable;
do not claim full three-provider failover or change its model identity by assumption.

Rollback restores only owned DEV configuration/order and removes only owned new
access. No ASUS writes occur in this phase. Preserve failed bootstrap receipts.
After owner-confirmed ASUS recovery, root resumes V1's fixed relay/GLM qualification
and full-chain acceptance; do not reuse partial PASS as that gate. Root reports
both the delivered partial outcome and the still-open third-provider gate.

## DEV delivery support, root disposition

The existing backend CI job includes the three new database-free infrastructure
test files. The local full run found one pre-existing path-sensitive privacy
assertion: formatted exception traceback paths contain the worktree name
`learner-presentation-release-20261010`. The narrow correction checks emitted
messages for the forbidden label and the entire log for the synthetic learner ID;
it does not remove the privacy check or alter application behavior. No product
feature or production release is authorized by this test correction.

For exact-SHA CI-before-deploy, the existing DEV API automatic deployment may be
temporarily disabled with readback, then restored to its original value after
the controlled deployment. Existing API/worker start commands are preserved as
children of the opt-in launcher. No plan, resource, environment identity, public
listener, production setting, or worker queue changes are permitted.

## Observed DEV transport reset, root technical disposition

Actual worker candidate1ec2e98 classifies the startup failure as TCP connection
reset, before application start. Exact server policy has no per-source startup
limit or unused-connection timeout, and no credential denial/MaxStartups drop was
observed. The resetting network node is NOT localized; do not attribute it to
ASUS or infer a key problem. Render documents public outbound TCP routing resets
at https://render.com/docs/outbound-connection-resets.

Permit exactly one bounded startup recovery after a classified connection
reset/close, with the same destination, pinned host and credential. Stop/reap the
first process, wait1second, attempt once more; a second failure stops. Never retry
host-key/authentication/policy failures, add a live reconnect loop, change ports,
relax trust or repeat model calls. Actual inference remains independently claimed
once. Deterministic tests cover successful recovery, strict-failure no-retry and
the two-reset terminal boundary. This changes transport resilience, not model
order, production or billing authority.
