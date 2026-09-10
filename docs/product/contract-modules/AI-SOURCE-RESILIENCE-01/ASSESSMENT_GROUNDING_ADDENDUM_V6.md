# AI-SOURCE-RESILIENCE-01 assessment grounding — V6

Status: Accepted for bounded implementation, not release approval.
Date: 2026-09-10. Supersedes: assessment negative-space row of EPIC_V1 only.
Approved by: root under the owner's existing full-source/question-quality repair
and acceptance request. No new provider, data, infrastructure or billing authority.
Owner/writer: root. Reviewer: independent bounded worker and root integration.
Change control: EPIC_V1 procedure; accepted predecessors retained.

## Evidence and objective

Release042 normal queue completed17lessons/61MCQs; browser and a separate read-only
API probe found an unsupported predicate in one correct answer. Two fast synthetic
tests reproduce acceptance of an invented predicate and altered numeric value.
The unchanged assessment validator used60percent word-stem overlap, excluding digits.

Assessment owns only validation/prompting of question candidates. An accepted
correct answer must be a contiguous, token-boundary exact span of the server-owned
selected evidence after display-markup/case/whitespace normalization. Preserve
numeric values, negation and meaningful signs. Reject unsupported candidates through
the existing bounded retry/recovery seam, never by accepting a partial word overlap.
Explanation is the trusted display-text evidence, not a model-authored factual claim.
Focused recovery must not force a fixed6word answer: require extractive2–12word
answers and similar-length plausible options, retaining the existing quality gate.

Public schema unchanged. Data ownership remains tenant/job/lesson scoped; source
IDs server-owned. No DB migration, saved customer quiz edits, new inference verifier,
new dependency, higher retry/call limits, or silent fewer-than-minimum success.
This is conservative extractive support, not a general semantic-entailment proof;
methodologist review remains mandatory.

## Impact and acceptance

| Consumer | Compatibility/negative invariant | Verification |
|---|---|---|
| assessment generator/recovery | all acceptance paths use the same stricter validator | invented predicate/numeric/negation negative and extractive positive tests |
| question quality validator | keep balance/distractor/duplicate checks | existing assessment suites |
| pipeline/persistence | unchanged minimum count, save/cancel/quota behavior | pipeline and full regression |
| frontend | unchanged MCQ/explanation schema and review state | source-backed live candidate plus actual persisted browser readback |

Exit: root-reviewed tests, real affected-lesson candidate validation, exact release
gates and normal queued representative flow, then disposable cleanup. No client GO
from deployment success or word overlap alone.
