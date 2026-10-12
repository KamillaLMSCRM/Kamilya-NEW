# Course and assessment quality benchmark — 2026-10-12

## Decision

**DEV and bounded production0.11.44 engineering acceptance CLOSED.
NOT marketing proof or measured human-efficiency evidence.**
Runtime candidate97f4efd2834c9d6bb0056f848b79cb7ecbf85816 passed actual DEV
generation and ordinary-methodologist editor/every-quiz acceptance on the frozen
866-word source:10 lessons/20 questions,23/23 meanings,27/27 labelled table
relationships. The new fixture is absent from all116 tenant-scoped tables;
permanent QA9-table fingerprints are unchanged. Following the owner's exact
approval,11 old orphan embeddings were removed under the non-bypass runtime
role after rollback proof; old tenant also has0 rows across all116 tables.
That DEV phase did not change production. The separately authorized production44
rollout and bounded real-generation acceptance are recorded in the final section;
earlier sections preserve historical runs, including blocked and rejected states.

Initial algorithm phase:
Eight real first-attempt generations exposed source-loss and teaching defects.
The first correction cycle and its failures remain below. A subsequent ten-run
FAQ/matrix cycle corrected FAQ answer ownership, stopped unchanged repairs and
diversified table targets. Final-source repeats preserve source semantics and
cover each lesson. A further bounded source-peer correction restores reporting:
two fresh matrix attempts retain all four selected questions, the second on the
final hardened code. FAQ first-pass acceptance remains variable (two/three);
full source assessment and same-version stability are not established.
No deployment, tenant, provider-plan or landing-page mutation occurred during
that initial algorithm phase. Later DEV-only deployment/fixtures are recorded below.

Source baseline: `07b70b4440f5266a5a47faa453edd642aba5add3` in
`.worktrees/learner-presentation-release-20261010`. This is NOT a new runtime SHA.
The primary checkout was preserved. `LESSONS.md` was not found in this repository.

## Frozen sources and evaluation protocol

Fixture: `apps/api/tests/fixtures/course_benchmark_v1.json`, SHA256
`36dac564b70439907869cc752ef6abed02d1314c6b366fe06afec54f30dde0e9`.
All eight sources are synthetic Russian documents with **fictional rules**, not
product documentation, actual prices, customer data or approved legal terms.
The sources contain 81–122 whitespace-delimited words each; complexity refers to
logic, not document length. This pilot does not represent long corporate manuals.

| Case | Level / document type | Intended outcome | Gold source clusters |
|---|---|---|---:|
| brief-policy-01 | Low / short policy | Draft | 7 |
| sop-02 | Low / numbered procedure | Draft | 7 |
| faq-03 | Medium / FAQ; holdout | Draft | 5 |
| matrix-04 | Medium / package matrix plus narrative rules | Draft | 8 |
| escalation-05 | Medium / escalation policy; holdout | Draft | 7 |
| conditions-06 | High / thresholds, exceptions, deadlines | Draft | 7 |
| sparse-07 | High / insufficient catalogue; holdout | Review, no invented quiz | 0 |
| conflict-08 | High / explicitly unresolved competing rules | Review, no selected rule | 0 |

An independent leaf author froze source-owned quotations and prohibited claims
before seeing model outputs. Gold annotations are never sent to the generation
provider. An independent AI reviewer checked outputs against sources; root
adjudicated findings directly, including correcting an initial false omission
finding in the SOP. Neither agent review nor quote matching is a human baseline.

Quality dimensions are separate: preservation of rules/exceptions; order of
actions; unique correct key; plausible, unambiguously wrong distractors;
explanation relevance; coverage of assessable lessons; refusal on bad input.
Literal quotation recall is a diagnostic, not semantic accuracy. For example,
the candidate table reconstructs rows as labelled facts: literal full-row
quotations remain absent even though all 12 values are now present.

## Execution scope

The harness runs the actual `generate_evidence_course` application seam with the
existing DeepSeek route, temperature0.2, max output8192, no alternative provider,
transport retries0, HTTP-call cap30 per case, provider timeout60s, case timeout360s.
Provider billing configuration, resources, spend limits and model routing were
not changed. Requested model: `deepseek-v4-flash`; response alias: `deepseek-flash`.
Internal validation/assessment repairs are included in call counts and elapsed
time, not discarded as hidden retries. Each saved case is outer attempt1.

Embedding retrieval is intentionally unavailable. Timing starts before source
corpus construction and planning, after process imports. It includes realization,
assessment generation, validation and repairs. It excludes upload, production
conversion/Docling, database, queue, browser, editor work, publication and learner
effectiveness. It is **not** document-to-published-course user time.

Raw synthetic receipts are retained append-only in the ignored local folder
`.release-evidence/COURSE-BENCH-20261012/`: first outputs, input, plan, request
hashes, response traces, call-level timings/tokens, flags and review reports.
Output directories must be new; failed runs are never overwritten.

Reproduction from this worktree, using the canonical project Python:

```powershell
& 'C:\Kamilya New\Kamilya-NEW\.venv\Scripts\python.exe' -m scripts.dev.course_quality_eval.benchmark --output-dir .release-evidence/COURSE-BENCH-NEW/offline
& 'C:\Kamilya New\Kamilya-NEW\.venv\Scripts\python.exe' -m scripts.dev.course_quality_eval.benchmark --replay-dir .release-evidence/COURSE-BENCH-20261012/live-candidate-v1 --output-dir .release-evidence/COURSE-BENCH-NEW/replay --case sop-02 --case matrix-04 --case conditions-06 --case conflict-08
```

`--live --env-file <canonical .env>` is an explicitly cost-authorized generation,
not an ordinary offline test. It must use a new output directory and preserve
HTTP/validation failures. The source-only ZIP is
`Kamilya-course-benchmark-sources-20261012.zip` in the evidence directory,
SHA256 `14f3a0f35194417f84fdbe53df8b3b328ba67ebd75875f743220852c1a2fa77b`;
18 entries (eight PDFs, eight originals, manifest, fictional-source warning).

## Real baseline — all eight cases retained

Runtime fingerprint (AI Python source + runner + fixture):
`4b23a3cba122d3e7b93cf80ccc0ce188c25752f760eb596912913b255026f518`.
Evidence: `live-baseline-v1/{manifest,metrics}.json` and per-case outputs.

| Case | Wall seconds | HTTP calls | Lessons / questions | Generator publishable | Root/source review finding |
|---|---:|---:|---|---|---|
| brief-policy-01 | 10.647 | 4 | 1 / 1 | Yes | Source rules preserved |
| sop-02 | 20.736 | 7 | 1 / 2 | No | Steps appeared 5→1→2→3→4; longest-key warning |
| faq-03 | 29.027 | 13 | 1 / 0 | No | Source meaning retained; no usable assessment |
| matrix-04 | 9.143 | 4 | 1 / 1 | Yes | All three package rows omitted despite publishable flag |
| escalation-05 | 11.419 | 4 | 1 / 1 | Yes | Source escalation conditions preserved |
| conditions-06 | 11.438 | 4 | 1 / 1 | Yes | Conditions preserved; percentage mislabeled financial |
| sparse-07 | 21.100 | 8 | 1 / 0 | No | No invented quiz; expensive negative control |
| conflict-08 | 20.386 | 7 | 1 / 2 | No | One answer chose a competing rule despite unresolved priority |

