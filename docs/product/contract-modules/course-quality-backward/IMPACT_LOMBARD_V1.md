# Original-source quality impact addendum V1

Status: accepted for implementation and gated delivery, 2026-10-19.
Root owner: current Kamilya orchestrator. Product authority: owner's explicit
request to reload the provided originals in synthetic QA, correct quality, verify
DEV and release one production packet; separate exact-three-draft cleanup approval.
Extends EPIC_V1 for this new task only; its historical synthetic-only scope and
expired per-run spending authorization are not reused as current authority.

## Interfaces and evidence

`DirectSourceCorpus -> build_evidence_source -> grounded realization ->
generate_block_assessment -> saved draft -> browser review` remains the chain.
No HTTP/DB/event interface changes; no new persistence owner or schema. Facts and
source locators remain immutable evidence; assessment axes may now represent
distinct explicit clauses of the same parent fact. Exact axis IDs, not merely the
parent fact ID, bind replacement/repair and critical-coverage audit. Existing
grounding/answer-key/exception/retry guards and no-padding policy remain required.
Quality policy v5 prevents mixing old and corrected resumable generation rules.

## Impact matrix

| Owner/module | Class | Allowed delta | Required negative space |
|---|---|---|---|
| Source application | Invariant | Preserve unheaded operational tables; filter cover navigation/signatures | Metadata/reference tables remain supporting; correction/actuality source identity preserved |
| Grounded realization | Invariant | Whitespace-only paragraphs and explicit lists after validation | No lost characters, amounts, conditions or exceptions; no new model calls |
| Assessment axes/semantic review | Invariant | Expand explicit operational list clauses, exact-axis recovery/repair and explicit missing coverage | Ordinary prose not multiplied; keys/evidence unchanged, no quota padding |
| Generation UI | Interface-compatible | Terminal/partial result with counts, bounded catalog and durable start-another reset | Do not hide real active/new jobs or cross-tenant source boundaries |
| Course catalog/guide | Presentation | Explicit own-course heading and list; neutral guide caption | Existing actions/roles/assets/captions/chapters retained |
| Auth, RBAC/RLS, schema, billing, provider route, learning evidence | None | No implementation change | Existing roles, tenant and completed learning preserved |

## Verification, errors and rollback

Independent original-file oracle plus red/green call-site fixtures. Source
normalization must be exercised before assessment derivation, not bypassed with
handwritten newline-bearing SourceFacts. Critical omissions remain visible and
cannot be relabeled completed simply to pass the UI. Fresh DEV model runs must be
reviewed for factual coverage, educational sequence, legibility and distinct
practical questions. Unit counts are not semantic acceptance.

Before deleting exact QA objects, verify stored-source bytes equal recoverable
local originals, all three courses are unpublished drafts, and full learning
history has no matching course. Use ordinary APIs; no force/purge/RLS bypass.
Old output snapshots stay private/ignored for comparative evidence. Original
files and unrelated records are never changed. New QA drafts remain explicitly
identified. No invitations or learner-result mutations in quality checks.

Deployment uses existing DEV Free/Free/Hobby and protected production procedure
only after hard gates. No new paid resources/plan/spend-limit changes. Compatible
rollback is current marker-aware65, not historical pre-kernel binaries. Root
alone accepts semantic quality and production readback. Stop on failed grounding,
data identity, isolation, learning preservation or release hard gate; record exact
failure and correct within scope, never relax the gate.
