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

This result does not prove end-to-end token savings for a real release because no
DEV/production deployment was executed and the root-agent work required to build
the pilot is outside the candidate runtime measurement. It proves that the
routine execution seam itself can use zero model calls and bounded output.

## Decision and remaining external proof

**Local decision: GO for review/merge.** Do not infer production approval from
this result. No DEV or production system, provider, database or deployment state
was changed by the pilot.

The remaining proof is one separately authorized DEV-only A/B release against
the same immutable packet:

1. current persistent Release Runner path;
2. deterministic bridge/controller path, with the LLM invoked only for the final
   root decision.

Compare model calls, input/cache/output tokens, elapsed time, first-pass success,
technical evidence completeness and product-acceptance result. The candidate is
ready for that external experiment; provider mutation remains outside this
local pilot.