Total133.896s; median over all eight15.912s; range9.143–29.027s.
Median over the six positive documents11.4285s. These populations must not be
mixed. **51 HTTP calls**, **70,015 input / 20,215 output tokens**. Actual billed
USD is unknown: no invoice/pricing-bound calculation was captured; unknown is
not zero. Results are first-attempt samples, not p95 latency or repeatability.

Baseline reviewer inspected41 semantic source clusters and found the three
table-row clusters missing. Its initial four question-key checks were not all
eight generated questions. Neither38/41 nor3/4 is product-wide factual accuracy.
An accepted refusal is not a successfully generated course.

## Corrections and fresh affected-case evaluation

1. Preserve an explicit contiguous numbered procedure1..N from one document,
   revision and section in source order. Hash-sorted evidence IDs and writer
   grouping no longer reorder these procedures. Unnumbered prose and unrelated
   scopes retain their existing path.
2. Parse ordinary rectangular Markdown tables into row/column/source-owned
   facts, retaining adjacent prose and existing worksheet primary/supporting
   roles. Reject ragged tables before provider calls rather than dropping cells.
   This does not prove OCR, PDF table reconstruction or arbitrary merged cells.
   Final review also reproduced adjacent-table loss (1FAIL/6PASS): a second
   table without intervening prose was swallowed by the first table's removal
   range. The corrected parser stops at the next header/separator pair and
   deduplicates identical same-heading cell facts without suppressing different
   values. Focused source/application/backward regressions61PASS.
3. Stop before paid generation when an admitted source explicitly declares
   unresolved rule priority and prohibits automated decision use. This is a
   narrow notice detector, **not universal semantic contradiction detection**.
4. Do not classify bare percentages as financial conditions; explicit financial
   vocabulary remains supported. The generic classifier is not a complete domain
   ontology, and other ambiguous wording still needs review.

Fresh-generation candidate runtime fingerprint:
`fad9409c6745c0064e2dbbd4091b300b5c1375249bff7f44e1cc78e0cebcbeb1`.
Evidence: `live-candidate-v1/{manifest,metrics}.json`, per-case results and
`independent-candidate-review.json`. Independent AI review plus root readback:

| Case | Baseline → candidate seconds | Candidate HTTP | Fresh observed result | Remaining limitation |
|---|---|---:|---|---|
| sop-02 | 20.736 → 21.103 | 7 | Steps1..5; seven source clusters; three correct keys | Two of three keys are longest; heuristic signal remains, not a proven exploit |
| matrix-04 | 9.143 → 52.560 | 26 | All12 table values and five adjacent rules; two clear keys | Narrative lesson has no retained question; NOT publishable |
| conditions-06 | 11.438 → 11.520 | 4 | Seven source clusters preserved; correct key; no financial label | One question does not test every exception |
| conflict-08 | 20.386 → 0.004 | 0 | `source_rule_priority_requires_confirmation`, no generated key | Expected rejection, not a generated-content success |

Candidate total85.187s;37 HTTP calls;47,629 input /11,736 output tokens.
After the adjacent-table correction, all four candidate cases were replayed from
these captured responses: three generated outputs plus the expected conflict
stop,37 captured calls,0 HTTP calls,0 live fallback. Final replay runtime
fingerprint `5ccc6d0d99b16988191e30606564fb48100eb595cac996d80c5572cf4ff12e7a`.
This replay verifies the final code path, not new generation latency or quality
variance; its milliseconds are excluded from live speed figures.
All live work in this pilot:88 HTTP calls,117,644 input /31,951 output tokens.
No monetary saving or faster overall algorithm is established. The matrix became
more complete and slower; comparing its old incomplete output to a complete
candidate as equal work would be misleading.

Generated positive candidate content was reviewed in31 finer-grained semantic
clusters (7 SOP +17 matrix +7 conditions); all were found preserved. Six keys and
18 distractors were inspected; no wrong key or ambiguous distractor was found in
this bounded sample. Conflict safety assertions are counted separately, not as
preserved generated content. These are inspected-case counts, not a “100% accurate”
product claim or a human expert certificate.

## Conversion and artifact checks

Source pack contains fourTXT, fourMarkdown and eight one-page searchablePDF
versions of the same eight sources; PDF variants are not eight independent cases.
Every PDF page was rendered and visually inspected; matrix layout is readable.
Gold answers are excluded from PDFs and the handoff source pack.

Actual local conversion fallback:16 successful extractions; TXT/MD0.000196–0.000337s,
PDF0.004571–0.177361s (first PDF includes initialization). Original texts preserve
41/41 literal gold quotations. PDFs preserve38/41 literal quotations: three matrix
rows lose exact Markdown representation under pypdf. This is not yet a measured
PDF-to-source-complete-course result. No OCR, scanned PDF, DOCX, XLSX, Kazakh,
long document, production converter or peak-memory benchmark was performed.
DOCX export was not substituted with unverified output when no bundled rendering
compiler was found.

## Regression and navigation evidence

- Procedure regression: old code1FAIL/4PASS; corrected5PASS; saved SOP replay
  restores order without new paid calls.
- Explicit-priority preflight: old code2FAIL/3PASS; corrected5PASS; NoNetwork
  checks prove the stop precedes generation and embeddings.
- Percentage context: old code4FAIL/2PASS; corrected6PASS.
- Final focused changed-file/regression selection31PASS. Broad evidence,
  assessment, source-presentation and new-regression selection424PASS6.31s.
- AI-COURSE-01 canonical required selectors25PASS3.50s (parametrized selectors;
  overlapping counts must not be added as unique tests).
- Canonical Python quality baseline PASS: existing ruff1008/mypy2201 debt counts,
  not a claim that the repository has zero lint/type errors. No exemptions added.
- One broad command used a nonexistent legacy filename and collected no tests;
  corrected commands above are the actual runs. An earlier unsupported pytest
  flag was removed; no test skipped to make a gate green.
- Captured holdout replay: escalation/sparse succeed with0 HTTP. FAQ replay fails
  after captured review validation rejection: the reused replay adapter raises
  RuntimeError when the captured response queue is exhausted instead of the live
  client’s provider-failure branch. This replay is **NOT** a FAQ regression PASS.
  Baseline zero-question FAQ and its failure traces remain retained; no network
  fallback or paid retry was used to hide the mismatch.
- CodeGraph1.6.1 navigated the actual generation seam and classifier consumers;
  source was the oracle. Final sync1.088s body /7.939s reported total, exclusion
  audit PASS. Static navigation is not runtime proof or a token-saving result.
- No DB integration, DEV application gate, full CI, browser acceptance, Git push
  or release occurred. These remain required before a production release.

