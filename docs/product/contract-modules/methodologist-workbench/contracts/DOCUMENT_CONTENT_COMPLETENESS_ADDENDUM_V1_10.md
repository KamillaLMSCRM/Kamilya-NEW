# Document-content answer completeness V1.10

Status: Accepted for implementation by Root,2026-10-16; not release acceptance.
Extends V1.8/V1.9. Product owner authorized completeness repair, DEV regression,
production rollout and live synthetic acceptance2026-10-16. Voice/reserve excluded.

## Evidence and decision

Production57 H57-03 failed twice; the local longer-deadline probe exhausted8192
generated tokens with no final text. A compact policy returned actor facts but
omitted both requested retention categories/periods despite declaring retention
and citing the facts. Preserve all failures and frozen corrected oracles.

Root selects one-inference private answer-parts, not another prompt-only clause,
critic, semantic retry or a larger deadline/token budget. R18's source-fact split
hid an actual conflict: therefore each requested dimension is compared across
sources in ONE part, not classified separately per source. No source-level status
may mask two opposing values on the same requested fact.

## Module and interface

Owner: existing document_answers module; Root implements/integrates. Independent
reviewer checks requirements/correctness/standards/complexity and real outputs.
Interface remains answer_document / public DocumentAnswer. Internally ModelAnswer
declares1..8unique requested_dimensions and exactly one bounded part per dimension.
Each part contains dimension, nonblank answer, citation handles, status. All
declared dimensions must be covered exactly once. A conservative multilingual
question matcher also requires clearly explicit actor/retention requests; it must
not infer action duration merely from a record-retention question or document text.
It is a bounded safeguard, not universal natural-language intent recognition.

Server assembles the public answer from the validated parts; it never appends an
unchecked separate summary. Unique server-owned citation handles are combined,
at most8; exact quotes/identity/index witnesses remain server-derived/revalidated.
Status is conflict if any requested part conflicts, otherwise not_found if any
requested part lacks evidence, otherwise supported. A not_found part must explain
its missing requested fact; partial evidence must not be silently omitted. Public
8000character answer/24000character raw JSON and all existing limits remain.

This structural gate detects omitted/duplicate parts, not a model lying within a
part. Nonblank text or a declared dimension is not semantic entailment. Independent
fact/scope/condition/language/conflict review remains mandatory. Unknown requests
still require all model-declared dimensions but are not claimed regex-complete.

## Ownership, impact and negative space

Stateless answer assembly only. Existing document_dialogue owns request key,
pending/completed/failed archive, actor/tenant/source locking and history. No new
table, migration, endpoint, public schema, UI, index or data owner. Invalid private
output follows generic502/invalid_response/refund path, never syntax repair or a
second model call. Existing transport-failure fallback unchanged; no change to
model/key/route/provider order/reasoning profile/45s attempt/60s overall/8192token
ceiling, budget admission/refund, tiers, resources, voice or saved reserveOFF.

Write scope: document_answers.py, its focused tests, owned isolated DEV fake
fixture/source manifest, this addendum/module index, existing execution plan,
release metadata and canonical current-state documents. Source witnesses/RLS/
security and neighboring assignment/lesson/generation behavior are protected.
Unexpected shared-provider or persistence changes stop for a revised addendum.

## Verification and rollout

1. Deterministic replay of the preserved incomplete completion must fail before
   accepting the repair; valid parts, missing/duplicate/unrequested dimensions,
   per-part evidence, merged bounds and real-conflict counterexample regressions.
2. Same managed-profile real-model local probes: H03 authority+retention, H04
   true3/5-day conflict, D16 unavailable-rival/injection; independently reviewed.
3. Full module/API/quality tests and fresh exact-source isolated Supabase DEV gate;
   no public QA writes concurrently with its neutrality interval.
4. Fresh no-history ordinary DEV regression42, plus independently frozen new
   multipart controls; actual browser/reload/source downloads/student denials.
5. Protected backend58 rollout only after accepted DEV; native56/public history
   remains compatible. Current57 rollback retained, actual switch NOT_RUN unless
   specifically exercised. Independent runtime/routing/ops and live synthetic
   production acceptance. No force-tag, broad cleanup or Proxmox.

Root alone accepts source/evidence and production GO. A failed live case remains
failed; no status-only acceptance, oracle relaxation or repeated unchanged calls.
Stop identical provider failures and choose a new measured hypothesis, not more
budget. Facts transfer to canonical owners; execution plan closes only after live
acceptance. No universal accuracy, long-document/OCR or SLA claim.

## DEV58 follow-up: question-bound conflict evidence

Root decision2026-10-16, after actual b73 DEV browser H57-03: completeness is
restored, but conditional deputy appointers were promoted into an unrequested
conflict. Retain that failed receipt. C58-01 explicitly asks deputy eligibility;
its differing exclusive appointment rules may legitimately conflict, so neither
global conflict suppression nor an expected-status rewrite is an acceptable fix.

Extend only the private AnswerPart with nullable conflict_evidence. A conflict
requires a literal current-question span and two distinct exact rule quotations
bound to this part's selected excerpt handles. Non-conflicts must omit/null it.
Server rejects missing, invented, identical, uncited or question-unbound evidence
through the existing invalid-response/refund path; it never relabels the answer.
Both positions may occur within one document or even one window. Exact binding
is NOT proof that the rules are semantically incompatible or responsive; retain
an explicit regression demonstrating that limitation and independent adjudication.
No proof text is persisted in the public answer or interpreted as instructions.

Narrow the existing authority policy to requested authorities, with ordinary
approval versus expressly requested replacement eligibility distinguished. No
extra inference, hidden repair, provider/routing/timeout/budget/schema change.
Required new gates: missing-proof RED, positive/negative bindings GREEN, H03/H04/
D16 actual managed-profile contrast plus explicit conditional eligibility control,
then the same fresh DEV/production acceptance; earlier gates do not prove the new
source delta. Owner also approved one temporary DEV QA methodologist2026-10-16,
no mail/existing-role changes, eventual exact account/own-history cleanup. Do not
delete legacy histories or raise the100-discussion limit to unblock evaluation.
