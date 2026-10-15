# Document content retrieval addendum V1

Accepted by Root under the owner's multilingual/multi-source validation request,
2026-10-15. Extends DOCUMENT_CONTENT_DIALOGUE_V1; its public contract is unchanged.

## Interface and invariants

- Inputs remain selected immutable current DocumentSource snapshots, authorized
  actor, question and bounded untrusted recall. Output remains verified evidence
  windows and the existing supported/not_found/conflict answer union.
- Retrieve a bounded opening window (chunks zero and one) per selected document.
  Prefer the longer opening body to a heading-only first chunk as fallback.
  Ranked lexical evidence has priority. Allocate one candidate per selected
  document before further candidates; fill remaining slots by ranked depth across
  documents rather than letting one document consume all spare slots. Deduplicate
  by chunk identity. Keep the previous eight-chunk/24000-character/16-handle cap.
- Pass a server-derived selected-source inventory with available evidence handles
  to the model. This inventory explains selection, not factual content or authority.
  Missing retrieved detail must not be described as an unselected document.
- Supported includes an evidence-grounded negative comparison (different scopes,
  or no conflicting value). Not_found means the requested conclusion cannot be
  established from excerpts. Silence about a value is not a conflicting value.
  Never infer precedence, universal absence, or applicability from a title.

## Negative space and failure modes

No public shape, migration, index/storage, permissions, model routing, budget,
provider deadline, retry, course/assignment mutation, voice or reserve change.
No translation/model call during retrieval, no post-hoc status rewriting, no
semantic guarantee from structural tests. Source/revision/hash checks and terminal
witness locks remain mandatory. Existing stale-source and provider errors retain
their behavior. Opening fallback is limited context, not full-document proof.

## Verification and recovery

Red tests reproduce heading-only fallback and five-source slot starvation;
regress exact hashes, tenant/revision scoping, bounded handles and full retained
chunk tails. Replay actual DEV retrieval without a model, then real-model tests
against frozen RU/KK TXT/MD/DOCX/PDF cases and a new independent holdout. Preserve
earlier failed answers. Run canonical isolated DEV RLS gates, ordinary browser
citation/download/reload checks and protected exact-source release gates.
Production acceptance uses synthetic QA only; previous history/learning and saved
routing/reserve state must remain unchanged. Rollback56 reads the same answer
shape/history; it restores earlier retrieval behavior, not repaired answers.

Root owns document_answers.py, its focused tests and this addendum. Independent
reviewer is read-only. Changes outside this seam require separate scope reasoning.