## Human comparison protocol — not yet measured

Use at least three actual methodologists and six paired source scenarios, with
matched variants and randomized/counterbalanced allocation to avoid learning
from an earlier answer. Eighteen paired comparisons is the first useful target,
not an already completed experiment. Freeze sources, acceptance rubric and
reviewer instructions before the run; blind reviewers to the preparation arm.

Both arms must meet the same acceptance standard: no unsupported mandatory rule,
no critical omission, correct conditions/exceptions/procedure order, one unique
key per MCQ, clear wrong options, relevant explanations and sufficient topic
coverage. Do not force either arm to pad question quotas. Preserve failed first
attempts and count every repair up to acceptance or explicit failure.

Record separately: source reading, brief/input/upload, draft preparation or AI
wait, editor review, correction, LMS entry/import and final acceptance. Record
accepted output volume, unsupported claims, critical omissions, ambiguous keys,
correction count, provider calls/tokens and actual monetary cost when available.
No AI roleplay is a substitute for human work or independent human review.

For each pair: `AI_total = input + generation_wait + review + correction + entry`;
`time_saved = human_total - AI_total`; `saving_pct = time_saved / human_total *100`.
Report the median paired speed ratio `human_total / AI_total`, sample size,
distribution, failure rate, date/model, source size/types and reviewer agreement.
Do not use this pilot’s LLM seconds as the denominator for a human speedup claim.

## Next bounded improvement cycle and landing claim gate

1. Extend the bounded FAQ/matrix corrections below: improve acceptance of a
   selected reporting axis without using other attributes as wrong answers;
   prevent unsupported prerequisite distractors in FAQ. Preserve rejection gates,
   first failures and separate source coverage from assessed knowledge coverage.
2. Compare equivalent accepted output, calls, tokens and repeated latency. The
   latest matrix uses12 calls rather than26, but question families/counts changed;
   this is not a matched-output efficiency or human-speedup experiment.
3. Expand to multi-page procedures, policies with references, scanned/noisyPDF,
   DOCX/XLSX and Russian/Kazakh mixed language. First validate actual conversion,
   chunk/revision provenance, long-source coverage and failure handling; then
   run end-to-end DEV with existing resources and canonical cleanup.
4. Run the paired human protocol and obtain independent human quality review.
5. Only then propose owner-approved landing copy tied to the exact experiment.

Today defensible **internal** wording: “In a synthetic Russian short-document
pilot, eight first generation attempts took9.14–29.03s at the algorithm seam;
quality review found defects and produced bounded corrections.” It is not an
appropriate unqualified product promise. Do NOT publish “N times faster than a
methodologist”, “100% accuracy”, “course ready in16 seconds”, or a universal
cost-saving percentage from this pilot. Human effectiveness, editor time and
ready-to-publish end-to-end performance remain **NOT MEASURED**.

## Follow-up: FAQ ownership, repair progress and table diversity

Frozen suite/source gold unchanged. Final-source runtime fingerprint:
`c1447127d4dcdb35ce8f9000700616c17d05140cf7f16933c8c781913f514358`.
This fingerprint includes AI source/runner/fixture, not a committed/released SHA.

Implemented locally:

- A leading unquoted FAQ question supplies the required prompt; its complete
  exact answer supplies the immutable key. Conditions, exceptions, uncertainty
  and evidence identity remain intact. A bare narrative question is not an
  answer. Explicit attributes containing legitimate quoted questions retain
  their existing behavior. Embedded quoted/multiple/truncated Q/A pairs are
  outside the bounded splitter, not proof of universal FAQ support.
- An unchanged rejected repair, including mere option reordering, keeps its
  omission and original reasons plus `assessment_repair_no_progress`; it does
  not purchase another semantic/constraint judgment. Changed repairs still
  undergo both gates. No accepted-question quota is manufactured.
- Author/repair instructions distinguish two independent misconceptions from
  cosmetic rewrites and forbid new prerequisites as a substitute for an explicit
  source contradiction. The same provider/model/settings are used; gates are
  not weakened. Model adherence remains imperfect, as retained failures show.
- Entity-first table selection now prefers an untested attribute within each
  entity. Stable source order breaks ties; single-attribute tables fall back
  normally. The three-question lesson cap remains unchanged.

### All fresh follow-up attempts, including intermediate omissions

Each cell lists seconds / HTTP calls / retained questions. All ten attempts are
retained; no lucky output replaces an earlier attempt. One outer attempt per
case per batch; internal schema/review/repair calls are counted separately.

| Batch | FAQ108 words | Matrix122 words | Interpretation |
|---|---|---|---|
| v2 |11.470 /4 /3|25.353 /14 /4| FAQ ownership and repair guard; matrix still all participant targets |
| v2-repeat |18.241 /8 /1|26.454 /14 /4| FAQ invented prerequisites correctly rejected; no-progress stop observed |
| v3 |12.800 /4 /3|26.809 /14 /4| More explicit source-condition author instructions; unchanged table selection |
| v4 final source |26.869 /7 /2|22.495 /12 /3| Diverse table selection; reporting candidate inadmissible |
| v4-repeat final source |12.534 /4 /3|21.530 /12 /3| Same final code; reporting candidate still inadmissible |

v2 fingerprint `ec7e6fb8097d5041b9c02f8af558225a0e11ac25108758275c15f516a27db281`;
v3 fingerprint `66d795c4cefbcbe99597b0b17047b110ee190f144334cdcc5268c907b3d24458`.
Follow-up total:93 HTTP calls,130,043 input/30,306 output tokens,204.555s summed
algorithm wall time. Actual monetary charge is UNKNOWN, not zero. Whole pilot
including the original cycle:181 calls,247,687 input/62,257 output tokens.
No401/402/403/429 or HTTP errors occurred in these ten attempts. Model request
and response alias remain `deepseek-v4-flash` / `deepseek-flash`; temperature0.2,
max8192 output tokens, no transport retries,30-call/360s per-case caps.

### Source and teaching review — distinct denominators

Independent cheap AI reviewer plus root/source adjudication inspected both
final-source runs. Per run: all five FAQ semantic clusters and all12 table cells
plus five matrix narrative rules remain in full lesson content. Across two runs
this is44/44 inspected source-semantic clusters, **not44 assessed concepts and
not a universal accuracy rate**. Eleven accepted keys are source-grounded;
26 wrong options were inspected without an established ambiguity. No independent
human reviewer or learner-outcome measurement was performed.

FAQ final runs assess two/three of three selected axes, from five source
clusters; the remaining two clusters are deliberately content-only under the
density policy. Matrix selects participant limit, reporting, practice and the
over-limit rule; accepts participant limit, practice and the over-limit rule.
The reporting candidate mixes reporting with practice/retention and is omitted
as `no_admissible_candidate`, not force-accepted. Nine other table axes are
density-omitted. All three learner-visible lessons across the two source cases
have assessments, but selected-axis acceptance and full pedagogical coverage
remain incomplete.

