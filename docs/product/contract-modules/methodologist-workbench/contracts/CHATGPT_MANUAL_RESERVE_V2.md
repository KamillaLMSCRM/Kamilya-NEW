# Manual Codex CLI reserve V2

Status: Accepted implementation boundary, not vendor entitlement or release approval
Supersedes: CHATGPT_MANUAL_RESERVE_V1.md
Reason: owner explicitly rejected an adapter to an absent SIWC gateway and requested
an actual official CLI connection with the current subscription, left OFF.
Approved by: product owner, 2026-10-15. Root/module owner: root; independent reviewer
must not implement the reviewed changes. Change control: a new versioned addendum.

## Responsibility, contribution and interfaces

Superadmin control -> existing singleton routing -> private authenticated CLI
connector -> official `codex exec` -> managed ChatGPT auth. The connector now is an
implemented component, not an unspecified external gateway. It owns fixed-argument
process lifecycle, typed input/output, readiness, bounded execution and sanitized
failures. It does not decide tenant rights, modify courses or execute LMS actions.
No raw subscription token is accepted by the browser or substituted into public
OpenAI API calls. CLI manages its existing auth file and refresh lifecycle.

Retain GET/PUT routing and explicit readiness contracts from V1; actual connector
GET `/v1/readiness` validates CLI version and managed ChatGPT login. Connector
POST `/v1/chat/completions` accepts messages/model/max_tokens/temperature and
optional response_format, runs one ephemeral CLI execution and returns an
OpenAI-compatible envelope. Constant-time bearer verification, no redirects or
public listener. API settings use auth mode `codex_cli`, not a fictitious SIWC
assertion. Managed authentication is a technical observation, not proof of
commercial-use approval. Official vendor limitations remain visibly documented.

## Data ownership, security and invariants

The existing global route remains the sole enable source; no default, migration,
health check, test or installer inserts the reserve ID. Current/rollback/provider
order remain unchanged until an explicit superadmin write. New clients follow
saved order; BYOK stays isolated. Removal works even when connector is down.

CLI receives only request messages on stdin, never tenant DB credentials or API
process environment. Model and executable are fixed server configuration. No
shell=True, arbitrary CLI arguments, session resume or persistent conversation.
Use ignored user config, ephemeral mode, read-only sandbox, disabled shell/apps/
plugins/browser/image/memory/multiagent/workspace tools and no user repository CWD.
No model tool event is accepted as a text result. Container runtime must isolate
the service from LMS files/DB/network/host Docker socket, drop capabilities and
limit resources; disabling tools in a prompt alone is not a security boundary.
No shell/tool bypass flag is permitted. If hard tool isolation cannot be proved,
stop before production, rather than declaring a benign no-tools response proof.

Authentication stays in a separately protected CLI home volume on the selected
runner. The prior DPAPI access-token backup is not a refreshable service login.
No secrets/prompts/raw stderr in logs or responses. Request state is ephemeral,
not persisted to the DB/disk; CLI output is bounded and temporary files removed.
Worker concurrency1, finite queue/no retries, per-request wallclock and output
bounds. Cancellation terminates the child; malformed output is a closed failure.

## State, impact, rollout and verification

States: not configured / configured but unavailable / managed login required /
ready; independent route OFF/ON. Readiness never runs generation or changes route.
Idempotency: readiness read-only; route mutations use existing revision/row lock;
generation is non-repeatable and never automatically retried by this connector.
Logs: closed errors, process version, elapsed and token counters only when present.

Allowed changes extend V1: `infra/codex-reserve/` runner/service/image/tests,
readiness protocol/config and existing UI copy/docs/tests. No voice, BYOK changes,
tenant mutations, provider billing/new paid resources, proxy compute or arbitrary
administrative access. Container installation/release requires exact existing
release gates and independently verified environment/capacity; no ad-hoc live
Docker mutation or auth copying may substitute for those gates.

Ready for code: exact CLI/help/auth/protocol inspected. Done locally: deterministic
invalid-input/auth/process/output/timeout/cancel/busy cases, actual current-login
synthetic response through the implemented connector and application transport,
OFF/no connector call and route/BYOK/RBAC regressions, UI/manual-control checks,
quality baseline and independent review. Done in production separately requires
exact source/image/CLI/auth/runtime/schema and OFF readback plus isolated synthetic
test. No ON test without explicit test-only authorization; do not enable the
persisted reserve even temporarily. Stop on unknown isolation, access/billing,
missing release authority or unplanned module impact. Rollback: disable/remove
connector with route unchanged, then existing app rollback; V1 schema rollback
constraint remains unchanged.
