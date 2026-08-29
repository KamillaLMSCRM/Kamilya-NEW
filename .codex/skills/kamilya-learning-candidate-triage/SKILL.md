---
name: kamilya-learning-candidate-triage
description: Deterministically triage sanitized recurring Kamilya observations into inert learning candidates for root review. Use to propose ERRORS, test, rule, ADR, or skill follow-up without an LLM scheduler; do not persist source events, activate generated rules, handle secrets or PII, or mutate project and external state.
---

# Kamilya Learning Candidate Triage

Convert repeated sanitized observations into review candidates without claiming
that the observations are verified facts. This is a script-only, read-only,
fail-quiet stage of the controlled self-learning lifecycle.

## Safety boundary

- Accept one sanitized JSON envelope through stdin. The script has no filesystem,
  path, baseline-file, mail, browser, network, provider, or database input. It
  rejects oversized, malformed, unknown-field, sensitivity-marked, contact-like,
  path-like, and cross-project content before candidate formation.
- The script writes nothing. It prints candidates to stdout only when at least one
  new candidate exists. No candidates or only baseline-known candidates produce
  no output and exit successfully.
- Output is `CANDIDATE_ONLY`. It is not evidence, an `ERRORS.md` entry, an active
  rule, a skill, an ADR, a test result, an approval, or permission to mutate.
- Do not connect the script to a scheduler, hook, CI job, provider, or notification
  channel under this skill. Any activation is a separate reviewed change. A
  periodic LLM task additionally requires the explicit owner gate defined in
  `AGENTS.md`.
- Reject unsafe, unknown, malformed, cross-project, or sensitivity-marked input
  instead of attempting to sanitize arbitrary payloads.

## Input contract

Each event in the stdin envelope must contain only:

```json
{
  "event_id": "EVT-0000000000000001",
  "observed_at": "2026-08-23T10:00:00Z",
  "project": "Kamilya-NEW",
  "kind": "TEST_FAILURE",
  "fingerprint": "OBS-a1b2c3d4e5f60708",
  "error_class": "TIMEOUT",
  "evidence_label": "NOT VERIFIED",
  "source_type": "agent_report",
  "source_ref": "REF-0000000000000001",
  "sensitive": false
}
```

The complete envelope contains exactly `schema_version: 1`, an `events` array of
the objects above, and a `reviewed_revisions` array.

Allowed projects are `Kamilya-NEW` and `kamilya-landing`. Event, observation, and
source references are opaque hexadecimal IDs with fixed `EVT-`, `OBS-`, and
`REF-` prefixes; arbitrary text, paths, contacts, tenant IDs, and payload-derived
values are forbidden. Error classes use a reviewed finite vocabulary. Source type
and evidence label must be a permitted pair. Timestamps require a timezone and are
normalized to canonical UTC before deduplication and revision hashing.

Historical sources such as agent reports, plans, handoffs, memory, and Graphify
remain contextual. Git/source, test, runtime, provider, and current owner evidence
may establish that direct evidence is present, but the script still cannot verify
root cause, fix, regression, or current relevance.

## Run

```powershell
Get-Content -Raw <sanitized-envelope.json> |
  python .codex\skills\kamilya-learning-candidate-triage\scripts\collect_candidates.py
```

The optional reviewed baseline is supplied inside the same stdin envelope and uses
this exact schema:

```json
{
  "schema_version": 1,
  "reviewed_revisions": [
    {
      "candidate_id": "LC-00000000000000000000",
      "revision_id": "LR-00000000000000000000"
    }
  ]
}
```

The stable candidate ID represents the observation class. The revision ID includes
the deduplicated event identities, timestamps, source types, references, and
evidence labels. The script suppresses only an exact reviewed candidate/revision
pair. The script has no persistence mechanism and cannot update a baseline.

`distinct_reported_refs` means only that different opaque references were supplied;
it does not claim organizational or evidentiary independence. Genuine source
independence remains an explicit root-review gate.

## Candidate interpretation

- `UNVERIFIED_REPORT_PATTERN`: repetition exists only in contextual reports. The
  next gate is independent source/test/provider/runtime evidence.
- `DIRECT_EVIDENCE_PRESENT`: at least one permitted direct evidence event exists.
  The next gate remains root verification of symptom, root cause, fix, and a
  proportionate regression check.

Suggested destinations are advisory:

- recurring confirmed failure -> `ERRORS.md` plus a deterministic test/CI/script
  invariant when possible;
- repeatable specialized procedure -> reviewed project skill;
- project-wide durable rule -> governing `AGENTS.md`;
- architectural decision -> ADR;
- unresolved review finding -> no persistence until reproduced and verified.

The root decides whether a candidate is discarded, investigated, merged with an
existing entry, or promoted through an ordinary reviewed diff. Never create a
parallel truth registry.

## Review contract

For every emitted candidate, the root checks:

1. scope and redaction;
2. whether sources are genuinely independent;
3. direct evidence appropriate to the claim;
4. duplicate coverage in existing canonical rules, errors, tests, ADRs, or skills;
5. verified symptom, root cause, fix, and regression evidence;
6. exact destination and one-writer ownership;
7. approval gates for cost, external access, production, secrets/PII, publication,
   scheduling, or destructive actions.

If any gate is missing, keep the item inert or discard it. Do not turn candidate
frequency or confidence into authority.