Reviewer findings were adjudicated against source: literal quote misses in
`signals.json` are not semantic loss when reformulated lesson text preserves
meaning. A deterministic `evidence_result.assessment` is not a second persisted
quiz: `to_generation_artifacts()` maps the realized course/assessment to the
single existing persistence contract. No fields or gates were removed based on
these withdrawn hypotheses. Artifact-level `independent_review=NOT_REVIEWED`
was written before independent review and left unchanged with the raw artifacts;
this report records the separate AI review without implying human evaluation.

### Regression and replay gates

- FAQ baseline RED6FAIL; source ownership, bare-question and negative splitter
  cases now PASS. An overly broad intermediate question-value filter was
  narrowed to auto-narrative attributes to preserve legitimate explicit keys.
- No-progress regression RED1FAIL before the guard; unchanged/reordered guard
  controls and changed-repair controls PASS. Existing request-count assertions
  were updated only for the intended removal of duplicate review calls;
  rejection/dropped-question assertions remain. Root corrected a misplaced test
  block before final verification; that harness error was not a product defect.
- Diversity RED2FAIL/1PASS, then PASS for one/two/three available attributes,
  with three distinct entities and the original budget. Reporting cross-attribute
  rejection has an explicit retained regression; refusal is not generation success.
- Final broad/journey/quality results are recorded in the machine-readable
  companion and ledger. Test counts overlap and must not be summed.
- Final v4/v4-repeat replay used35 captured calls,0 HTTP/fallback, and retained
  exactly the corresponding outputs. Unaffected SOP/conditions replay used11
  captured calls; explicit priority-conflict input stopped before any call.
  Offline replay timing does not measure provider latency or validate new prompt
  effectiveness; the fresh attempts above do.
- CodeGraph1.6.1 final sync1.095s body/7.846s reported total, exclusion audit PASS.
  No unresolved cross-language relationship justified Graphify work; no agent
  token-saving or subscription-cost claim is supported.

At the end of the v4 cycle: improve selected reporting-axis recovery and first-pass FAQ distractors;
then expand to long/mixed-format sources and actual conversion/DEV/editor flows,
followed by the paired human protocol. This package is locally measured, not
production-released and not yet defensible public comparative marketing proof.

## Follow-up: source-owned table peer alternatives

The reporting omission originated before semantic review: provider alternatives
mixed reporting with practice/retention, so materialization correctly refused
them. Repeating that authoring without new source structure did not fix it.
The correction constructs a candidate, **not an accepted question**, from two
distinct values in the same column of the same document/revision/table within
the lesson's primary facts. The immutable source prompt/key/evidence and both
blind semantic review and constraint audit remain mandatory.

This narrow path accepts only simple certain text attributes. Explicit table
identity is mandatory; a sheet can contain multiple tables and is insufficient.
Numeric row identity is normalized (`2` and `02` are one row). Duplicate subjects,
missing coordinates/revision, ambiguous/merged rows, uncertain/low-confidence
cells, compound conditional values and supporting-only facts retain provider
authoring. Numeric/rule fields and mixed qualifying/nonqualifying groups also
retain the existing authoring path. No service/interface/provider change,
additional repair loop, padding or review exemption was introduced.

### Fresh attempts and bounded quality readback

| Source version | Runtime fingerprint | Algorithm seconds | HTTP | Selected/accepted |
|---|---|---:|---:|---:|
| v5, before final identity hardening | `2a59773e7a359f685466f6866b09772f9f60b212434fdac7afb84c837c8bab8c` |28.017|13|4/4|
| v6, final code | `bb307ae54b72cb7496c5b3e839ca5742db2be1c0a8ed2ebd71f3da59f8d8cfe6` |30.155|13|4/4|

Each is one outer attempt; all internal HTTP calls are counted. These are two
slightly different source versions, **not pass-squared/same-version stability**.
Each preserves all12 matrix cells and five narrative rules in the two lessons;
the table lesson has three questions and the rules lesson one. Independent
read-only AI review plus root/source adjudication checked34 source clusters,
eight exact-source keys and16 distractors across the two outputs without an
established ambiguity. Human/source accuracy remains unmeasured. Nine other
table axes are deliberately omitted under the unchanged density cap, so4/4
selected-axis acceptance does not mean every fact has a question. A source-peer
candidate is used for reporting once per attempt; the other three candidates
are model-authored. Both required review gates run for all accepted questions.

Literal quote recall remains5/8 (0.625): three full table-row quotes disappear
when rendered as labelled cells, but their values/relationships are preserved.
The longest-correct-option heuristic hits1/4 in v5 and0/4 in v6. Both observations
remain in raw signals; neither is silently rewritten as semantic loss or a
universal teaching-quality score. Raw artifact `NOT_REVIEWED` fields describe
their generation-time state; the independent AI review is recorded here, not
misrepresented as an independent human evaluation.

These two attempts cost26 HTTP calls,32,860 input/6,487 output tokens and58.172s
summed algorithm time. No HTTP errors or transport retries occurred. Actual
monetary charges remain UNKNOWN. Whole pilot including every earlier attempt:
207 HTTP calls,280,547 input/68,744 output tokens. Model route/settings and billing
configuration are unchanged. The previous v4 outputs had three questions and
12 calls, so the new four-question result is **not a matched-output speedup**.

### Final verification and navigation evidence

- Initial table-peer positive/reviewer controls: RED2FAIL/14PASS, then16PASS.
  Independent review found sheet-only identity insufficient; new sheet-only
  and row-alias regressions: RED2FAIL/16PASS, then18PASS. Reviewer-outage control
  cannot accept source-built questions without independent judgment.
- Final broader selected suite456PASS/8.00s; canonical13 journey selectors
  yield27 parametrized PASS/4.41s. Counts overlap; do not add them. Quality
  baseline PASS with unchanged existing debt (Ruff1008/Mypy2201). Diff whitespace
  gate PASS; no CI/DB/DEV/browser/release claim.
- Replay of v5 on final v6 consumes13 captured calls and exactly matches course,
  assessment, publishability and assessment audit. Replay of the fresh v6 control
  also consumes13 captures and matches those four fields exactly. FAQ v4-repeat
  replay consumes4 captures, preserves the same three questions and all four
  output fields except the intentional additive `source_peer_candidates=0`
  audit counter. All three replay runs use0 HTTP/fallback; replay timings are
  not live/provider latency measurements.
- CodeGraph preflight reported `NOT_READY: Required local index/receipt missing`
  for the combined preparation receipt, while the local CodeGraph SDK/index
  remained usable. Bounded search/callers narrowed `_parse_axis_questions`;
  graph callers showed tests but missed its dynamic `partial` binding. Source
  confirmed the decisive runtime consumer; edges were not treated as complete.
  Final CodeGraph1.6.1 sync2.401s body/13.205s reported total, exclusion audit PASS.
  This Python-only seam needed no Graphify expansion. Token savings, agent
  subscription costs and tool-versus-no-tool effectiveness remain UNKNOWN.
