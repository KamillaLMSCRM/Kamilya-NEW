# ECC selective pilot: deterministic Kamilya release bridge

Date: 2026-09-27

Branch: `experiment/ecc-release-pilot-20260927`

Base: `origin/master` at `315e01320a0395b4c30a0f7738d3eccb01e5417e`

## Goal

Test whether selected ECC patterns can reduce the context and model work required
for a prepared Kamilya release without installing the full ECC plugin, enabling
hooks/MCP, or changing DEV/production.

Patterns under test:

- iterative retrieval instead of full-document bootstrap;
- one deep deterministic module behind a small interface;
- test-first evaluation at agreed seams;
- compact checkpoint/handoff instead of raw logs;
- explicit context/output metrics.

## Agreed seams

1. digest-bound release packet -> deterministic validation and command plan;
2. technical evidence + Test Runner evidence -> five-field root handoff;
3. invalid digest or incomplete evidence -> fail-closed reason code;
4. CLI execution -> bounded JSON output and measurable elapsed time.

The pilot reuses the existing `ReleasePacket` and
`scripts/ops/ct137_native_release.py`. It does not duplicate deployment logic.
Its `dispatch` operation may invoke one controller phase, but only from an exact
digest-bound packet and only after the phase-specific safety gates pass.

## Baseline

CodeBurn snapshot for the persistent `Kamilya — Release Runner` chat from
2026-09-23 through 2026-09-27:

| Metric | Baseline |
|---|---:|
| Turns | 4 |
| Model calls | 35 |
| Input tokens | 694,262 |
| Cache-read tokens | 3,719,424 |
| Output tokens | 22,893 |
| Average input per model call | 19,836 |
| Average cache read per model call | 106,269 |
| CodeBurn estimated cost | USD 0.1181 |

The cost estimate is not a provider invoice, and cache-read tokens are not
equivalent to full-price input tokens. The baseline nevertheless proves that the
mechanical path repeatedly invokes the model and carries a large persistent
context.

## Candidate

`scripts/deploy/release_runner_bridge.py` exposes three deterministic operations:

- `plan`: validate one existing CT137 packet and emit the exact immutable
  `preflight`/`execute` commands;
- `dispatch`: invoke exactly one controller phase, suppress raw logs, validate
  fresh phase-bound evidence and return a compact handoff;
- `handoff`: compact bounded technical/Test Runner evidence into the required
  five fields.

The bridge itself does not implement network, Git, provider, database, SSH or
deployment logic. Those operations remain owned by the existing canonical
controller. Routine success needs no policy-document read and no model call.

### Safety invariants

- evidence is accepted only from `<exact checkout>/.release-evidence`;
- execute requires the exact packet `release_id` as a separate confirmation;
- preflight accepts only `READY` or `BLOCKED`; execute accepts only
  `RELEASE_OK` or `BLOCKED`;
- stale evidence from an earlier invocation is rejected;
- evidence must match both packet `release_id` and exact SHA;
- an execute timeout or missing/stale evidence requires state reconciliation,
  not a blind retry;
- technical success stays `NOT READY` until matching evidence from the separate
  Test Runner is supplied through `handoff`.

### Measured synthetic run

| Metric | Plan | Handoff |
|---|---:|---:|
| Exit code | 0 | 0 |
| Elapsed time | 244.12 ms | 231.27 ms |
| Stdout size | 1,723 chars | 370 chars |
| Model calls inside candidate | 0 | 0 |
| Policy documents read | 0 | 0 |

An invalid packet digest returned exit code `1` and one 62-character structured
error: `release_packet_digest_mismatch`.

The completed fake-controller dispatch replay measured `131.34 ms` and `287`
JSON characters for preflight, then `106.96 ms` and `399` JSON characters for
execute. Both phases used zero model calls and read zero policy documents. These
are local control-plane measurements, not production latency claims.

## Verification

- `33` release/controller/bridge/governance unittests passed;
- `42` release workflow/plane/bridge pytest contracts passed;
- release-contract gate passed: Alembic chain (`162` revisions, head `0164`),
  Celery contract, migration ownership, Render dependencies and error journal;
