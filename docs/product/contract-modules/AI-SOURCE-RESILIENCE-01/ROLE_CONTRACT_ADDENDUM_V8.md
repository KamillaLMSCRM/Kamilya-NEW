# AI-SOURCE-RESILIENCE-01 role-contract addendum V8

Status: Accepted for implementation; release acceptance remains open.
Document version: V8. Supersedes: no earlier role-contract addendum.
Decision date: 2026-09-12.
Approved by: product owner instruction to implement the reviewed complex-source
repair. Root owns integration, evidence, Git and release decisions.

## Responsibility and user-visible contribution

The document passport classifies worksheet sections for course planning, and
the direct-source architect preserves those roles while allowing supporting
facts to enrich lessons whose subject remains grounded in primary material.
An ordinary methodologist can leave optional guidance blank; role ambiguity
must not be converted into a confident but unsupported curriculum decision.

Non-responsibilities: parsing source bytes, embedding/provider routing, lesson
prose, assessment generation, persistence, quotas, authorization, publication
and deployment.

## External interfaces

```text
build_document_passport(corpus) -> DocumentPassport
run_direct_architect(llm, corpus, ...) -> CourseStructure | DirectSourceError
```

Both interfaces remain source-compatible. This addendum changes validation
policy behind them; no API schema, database schema or provider contract changes.

## Inputs and outputs

| Direction | Name | Version | Validation | Sensitive fields |
| --- | --- | --- | --- | --- |
| Input | `DirectSourceCorpus` | existing | selected documents, chunks and worksheet headings | may contain tenant source text; never log or delegate |
| Output | `DocumentPassport` | existing | bounded roles and teachable capacity | aggregate metadata only |
| Output | `CourseStructure` | existing | selected documents, primary headings, lesson limits and role policy | course draft metadata |

The module is stateless and owns no database records. Tenant/object ownership is
enforced by upstream document selection and must not be weakened here.

## Invariants

- Primary learning content defines module and lesson subjects.
- Supporting sections may provide examples, attributes and comparisons inside a
  lesson that also cites required primary headings and the exact supporting
  heading used by that description.
- A supporting description must link those facts to the primary subject. A narrow
  possessive/anaphoric construction is accepted only when it begins with the
  relationship, names the supporting heading exactly and cites that heading.
- Merely naming a supporting worksheet, or mentioning generic SKUs, article
  numbers or prices, does not make a catalog-dominated description acceptable.
- A supporting-only subject in a course/module/lesson title or lesson objective is
  rejected by the existing direct-source error contract.
- Generic catalog objectives remain supporting-driven even when they share a broad
  word such as `product` with the lesson title.
- Relative size and reference columns are evidence, not absolute truth: a large
  learning sheet is not supporting merely because it contains price or ID fields.
- A much larger sheet with strong catalog/reference evidence at least as strong as
  learning evidence remains supporting relative to a strong primary sheet in the
  same document.
- Conflicting non-dominant evidence yields `unknown`; it is not silently forced to
  `supporting`.
- Strong learning markers such as `Product knowledge`, instructions or procedures
  prevent a large mixed learning sheet from being demoted merely because it also
  contains identifier and price columns.
- Existing selected-document, primary-heading, unsupported-action, lesson-count,
  cancellation and checkpoint guards remain active.
- Worksheet evidence is document-scoped. If a heading name is ambiguous across
  selected documents, the current string-only heading interface rejects the plan
  instead of borrowing evidence from another document.

## Error modes

| Error | Class | Caller behavior | Retry | Visible evidence |
| --- | --- | --- | --- | --- |
| Supporting section becomes the instructional subject | permanent plan validation | bounded architect correction, then stable failure | existing bounded policy | safe error code only |
| Section-role evidence conflicts | advisory classification | continue with existing low-confidence policy | none | aggregate passport confidence |
| Required primary grounding missing | permanent plan validation | bounded correction, then failure | existing bounded policy | safe error code only |

Descriptions are explanatory inputs to the lesson writer, not an authority to
override primary headings or objectives. Supporting headings in `relevant_headings`
are allowed only in addition to the existing required primary-heading contract and
the explicit subject-link rule above.

## Existing-module impact

| Affected module | Existing contract | Change | Compatibility | Regression evidence |
| --- | --- | --- | --- | --- |
| `document_passport` | deterministic section roles | compare strong reference and primary evidence within one document before using relative size | return type unchanged | mixed, large-learning, cross-document-peer and large-balanced-reference tests |
| `direct_source` | validate generated structure against passport | keep titles/objectives primary; allow only cited, subject-linked supporting detail in descriptions; reject cross-document heading ambiguity | public seam unchanged; deterministic ambiguity error added | valid enrichment plus adversarial description and name-collision tests |
| topic map, writer, assessment, checkpoints | consume accepted structure/corpus | no interface or file change | unchanged | affected-neighbor focused suite |

## Security, privacy and observability

No new logs, provider calls, credentials, storage or tenant identifiers are
introduced. Verification uses synthetic fixtures. A local aggregate passport run
may use an owner-provided workbook, but raw cells must not leave the workstation or
appear in evidence.

## Verification

| Level | Scenario | Required result |
| --- | --- | --- |
| Unit | conflicting `Collection/Description` and `Price/ID` signals | `unknown`, not forced supporting |
| Unit | large primary sheet with a price field | primary |
| Unit | much larger balanced reference sheet | supporting |
| Interface | primary lesson enriched by named supporting examples | accepted in one architect call |
| Negative space | standalone supporting subject, catalog-dominated description or objective, uncited SKU detail, same-name ownership shadow, cross-document heading ambiguity or missing primary heading | deterministic rejection preserved |
| Neighbor | direct-source/passport/map/writer-related focused suite | PASS |
| DEV integration | isolated Supabase application gate with synthetic data and exact cleanup | PASS before release |
| Local representative | full owner-provided workbook converted and passported without network | intended primary/supporting split retained |

## Rollout and rollback

Release requires the normal exact-SHA CI/image/provider/worker/browser gates and
a separately authorized production action. No migration is required. Rollback is
the previous application image; no data rollback exists. A successful structural
gate does not prove lesson or assessment quality for arbitrary documents, so a
separate end-to-end human acceptance remains mandatory.