- The existing cheap independent reviewer was reused with English-only,
  read-only packets and no writes/external access. Root accepted its explicit
  table/row finding and implemented/tested it. No per-agent observed model/token
  or review/rework timer was exposed, so no invented delegation-efficiency
  percentage is reported.

Next: improve FAQ misconception quality without relaxing rejection gates; expand
to long documents and actual conversion/DEV/editor flows; then run paired human
evaluation. Production/public landing remain unchanged. The bounded matrix
correction is verified locally, not a release or general product-quality claim.

## Follow-up: precise repairs and longer mixed-section documents

### Implemented and falsified hypotheses

Repair feedback now binds closed server-generated rejection codes to the exact
original option text, including index remapping after semantic pruning. It does
not forward reviewer prose or add another retry. The benchmark also freezes the
selected suite SHA before execution and checks it before/after every case;
custom-suite mutation has an offline RED-to-GREEN regression.

The initial hypothesis that every `invented_constraint` on a wrong option must
be rejected was **withdrawn**. Existing regression correctly permits a realistic
wrong answer to depict an exception explicitly contradicted by the source.
The broad run caught the temporary overrestriction (1FAIL/462PASS). Final code
keeps that contract and adds the diagnostic only for an invented key or an
otherwise invalid/undetermined wrong option. Better feedback has **not** yet
proven better model acceptance: final FAQ still omits one unchanged failed repair.

### Sources frozen before generation

The extended suite adds three fictional Markdown documents, not new binary
formats: equipment handover (628 words/15 gold claims), mixed-table policy
(599/14), and exceptions/deadlines (517/15). There are44 gold claims and48
table-cell relationships across these sources. Fixture SHA256:
`7e9354b682355d8bedffeecb8bb7fe2ea3abdc6159c46d624a3366c36299ac3a`.
The source author saw no generated output. Root requested one explicit
below-threshold/no-round-up clarification before freezing the mixed policy.
Gold never enters the provider request. The original eight-source suite is unchanged.

The exceptions case was an untouched holdout for its **first** fresh attempt.
After inspecting that failure and using it to guide repairs, it is a consumed
regression case; the unchanged fixture `split=holdout` label does not establish
new holdout generalization. The other two longer cases have offline plans only.

### Source loss found and corrected

The first long run used8 admitted facts, five lessons and eight questions, yet
omitted the eligibility paragraph and all four table rows from learner content.
Two table rows were absent even from parsed supporting facts. Causes:

1. Generic ingestion carried mid-word overlap across a genuine heading, making
   the next complete rule look truncated and unsafe.
2. Ordinary tables were parsed per storage chunk: later rows without a full
   header were lost, and table roles used a different fallback from prose.
3. In the subsequent fresh run, sentence deduplication removed the owner-error
   deadline `2 рабочих дня` after citation coverage had already been validated.

Genuine headings now flush without cross-section overlap; sentence-like ordinal
action lines remain body text. Ordinary tables are parsed after reassembling only
consecutive same-heading/revision chunks, preserving contributing IDs and not
crossing gaps, duplicate indices or worksheets. Table role resolution reuses the
existing narrative fallback; explicit supporting/catalog/appendix roles remain.
Complete prose and all48 table cells survive admission in the three source tests.
Final offline plans admit22/30/20 facts into6/8/6 lessons respectively. This is
admission proof, not proof that every generated lesson renders every value.

The second fresh output retained15/15 gold meanings but only11/12 table
relationships: the omitted two-day value was not caught by those15 gold claims.
The independent AI review initially claimed12/12; root's actual-text readback
falsified that claim, and the reviewer explicitly withdrew it. A new numeric-row
regression reproduced the renderer loss (RED1FAIL). The renderer now checks
labelled table-cell coverage **again after deduplication**; incomplete visible
blocks cannot suppress the existing exact labelled-cell fallback.

Replaying the same34 captured responses on this final correction restores the
two-day value with no new provider calls. Independent AI re-adjudication and
root table-text readback confirm12/12 table relationships and15/15 gold meanings
in this one corrected replay. All10 accepted keys and23 wrong options were
independently inspected against source; no ambiguity was established. This is
bounded AI/source review, not an independent human or universal accuracy score.

### Live costs, omissions and final replay

| Attempt | Algorithm seconds | HTTP | Input/output tokens | Lessons/questions | Interpretation |
|---|---:|---:|---:|---:|---|
| FAQ v7, temporary nonfinal gate |15.050|4|7059/2420|1/3|Retained as intermediate, not final-contract evidence|
| FAQ v8, corrected gate |19.532|5|9174/2607|1/2|All five Q/A clusters taught; unchanged third repair omitted|
| Long v1, first holdout |99.198|26|34966/10972|5/8|Substantial source omissions; not full-source success|
| Long v2, source-boundary correction |89.372|34|46001/12025|6/10|11/12 table relationships; blocked for assessment quality|

Long v2 and final renderer replay retain10 of11 requested axes; nine other
table axes are density-omitted. Total derived axes20, retained10, omitted10.
The conflict-of-grounds question fails bounded repair and remains omitted.
Its unresolved answer-length quality signal keeps `publishable=false` and
`terminal_status=review_required`; no gate was bypassed to make the result green.
The final renderer replay intentionally changes course text only; assessment,
publishability and assessment audit exactly match the captured live v2 result.
Its0.136s replay time is **not** a measured live latency of the final code.

FAQ retains literal4/5 quotes (one valid paraphrase), long13/15 (two valid
reformulations); literal recall is not semantic completeness. Longest-key
heuristic is FAQ1/2, long4/10; it is not a factual-error rate. Table presentation
still starts ahead of the purpose lesson, and labelled fallback prose needs
pedagogical polishing; source restoration is not full teaching-quality acceptance.

Four fresh attempts add69 HTTP calls,97,200 input/28,024 output tokens and
223.152s summed algorithm time. Split: short-suite FAQ9/16,233/5,027 and
extended-suite long60/80,967/22,997. Original short-suite pilot now216 HTTP,
296,780 input/73,771 output. Across both suites and every28 recorded fresh
attempts:276 HTTP,377,747 input/96,768 output. No HTTP errors/transport retries
in these four attempts. Actual monetary charges remain UNKNOWN, not zero.
Provider/model/settings/billing configuration remain unchanged. More complete
content plus more questions is not a matched-output speed or cost comparison.

### Final local gates and limits

- Final broader selected tests578PASS/7.85s, canonical13 journey selectors
  27 parametrized PASS/3.73s. Counts overlap. Baseline PASS with unchanged
  Ruff1008/Mypy2201 debt. The initial longer-source test used the wrong tuple
  shape (corrected before the meaningful3FAIL source-loss regressions); one
  overlap test used less than the existing20-character proof threshold and was
  corrected. Import-order baseline failures were fixed mechanically, not exempted.
- Final replay: long34 captures restores source text; FAQ5 and matrix13 captures
  exactly preserve course/assessment/publishability/audit. All52 final captures
  use0 HTTP/fallback; no latency or independent fresh-quality claim from replay.
