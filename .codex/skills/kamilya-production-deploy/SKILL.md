---
name: kamilya-production-deploy
description: Deploy an exact Kamilya backend release to KZ production on VM126 with reviewed immutable scripts, rollback, synchronized API/worker identity, and independent readback. Use for production rollout or rollback preparation; never treat the skill as approval, run migrations implicitly, or target CT125/proxy compute.
---

# Kamilya Production Deploy

Orchestrate one exact backend release from verified Git/CI evidence to the KZ
production API and workers on VM126. Compose, rather than replace:

- `kamilya-release-evidence-gate` for the deterministic pre-release decision;
- `kamilya-safe-remote-exec` and `scripts/ops/kz_remote_exec.py` for reviewed
  script transport through the canonical proxy route.

The skill never grants deployment authority. Before execution, bind the current
owner approval to the exact target, release SHA, services, migration scope,
preservation requirements, stop conditions, and rollback operation.

## Mandatory Git identity preflight

**STOP: the repository-root `GITHUB_TOKEN` was verified on 2026-08-26 for the
`KamillaLMSCRM` account. Do not diagnose token expiry from a custom
`GIT_ASKPASS`, a plain `git push`, or the inactive keyring account
`askar0007amirkhanov`.**

- Require exact commit author `Kamilya Codex <kamilla_lms_crm@proton.me>`.
- From `apps/api`, verify the process-local credential without printing it:
  `poetry run dotenv -f ..\..\.env run -- gh auth status --hostname github.com`.
- Push only through the official process-local helper:
  `poetry run dotenv -f ..\..\.env run -- git -c credential.helper= -c "credential.helper=!gh auth git-credential" -C ..\.. push origin <exact-sha>:<exact-branch>`.
- Never create a custom askpass script, use a browser/device login, put the token
  in a URL/command/config, or treat another account's 403 as token evidence.
- Declare the canonical token invalid only when this exact root-env
  `gh auth status` fails authentication.

## Fixed production topology

- The proxy is ingress and SSH transport only; never build or run Kamilya there.
- VM126 runs the production API, three workers, Valkey, and file services.
- CT125 runs PostgreSQL. A backend release is `no-migration` unless an approved
  migration node explicitly names CT125, the revision, backup/restore evidence,
  runtime roles, cleanup, and rollback limits.
- Public traffic is Vercel frontend -> `api.kml.kz` -> proxy -> WireGuard ->
  VM126. Validate frontend/backend compatibility, but do not mutate Vercel from
  this backend deployment unless the approval explicitly includes it.
- When frontend deployment is approved, resolve the custom production alias to
  its actual Vercel project before deployment. A READY deployment in a dev
  project is not production evidence. After deployment, prove `app.kml.kz`
  points to the target deployment and that deployment carries the exact release
  SHA.

## Required release inputs

Refuse mutation until all values are exact and independently read back:

- full 40-character release SHA and immutable CI run/artifact identity;
- current production release SHA and exact API/worker image identities;
- intended branch/ref and confirmation that the release commit is reachable;
- migration mode: `no-migration` or an exact separately approved migration;
- services allowed to change, normally API plus `worker-ops`,
  `worker-documents`, and `worker-ai` only;
- correlation/approval ID, expected old SHA/image, rollback image/config, and
  bounded health timeout;
- changed-capability smoke plan and synthetic-data cleanup rule.

Dirty local work is not release content. Build the source archive from the exact
Git object, never from the working directory. Do not reset, clean, stash, or
include unrelated changes.

## Deployment procedure

1. **Evidence gate.** Verify tests, CI, release identity, current runtime,
   owner approval, rollback readiness, and environment binding. Evaluate the
   sanitized envelope with `kamilya-release-evidence-gate`; independently verify
   every reference before root declares an actionable `GO`.
2. **Idempotency check.** If public and private health plus all four container
   images already match the release, do not rebuild or redeploy. Continue with
   readback/smoke only and report `ALREADY_DEPLOYED`.
3. **Exact package.** Create a `git archive` from the full release SHA. Record
   archive SHA-256 and size. Stage it without secrets and verify the remote hash
   before extraction or build.
4. **Read-only preflight.** Use a reviewed `read-only` script through
   `kz_remote_exec.py`. Confirm VM126 identity, expected old public/private SHA,
   all API/worker images, service health, deployment environment, disk and
   memory headroom, compose project, rollback material, and absence of an
   unrelated active rollout. Emit only sanitized `EVIDENCE|key=value` lines.
5. **Reviewed mutation script.** Store the LF/UTF-8 `.sh` under the current
   release evidence directory. Include the required `kamilya-*` headers,
   `set -Eeuo pipefail`, exact expected-old assertions, bounded operations,
   configuration backups, and an `ERR` trap that restores the previous
   image/config and recreates the same allowed services.
