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
`scripts/ops/ct137_native_release.py`. It does not duplicate deployment logic and
cannot execute a release.

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

`scripts/deploy/release_runner_bridge.py` exposes two deterministic operations:

- `plan`: validate one existing CT137 packet and emit the exact immutable
  `preflight`/`execute` commands;
- `handoff`: compact bounded technical/Test Runner evidence into the required
  five fields.

It intentionally performs no network, Git, provider, database, SSH, deployment,
or document-reading operation.

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

## Verification

- `16` related release/controller/bridge tests passed;
- changed-file Ruff lint passed;
- Ruff format check passed;
- Python compile check passed;
- `git diff --check` passed;
- incomplete technical evidence cannot bypass the required separate Test Runner
  acceptance marker.

## Result

The selective ECC hypothesis is supported for this seam. A prepared release does
not need an LLM between packet validation, controller planning and handoff
compaction. The existing deterministic controllers already contain the complex
implementation; the missing piece is a small stable interface around them.

This result does not prove end-to-end token savings for a real release because no
DEV/production deployment was executed and the root-agent work required to build
the pilot is outside the candidate runtime measurement. It proves that the
routine execution seam itself can use zero model calls and bounded output.

## Recommended next experiment

Run one owner-approved DEV-only release twice against the same immutable packet:

1. current persistent Release Runner path;
2. deterministic bridge/controller path, with the LLM invoked only for the final
   root decision.

Compare model calls, input/cache/output tokens, elapsed time, first-pass success,
technical evidence completeness and product-acceptance result. Do not migrate
the production release path until that A/B run passes and the exception path is
reviewed.