- Final runtime fingerprint:
  `710206ae4c9fbe93ee06a411081d38e49e0a135fc7fb5dfebf82bad045120859`.
  Last fresh v2 fingerprint was
  `fb3904e23fef0722185aae26a765c774e9e87851170373d325babd2fd7f849b8`.
- CodeGraph narrowed the existing semantic seam; source remained decisive for
  ingestion and renderer defects. Combined preparation receipt was NOT_READY
  while the SDK/index worked. The initial final semantic sync was1.251s body/
  8.411s total; subsequent source-boundary sync1.464s/8.523s. Final renderer
  sync is recorded in the ledger. Graphify expansion was unnecessary. No tool
  token-saving, subscription cost or causal efficiency percentage is established.
- A cheap independent author and reused cheap reviewer operated English-only
  bounded packets. Their mistakes and root corrections remain in this history.
  Observed per-agent token/cost/rework timing is UNKNOWN; no invented savings.

Production/public landing, accounts, DB, providers and deployment are unchanged.
Existing indexed documents were not reindexed; the ingestion fix needs its own
DEV/reindex journey before claiming repair of previously stored chunks. OCR,
mixed-language sources, full conversion/DEV/editor flow and paired human time
remain open. Next priorities are first-pass misconception quality, source-owned
lesson order, another untouched complex-source evaluation, then the canonical
DEV journey and paired methodologist comparison. No public human-speedup claim.

## Continuation2026-10-12: conflict, order and complex-source gate

The previous conclusions above describe their captured candidates, not the current
one. Late answer-length feedback now reaches the existing single repair together
with semantic feedback; final omission reasons describe the current failed repair.
Ordinary prose/table lessons follow document/chunk order. Numbered normative
sections are not demoted to catalogs merely because they mention a list. Two
unambiguous prohibition grammars reuse server-owned binary inverses; joint actions
and conditional status alternatives stay intact. Qualified/exceptional grammar
remains model-reviewed. No source fixture or quality threshold was weakened.

Frozen new complex source:866 words,8 numbered sections,2 tables,23 required
meanings,27 table cells; suite SHA256
`41e3934b25cb8c488fd5e67a563a47802ff384cfc1bca47c7f39bfa513a94857`.
Its first run was untouched; later runs are regressions on that consumed holdout.

| Fresh attempt | Seconds | HTTP | Input/output tokens | Lessons/questions | Verdict |
|---|---:|---:|---:|---:|---|
| Complex v1 |95.167|38|53704/14228|6/10|Rejected: missing operational sections/cells and ambiguous wrong option|
| Complex v2 |141.495|57|82890/19763|10/15|Full material restored; two assessable lessons blocked|
| Conflict v3 |93.515|36|51267/13982|6/11|Bounded semantic PASS:15/15 meanings,12/12 cells; conflict question retained|
| Complex v3 |132.960|53|76998/19339|10/19|Bounded semantic PASS:23/23 meanings,27/27 cells, all19 keys supported|

Complex v3 source order:purpose,roles,classification prose/table,design,
approval prose/table,publication,exceptions/rollback,closure/archive. All retained
questions and wrong options were independently inspected and root-reviewed.
Publication gates pass on these captured outputs; this is not universal accuracy,
human review or release/runtime proof. Literal complex recall13/23 is not semantic
coverage: table rows and one prose rule are reformatted. Assessment19 retained/
22 omitted axes is density/selection, not22 missing taught meanings. Some wrong
options still combine clauses or test the same misconception; pedagogical polish
and paired human effectiveness remain separate work.

Total32 fresh attempts including all failures/intermediates:460 HTTP requests,
642606 input/164080 output tokens; actual USD charges UNKNOWN. Route/model/settings
unchanged. Complex v3 runtime fingerprint
`ba5bd5ea2b7588c4f3f029ae770092994f61d781cd5b456f75e40b4778ff512a`.
Final local R3:533 PASS/7.62s across34 files;13 required AI journey selectors
yield27 PASS/4.03s; overlapping counts are not added. Baseline PASS with unchanged
Ruff1008/Mypy2201 debt. Initial R1 import-order failure retained, corrected
mechanically before R2/R3; focused inverse regressions were RED then GREEN.

DEV before-state freshly verified:c453658aa30b1826d9395f976c6355d3bc760de9
on API/worker/frontend, schema0178; permanent QA9-table counts/fingerprints saved.
New candidate deployment, public queue generation, editor/browser and
exact cleanup are still OPEN. Production is out of scope and unchanged.

### DEV release gates, first prepared candidate

Committed candidate422588f01b8835f727d2f18228757d4e990e5f0c was pushed only to
`dev`; independent project-account remote SHA readback retained. Exact CI38220959608
failed three jobs at the same ERRORS journal contract: new entries used plural
`Symptoms`/`Causes`, and044 lacked `Symptom`. Release Runner stopped at that hard
gate, before its explicit provider deployment. Singular fields and the missing
factual symptom were corrected; release-contract gate now PASS with250 entries.
No application source change, extra paid generation or CI exemption followed.

Canonical Supabase DEV application gate HBR-DEV-APP-20261012T075838Z passes20
checks with exact cleanup, active-only retrieval, tenant/no-context negatives,
rollback and public0178 metadata unchanged. The named reindex/idempotency selector
first failed at fixture bootstrap under non-bypass lms_app (tenant context absent).
It now sets only its allocated synthetic tenant context before creation and passes
in9.38s under the same role/outer-transaction rollback; no owner-role or RLS bypass.
These are runtime DB checks, not public queue/browser acceptance.
Final R4 complete database-free unit suite2760PASS/28.76s, release contractPASS,
baselinePASS; root's concurrent changes affected documentation/integration fixture,
not the tested AI runtime source. Permanent QA9-table fingerprints unchanged after
both isolated DB gates. The failed CI and initial RLS fixture failure remain recorded.

### Actual DEV R2 uncovered a public-submission mismatch

Exact1a5d8bb800cebc2edb04c8680558ae9214247cea passed CI38221848922 and
API/worker/frontend release identity, Free/Free/Hobby contracts and public0178.
One ordinary-methodologist source upload indexed in11.485s; queued generation
62ac1763-31af-4666-90df-a047f556987d ran08:20:08–08:21:05UTC, saved a draft
with3 lessons/3 quizzes/6 questions, and returned interrupted with
assessment_coverage_incomplete. NOT_ACCEPTED: all23 meanings/cell values existed,
but classification row associations were visibly detached and moved behind later
sections. Local v3 PASS was not substituted for this DEV failure.

Root read-only, non-bypass tenant-bound job diagnostics proved that the public
submission uses inspect_content=false and source_capacity_proxy_chunks; its
3-lesson recommendation was passed as a hard generation cap. Runtime correction
keeps lightweight admission and existing explicit/manual/passport recommendations,
but automatic proxy-only jobs now use the existing40 lesson ceiling while the
evidence engine derives actual lessons from source. The exact ceiling is persisted
for resume; old jobs retain their stored recommendation fallback. Mixed prose/table
writer blocks cannot suppress attributed cell fallback; valid blocks follow source
fact order. No provider retry, model, quota, quality threshold or billing changes.
Renderer regression RED then62 focused PASS; ordinary Supabase DEV submission
regression1PASS/9.42s, outer rollback. Full R5 unit run2763PASS/1FAIL: the pre-existing
admission test pinned the superseded proxy cap1 rather than source-adaptive bound.
Its outcome is retained; update that exact policy expectation, not quality gates.