6. **One immutable execution.** Dry-run the script, review it, record SHA-256,
   then execute those exact bytes once in `mutation` mode with the approved
   correlation ID and expected hash. Never reconstruct shell quoting across
   PowerShell/SSH layers and never retry a partially applied script blindly.
7. **Synchronized rollout.** Build/tag the exact release image and recreate only
   the approved API and three workers. Require all four to resolve to the same
   image and full release SHA. A mixed identity is `PARTIAL_ROLLOUT`, not a
   successful deploy. If a host timer can enter one of these containers, stop
   that timer immediately before recreation, run and verify its oneshot against
   the healthy new runtime, then restart and read back the timer.
8. **Health and rollback gate.** Require bounded private API health before
   public health. On build failure, container failure, timeout, wrong SHA,
   mixed images, or unhealthy API, execute the reviewed rollback path and stop.
   Do not improvise a second deploy.
9. **Independent readback.** After the remote script terminates, independently
   re-read public `api.kml.kz/health`, private health, container health/images,
   deployment environment, recent bounded error summaries, and resource
   pressure. Provider/front-end evidence must match the compatibility plan.
10. **Capability smoke and cleanup.** Exercise only the changed behavior with
    synthetic data and no real PII. Verify both success and a relevant negative
    path. Remove disposable data through the approved application/database
     seam and prove absence. Never use a production customer record as smoke.
11. **Watchdog and documentation.** Update the watchdog expected SHA only after
     synchronized rollout and independent readback. Read the existing
     EnvironmentFile and update its actual keys; the current production keys are
     `EXPECTED_RELEASE` and `EXPECTED_API_IMAGE`. Preserve rollback evidence,
    then transfer durable facts to `docs/PRODUCTION_READINESS.md`, `ERRORS.md`
    only for confirmed reusable failures, and the active release plan. Do not
    create a parallel project-truth file.

## VM126 execution invariants

- The canonical target user is `kamilya-admin`; Docker and root-owned runtime
  files require `sudo -n`. Read-only helper validation may unwrap only
  `sudo -n` followed by an already allowlisted command. Never broaden this to
  arbitrary `sudo`, shell execution, or Docker mutation.
- `/opt/kamilya-runtime` is root-only. Do not `cd` into it as the target user.
  Use absolute paths and `sudo -n docker compose --env-file
  /opt/kamilya-runtime/runtime.env -f /opt/kamilya-runtime/compose.yml ...`.
- An `ERR` rollback handler must capture the original status, immediately
  disable its own trap, attempt the restore, and exit with the original nonzero
  status. Expected startup polling failures belong inside `if` conditions and
  must not trigger rollback.
- Emit sanitized stage evidence before and after preflight, backup, config
  validation, recreation, health, and rollback. Preserve validated evidence on
  remote failure, but never return raw stdout/stderr.
- Treat hidden PTY input as unsuitable for exact strings containing `@` or
  other transport-sensitive characters. Accept local/domain parts separately
  or use a secret-safe non-PTY input channel, then assert the reconstructed
  shape before any external or data mutation.
- A deploy is not successful until a separate read-only script proves all
  expected container image/status/restart values and public health proves the
  exact release. Update watchdog identity only after that independent readback.
- A release containing an approved CT125 migration additionally requires an
  independent CT125 readback of the exact Alembic revision, expected schema and
  FORCE RLS state, plus cleanup proof. VM126 migration output alone is not
  database evidence.

## Stop and rollback conditions

Stop without further mutation on target ambiguity, missing exact approval,
stale expected-old identity, unknown migration state, insufficient resources,
archive/hash mismatch, unexpected compose diff, extra service impact, warning
that changes the approved scope, or inability to prove rollback readiness.

After mutation begins, rollback on failed build, failed recreation, bounded
health timeout, wrong release SHA, mixed API/worker images, or changed
deployment identity. Preserve evidence and report the exact first failing gate.
Do not update the watchdog expected SHA, claim success, or continue to another
release while rollback/readback is unresolved.

## Evidence and final verdict

Use only `GIT-DERIVED`, `RUNTIME-DERIVED`, `OWNER-CONFIRMED`,
`PROVIDER-CONFIRMED`, `GRAPH-DERIVED`, `INFERRED`, `NOT VERIFIED`, and
`BLOCKED`. Never expose environment values, credentials, tokens, URLs carrying
secrets, tenant payloads, contact data, or raw logs.

Final output must name the exact release SHA, previous SHA, CI run, archive and
script hashes, changed services, migration mode, public/private/container
readback, smoke/cleanup result, rollback state, residual blockers, and honest
`GO` or `NO-GO`. A script exit code or agent report alone is not production
evidence.
