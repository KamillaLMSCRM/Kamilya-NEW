# CQCL-001 critical journeys and acceptance

Status: Accepted for implementation and release verification

## Minimum acceptable quality

A run is accepted only when all applicable deterministic gates pass and root source
review finds no P0/P1 semantic defect. Question count is not a success metric.

### P0 defects — zero tolerance

- wrong correct answer;
- answer unsupported by cited source;
- condition, negation, permission or obligation reversed;
- learner-visible provider/meta instruction;
- cross-tenant/customer mutation or secret/PII exposure.

### P1 defects — zero tolerance among retained questions

- options do not answer the same question;
- unrelated true statements used as distractors;
- question belongs to another lesson/entity/source block;
- two options are defensibly correct;
- duplicate question/fact assessed without distinct learning purpose;
- explanation depends on answer position or contradicts the key.

### P2 outcomes — allowed only as explicit warning/review

- an assessable source contract remains uncovered after the bounded repair budget;
- a source block is unassessable because evidence is ambiguous/corrupt;
- useful draft survives with omitted weak questions;
- optional polish/style issue does not alter meaning.

## Repeatability gate

For each required source class, execute at least two fresh candidate generations from
the same frozen converted input and accepted configuration. Accept only if both runs:

- complete or save the documented reviewable-draft outcome;
- have zero P0/P1 retained defects;
- cover every assessable primary contract or report its exact uncovered ID;
- do not depend on favorable-run selection;
- preserve timing/model/token/cache counters where available.

Recorded-response offline replay must reproduce every retained/omitted decision without
provider calls. It validates determinism, not semantic correctness by itself.

## Journeys

### CJ-01 — Minimal source

Given one coherent paragraph with one assessable rule, generation creates one
proportional lesson and at most the defensible assessment supported by that paragraph.
It never pads to a default lesson/question count.

### CJ-02 — Lombard-like narrative PDF

Use the approved local source and production converter path. Validate normalized source
before generation. Every retained lesson/question maps to a coherent section; definitions,
conditions and exceptions remain intact; no TOC/image artifact becomes a lesson. Record
stage timing and compare two fresh runs.

### CJ-03 — Plus-like multi-sheet XLSX

Use the complete approved local workbook. Preserve primary-versus-supporting sheet roles,
entity/column ownership and adjacent narrative. No peer collection/product answer may
appear in another entity's question. Record stage timing and compare two fresh runs.

### CJ-04 — Unrelated true distractors

Replay the privacy-question defect: true source statements about reply/escalation are
invalid options for a personal-data handling question. The completion module must reject,
repair or omit them while preserving the immutable key/evidence.

### CJ-05 — Missing coverage

When a candidate is omitted, coverage names the exact assessable contract. One targeted
replacement may be requested. If still unresolved, save a reviewable draft with the
contract/reason; do not generate a generic filler question.

### CJ-06 — Provider degradation

Existing provider timeout/failover behavior and sanitized progress remain unchanged.
Semantic rejection cannot silently consume an unbounded provider retry budget.

## Evaluation layers

1. Deterministic contract/quality checks.
2. Source-topic and contract coverage.
3. Independent blind reviewer.
4. TypeSafe development-only report.
5. Root direct source review for every P0/P1 finding and oracle expectation.

Reviewer or TypeSafe PASS never overrides a source contradiction or missing coverage.