The rejected fixture e31c3a08-e61e-4450-b0ba-ac97c0d457df was removed through
normal guarded API DELETE204/fresh404; permanent QA business stats unchanged.
Independent owner read-only sweep checked all116 public tenant-scoped tables:
tenant absent,115 tables empty,11 residual document_embeddings rows for the owned
source only. API deletion is not complete cleanup. Exact residual maintenance
requires new owner authority under TENANT-PURGE-007; none was performed.
Final corrected DEV acceptance remains pending.
The canonical AI-COURSE-01 flow ends at a reviewed draft and every quiz; no
publication, assignments, invitations or irreversible learner completion is emitted.

Final R6 local gates:2764 unit PASS/23.48s,27 AI-COURSE-01 parametrizations
PASS/3.98s, release contract PASS(head0178/176 revisions/32 dependencies/251
journal entries), baseline PASS(Ruff1008/Mypy2201). Initial R6 diff whitespace
failure was corrected by line-ending normalization of the named integration
test only; independent correction gates PASS with unchanged runtime hashes.

Independent review then identified a same-section/shared-column two-table edge.
The executable regression reproduced row interleaving; table identity now scopes
coalescing and row sorting. Distinct-section and same-section variants pass with
separate blocks and source table order. Final R7 gates are required on this delta.

Final R7 functional gates:2766 unit PASS/22.81s,27 journey parametrizations
PASS/4.79s. One new missing dictionary type annotation failed the Mypy baseline;
explicit annotations corrected it without logic changes. Correction31 focused
PASS/0.60s, baseline PASS, release contract PASS and diff check PASS. Original
failure retained. Final renderer hash
`463fd50118e34095512870cb95b5c1c3e8c0e4859c127eb5c3fa442319621225`.

## Final DEV acceptance — candidate97f4efd, 2026-10-12

Exact CI38225806750 SUCCESS across all seven jobs. Release Runner executed
REL-DEV-COURSE-QUALITY-R3-20261012 on existing Render Free API/worker and Vercel
Hobby only: APIdep-db69vm7lk1mc73cfnon0, workerdep-db6a0odckfvc73cmo93g,
frontenddpl_EM9pR2Pgy7u1UqZa8ApmUJgRu9ht, all bound to
97f4efd2834c9d6bb0056f848b79cb7ecbf85816. Root independently read back provider
identities, enabled workbench/document/correction flags, public schema0178 and
unchanged9-table QA fingerprints at09:20:17UTC after cleanup. No migration,
provider-plan/resource/budget/model change, master push, tag or production release.

One disposable tenant05e2e2c7-91c6-4037-9410-6c91ebcaf16d and one ordinary
methodologist submitted the frozen synthetic Russian source through normal API:
source upload/index13.516s; confirmed queue generation135.750s, including polling
and network. Job36c1b021-eaca-47f5-a361-2fa355ab86ae completed with no errors;
course4d1f95c0-d015-4ebb-befa-784065921418 remained draft, with one module,
10 lessons,10 quizzes and20 questions. Reconfirming the same sealed plan returned
the same job; exactly the ingest and generation jobs existed, both completed.
This is idempotent submission proof, not a second paid-generation repeat.

Independent AI review plus root source adjudication preserved23/23 frozen
meanings and27/27 row/column relationships; all20 accepted keys are grounded,
and every retained wrong option is false or source-unsupported. Lesson order is
sections1,2,3a,3b,4,5a,5b,6,7,8, not row-number interleaving across tables.
The multiple-basis classification question now retains the explicit source rule
to select the higher impact level. The unresolved-priority negative control still
does not authorize inventing a precedence rule absent from the source.

Persisted audit covers14/14 topics with no unresolved quality signal, missing
assessed lesson or incomplete audit. One existing semantic repair occurred.
Of41 derived assessment axes,20 were retained and21 omitted by density/selection;
that is not21 missing taught meanings or a complete exam of every source fact.
The lightweight preview estimated3 lessons; the source-owned worker derived10
within the unchanged automatic ceiling40. Preview is not an exact final-count
guarantee. No gate, threshold, provider retry budget or quota was relaxed.

Browser acceptance used ordinary login, no impersonation: source download bytes
match SHA2568d67d813ec5800b00fbeacee3e27a50224b22a7e4f71b374697cf6a4403d1171;
all10 lesson previews and10 quizzes were opened; every visible question/choice
matched persistence, and all20 edit forms showed matching correct-answer keys.
Forms were cancelled, no edits saved. Reload retained all10 quizzes. This is a
hybrid normal-API upload/queue plus browser source/editor/quiz scenario, not a
UI-only upload/start or full-LMS/student-completion test. No quiz approval,
publication, assignment, invitation or learner completion was emitted.

Test-harness mistakes remain recorded, not misreported as product bugs: an
assignment-plan query used for a document plan returned404; normal course/quiz
navigation corrected the check. Lesson selection resets editor mode, so Preview
was explicitly selected for each lesson. Quiz selectors expose a misleading AX
checkbox role; their actual DOM button role was used. Cleanup attempts1/2 stopped
before deletions at superadmin users/me403 and preview max_chars validation422.

New fixture cleanup then passed through the normal lifecycles in this order:
draft DELETE204/fresh404; document DELETE202, completed document_cleanup worker,
fresh404; tenant DELETE204/fresh404. Independent read-only sweep: tenant0,
all116 tenant-scoped tables0, remaining0. Ordinary browser logout was verified
and the temporary tab closed. The worker proves its document cleanup completed;
no independent object-store bucket inventory was collected.

**Remaining release gate:** rejected R2 tenant
e31c3a08-e61e-4450-b0ba-ac97c0d457df/doc39a99b98-e8af-449e-b4c9-5121a688d8eb
are absent, but11 exact document_embeddings rows remain. No privileged cleanup
was performed. Frozen ID/full-row-hash inventory SHA256
b091c3d18834dfda11bc10feae25ac291fc9fe7fdb5d639954463d11adf1efdc;
new exact owner approval, rollback-only rehearsal and116-table final absence
readback are required by TENANT-PURGE-007. No generic tenant purge repair or
automatic production data cleanup is included in this package.

Sanitized evidence under `.release-evidence/COURSE-BENCH-20261012/`:
`final-acceptance.json` status PRODUCT_FLOW_PASS_RELEASE_CLEANUP_BLOCKED,
`dev-final-readback.json`, `dev-live-r3/{generation-readonly,job-diagnostics,
semantic-review,ui-browser,cleanup-source-first-r3,absence-owner}.json`,
`dev-live-r3/conflict-question-browser.png`, and
`dev-live/residual-eleven-inventory.json`. The root receipt binds proof hashes.