- changed-file Ruff lint and format checks passed;
- Python compile and `git diff --check` passed;
- CI now compiles and tests the bridge;
- the Release Runner contract routes routine CT137 work through `dispatch` and
  permits bounded source retrieval only after a structured exception;
- incomplete technical evidence cannot bypass the required separate Test Runner
  acceptance marker.

## Result

The selective ECC hypothesis is supported for this seam, and the local candidate
is complete. A prepared release does not need an LLM between packet validation,
controller dispatch and handoff compaction. The existing deterministic
controllers already contain the complex implementation; the missing piece was a
small stable interface around them plus exception-only retrieval rules.

The local replay proves that the routine CT137 controller seam itself can use
zero model calls and bounded output. It does not imply that the current DEV
provider path is deterministic: the bridge is intentionally CT137-production
specific.

## Authorized DEV follow-up

The owner subsequently authorized one DEV-only experiment. Exact SHA
`b3b4c314750a7a2e3df89f526b92345d54c305d0` was fast-forwarded from base
`315e01320a0395b4c30a0f7738d3eccb01e5417e` to `origin/dev` with the canonical
project-bound GitHub credential. The change contained no migration or application
runtime modification.

### Exact runtime evidence

| Gate | Result |
|---|---|
| Remote branch | `origin/dev` exact SHA `b3b4c314750a7a2e3df89f526b92345d54c305d0` |
| GitHub CI | run `36298869875`, success, 7/7 jobs, 06:01:17Z-06:05:52Z |
| Vercel DEV | `dpl_EZDr2aAcEukvg1WWCLJg7XuX7mdM`, `READY`, exact SHA; 111.934 s |
| Render DEV API | `dep-dasb4r7pn0mc73fl6pvg`, `live`, exact SHA; 104.650 s |
| Render DEV worker | `dep-dasb4r60tbcc73el9olg`, `live`, exact SHA; 52.163 s |
| Public API | `/api/v1/health` returned `status=ok`, `render-development`, exact SHA |
| Public worker | root returned HTTP 200 and `ok` |
| Public frontend | `/login` returned HTTP 200 |
| Migration scope | none |

Both Render services remained on the existing `free` plan. No plan, billing,
environment, database, DNS or production setting was changed.

### Persistent-runner A arm

The existing persistent `Kamilya - Release Runner` received the same immutable
identity and performed read-only post-release reconciliation. It returned
`BLOCKED` before any external readback after 106.646 s.

Measured usage for that one turn:

| Metric | A arm |
|---|---:|
| Model | `gpt-6-luna` |
| Input tokens | 133,750 |
| Cache-read tokens included above | 132,864 |
| Output tokens | 855 |
| Command executions | 5 |
| Recorded source tool-output characters | 34,648 |
| External evidence verified | none |
| Final result | false `BLOCKED` (`AUTH_EXIT=112`) |

The runner loaded the stale contract from the shared primary checkout instead of
the packet's exact-SHA checkout, broadly read project documentation, entered the
irrelevant CT137/SSH path for a DEV packet, and then classified its own executor
access failure as the release blocker. The root executor successfully used the
same canonical GitHub helper immediately before this run, so the result is not
evidence of a bad project token or DEV outage.

### Interpretation limit

This is a decision-useful comparison, but not a symmetric two-deployment A/B.
Only one provider release was performed. The A arm reconciled that completed
release read-only; the B release was mechanically sequenced by the root because
no dedicated DEV controller exists yet. Therefore:

- the persistent LLM runner is conclusively unsuitable for the routine path;
- the CT137 deterministic bridge is validated locally and by exact-SHA CI;
- end-to-end zero-model-call DEV release savings are **not yet proven**;
- a dedicated DEV controller is the remaining deep-module seam if DEV releases
  also need zero-model-call execution.

## Decision

**GO for review/merge of the CT137 bridge and exception-only runner contract.**
The live DEV evidence confirms that the candidate is release-safe and that the
old persistent-runner behavior is both expensive and unreliable. Production was
not changed or authorized by this experiment.
