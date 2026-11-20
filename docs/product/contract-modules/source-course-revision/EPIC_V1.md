# Course revision from an updated source

Product owner: Kamilya owner. Implementation, integration and test owner: root.
Authority: first product package, synthetic verification. Production has its
own release gate and requires an exact candidate.

## Critical journey

The methodologist compares two revisions of a document. The existing source
review identifies the affected lesson and tests and opens the derived draft
at the exact lesson. The existing editor prepares and previews the correction
before applying it. Language versions remain mandatory where configured.
Publishing follows the existing draft and review gates. The predecessor
release, its enrollments and all attempt evidence retain their exact IDs.

## Boundaries

- Source actuality owns the comparison, draft creation and the decision
  receipt. It only rebinds an old source span after verifying its original
  content hash, working-text hash and document revision. Unsupported or
  ambiguous references require manual review.
- The lesson editor owns proposal preview and application. Localizations own
  translation fields and language approval. The existing quiz editor owns
  changes to questions and grading. The release flow owns publication.
- No published rows, learner record, permissions, providers or schema changes.

## Verification

Change a single source rule in a two-lesson fixture. Prove the affected
lesson opens in the derived draft with verified replacement evidence. Prove
the unaffected lesson and translations retain their text and the predecessor
release and enrollment remain intact. Also cover legacy references, uncertain
locations, stale source decisions, reload and cross-tenant denial.