Algorithm usage totals32 attempts/460 HTTP/642606 input/164080 output tokens
exclude both actual DEV generation jobs. DEV token counts/call counts and actual
USD charges are UNKNOWN; do not relabel algorithm totals as the complete spend.
These synthetic results do not establish general accuracy, human methodologist
speedup, accepted-course total time, OCR/RU-KK quality or marketing readiness.
Remaining broader quality work: FAQ stability, long/binary/scanned sources and
paired real-methodologist comparison. Production remains unchanged.

## Exact cleanup closure — 2026-10-12

Owner's current approval covered only the frozen11 DEV embeddings inventory.
Original inventory and PRODUCT_FLOW_PASS_RELEASE_CLEANUP_BLOCKED acceptance are
preserved, not rewritten as historical successes. Independent Test & Evidence
Runner static review preceded execution. First rehearsal failed42501 before
DELETE and rolled back: Supabase migration postgres is MEMBER(lms_app) but
pg_has_role(...,'SET') is false. This was an already documented managed-role
restriction; importing the production SET ROLE step into DEV was a harness
mistake. Metadata reads confirmed canonical runtime SELECT/DELETE privileges.
No new grants, roles, membership, policies, DDL or RLS changes were used.

Corrected procedure uses the existing canonical lms_app connection for table
lock/tenant-bound exact-ID/document/full-row-hash DELETE. Owner connection stays
READ ONLY for all116-table inventory, revision/absence guards, unknown-trigger/
incoming-FK negatives and foreign full-row hash-of-hashes/security invariance.
Rehearsal R2 PASS restored all11 exact rows and hashes after rollback. Its exact
script SHA256be1e53ffbbc8e6be3cd72fc6f1212fd637c38cd3c756b281b6512d94cb12f269
was independently reviewed and bound into the single commit receipt.

COMMITTED_EXACT_ELEVEN:11 rows removed, lms_app non-super/non-bypass, all foreign
embedding rows and owner/ACL/policy/FORCE-RLS fingerprints unchanged. Independent
fresh READ ONLY sweep of the old tenant: absent,116 tables checked,0 rows total.
The new tenant's separate116-table zero proof remains hash-linked. Final DEV
provider/API/schema readback PASS; all9 existing flags ON, Render Free/Free and
Vercel Hobby unchanged, API/worker exact97f4efd, schema0178. Permanent QA9-table
full-row fingerprints before/after cleanup identical. No extra generation.

Current root receipt `.release-evidence/COURSE-BENCH-20261012/release-readiness.json`
is DEV_ACCEPTANCE_CLOSED_RELEASE_CANDIDATE_READY and binds the previous acceptance,
failed first rehearsal, permission diagnosis, successful rollback/commit, both
absence proofs and final readback. This closes this candidate's owned fixture
cleanup; generic tenant-purge omission remains a separate open defect. It does
not prove old object-store absence, full-product quality, paired human speedup,
production release execution, version/tag publication or commercial readiness.

## Production0.11.44 — separate real-generation and browser closure, 2026-10-12

Runtime source `2f333c414854c7f54be3c4d8c34d78472c652581`, immutable image
`sha256:5acc4539cea194cba886cc2e8c7a30816b297e0da23685d5aaeb13d6fd9081d8`.
CI38235382186 all7SUCCESS:4337PASS/2SKIP,75.81% coverage, overlapping
AI-COURSE-01 28PASS and RLS42PASS. Protected workflow38236208832 SUCCESS,
deployment7011811718. Root verified actual attestation source/subject and remote
tag; the separate automatic build image was not used as deployed-image proof.
Four green containers use this exact image/restarts0, schema0178 unchanged,
native frontend42 retained and live-browser compatible. Watchdog identity,
oneshots/timers, backup and rollback43 readiness independently read back.
Actual rollback switch and a new restore drill were NOT_RUN.

One actual production queued generation used the already consumed complex
regression source, not a newly unseen holdout. Source8 sections/2 tables/866words;
source bytes SHA2568d67d813ec5800b00fbeacee3e27a50224b22a7e4f71b374697cf6a4403d1171.
No repeat paid generation or model/repair-budget change during this acceptance.

| Production measurement | Actual result | Boundary |
|---|---:|---|
| Upload and indexing | 3.187s | Normal API path; text source, not OCR/converter benchmark |
| Queued generation | 135.734s | Includes network/polling; excludes human review/publication |
| Harness total | 139.937s | Upload through captured draft; excludes browser acceptance |
| Lessons / quizzes / questions | 10 / 10 / 18 | DEV had20 questions; no padding or full-axis claim |
| Source meanings retained and reviewed | 23 / 23 | One synthetic source; not universal accuracy |
| Labelled table relationships retained | 27 / 27 | Row/column values rendered as labelled prose |
| Grounded unique keys / wrong options reviewed | 18 / 35 | Source-first review, not measured learner effectiveness |

Root ordinary-methodologist browser inspected all10 rendered lesson previews
and all18 question forms, including the higher-level conflict rule. Each visible
question/choice/key matched the captured API output; source file downloaded
through the actual browser and matched the uploaded bytes. Reload retained10
quizzes; console errors0; ordinary logout returned login. The generation was
started using normal API helpers, so this is a hybrid end-to-end draft workflow,
not an exclusively UI-driven upload journey. Same sealed confirmation replayed
the original job. Draft remained unpublished and all quizzes require review;
no save/approval/publication/assignment/invitation/learner attempt was performed.

Normal draft204/fresh404 → document202/completed cleanup worker/fresh404 →
tenant204/fresh404. Independent READ ONLY116-table sweep:0rows, tenant absent;
physical local-storage prefix0files. Permanent QA9 full-row fingerprints and
business counts unchanged. No privileged residual deletion. Generic
TENANT-PURGE-007/008 remains open; successful source-first cleanup does not imply
the generic tenant purge was fixed.

Sanitized append-only raw receipts: `.release-evidence/REL-COURSE44-20261012/`,
generation receipt SHA256b1bf179af3279e7d00b07c2246fb0367afcdc7e5e69528cc52ea697276d50f1a.
Test & Evidence Runner independently reconciled Root's artifacts and corrected
two reviewer labels to the actual production questions without changing outputs;
its verdict is local artifact review, not a second runtime execution. Release
Runner's protected-workflow receipt and Root's independent live readbacks are
separate. Browser harness corrections (AX diff/race, field-order comparison and
AX pressed-button representation) are retained as harness observations, not
product failures or silently discarded generations.

This closes the bounded production package. Earlier failed/blocked measurements
and algorithm usage totals remain unchanged. Production provider call/token
counts and actual billed USD are UNKNOWN; do not add this run to algorithm
usage totals. No paired real-methodologist baseline, accepted-course editor time,
same-version stability, long/scanned/binary-source coverage or human speedup is
established. A truthful future case study may report the exact synthetic result
and timing with these bounds; a comparison “faster than a person” is not supported.
