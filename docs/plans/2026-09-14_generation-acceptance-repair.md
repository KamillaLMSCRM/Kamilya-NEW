# Generation acceptance repair

Owner authorization: current request delegates inexpensive agents, root review, production release, then one live run of each source. No billing, provider-route or infrastructure expansion. Baseline v0.5.41 `ae81b12a845e21845bf505a6257e4f1f99d84cdb`. Prior two-run evidence: `.release-evidence/v0.5.41/LIVE_ACCEPTANCE_LOMBARD_PLUS_20260914_RU.md` (local, not public fixtures).

## Ownership and sequence

| Owner | Model/effort requested | Exclusive writes | Acceptance |
|---|---|---|---|
| Ampere | gpt-5.6-terra / medium | `assessment.py`, `test_assessment_prose_semantics.py` | Actual-seam RED/GREEN; prose meaning, contextual evidence, duplicate/drop-only checks and false-positive guards |
| Boole | gpt-5.6-terra / medium | `lesson_quality.py`, `test_lesson_numeric_provenance.py` | Unsupported numerical claims and missing-formula guard; realistic negative and positive cases |
| Root | Astra | `direct_source.py`, pipeline/schema integration, source/OCR diagnosis, plan, journal/changelog/version, release and independent acceptance | Exact-scope review, complete applicable journey, DEV, same-SHA release/runtime readback |

No more than two concurrent leaf workers; no agent owns production access until a complete Release Runner packet. Worker handoffs use English five-field contract. Root owns final documentation, integration and source/customer data. Existing unrelated dirty main/landing trees remain untouched; only linked candidate checkout is edited.

## Gates and work

1. Reproduce observed quality escapes with minimized synthetic fixtures. Exact rejected Excel response is not yet available; do not label a synthetic shape as a captured production replay. Verify OCR-versus-writer origin of the invented percentage.
2. Repair primary worksheet references with bounded contextual correction; preserve document ownership and rejection of standalone auxiliary curricula. Keep primary content estimates separate from supporting rows.
3. Prevent unsupported numeric claims and retain explicit warning/omitted-topic inventory when a partial course is saved. Preserve source facts, provenance and checkpoint coordinate mapping; no fictional replacement lessons.
4. Validate every assessment option and contextual action; remove duplicates and invalid questions without padding. Preserve distinct subjects/conditions and structured-source behavior.
5. Review UX progress scope and final partial-result messaging, readable lesson preview, and methodical quality. WYSIWYG redesign is not part of this candidate.
6. Root independently reviews worker deltas and invokes focused/broader DB-free tests, mandatory AI-COURSE-01 local profile, isolated Supabase DEV application gate and relevant frontend checks. Never use local Docker PostgreSQL.
7. Publish one exact versioned candidate only after gates and rollback readiness, using canonical Git identity and Release Runner for prepared deployment. No migration intended. API/workers and frontend readbacks are separate.
8. One live methodologist run on the Lombard PDF, then one on the complete Plus workbook in synthetic tenant. Record start/terminal/stage times and inspect every saved lesson/question. Preserve requested review drafts; explicitly separate disposable infrastructure smoke cleanup from these owner-requested artifacts.
9. Final report separates implemented, tested, deployed and content acceptance. A failed live quality result is not GO; do not silently begin another production iteration.

## Initial status

- Root preflight: candidate tracked files clean at baseline; existing untracked operational/evidence files preserved. Main and landing contain unrelated owner work and are not candidate sources.
- Graphify query for `generate_direct_source_content` returned no node; exact current `write_direct_course` source confirmed. Navigation gap is not runtime evidence.
- Primary-heading repair seam: two synthetic regressions RED then GREEN; full architecture module 20 passed. Confirms quoted exact headings and missing prior-plan correction context, not yet exact production failure cause.
- Requested model is not an observed billing measurement; effective model/token counters were not exposed by the worker transport.

## Candidate 0.5.42 review ledger

- Two requested Terra/medium implementers, followed by one Luna/medium read-only
  reviewer. All leaves closed after handoff. Effective billing/token counters are
  unavailable; no token-saving percentage is claimed.
- Root rejected first assessment/numeric candidates for Russian replay gaps and
  merged-fact false positives. Corrected focused worker suites passed.
- Independent review found stale omission-policy reuse and misleading retry-budget
  classification in root changes; corrected with RED/GREEN regressions.
- Root rejected the initial OCR guard because it affected non-PDF formats and
  checked raster bounds after allocation. Corrected scanned-only scope, pre-render
  bounds and table ownership passed independent Luna review and 30 focused tests.
- Real-page replay then exposed Markdown escaping of the uncertainty marker. Root
  fixed serialization and added three regressions. Full 21-page original replay:
  98.81 seconds, invented percentage present before guard, absent afterwards, one
  uncertainty marker and one warning. Tested converter source SHA-256:
  `dd751597009a24d0085a8feb1e3e2cfcc08d83a00b887d0af3d31aa72797ca44`.
- Complete workbook original-hash replay: 1076 source chunks, primary learning
  section separate from supporting catalogue; revised recommendation two modules,
  six lessons, hard cap seven. This is sizing evidence, not generated-course QA.
- Root extended checks: 395 passed; source uncertainty/persistence and converter
  checks: 40 passed; UI status seven passed, TypeScript and scoped ESLint passed.
  Final combined quality/converter/journey matrix: 369 passed in 16.59 seconds.
  Existing Ruff/mypy regression baseline passed without baseline changes. Version
  consistency passed. Graphify update refused a smaller graph (17649 versus
  18340 nodes); existing index was preserved, final review uses actual source and
  tests, not the stale graph. No forced index overwrite is part of this release.
- Supabase DEV application gate `HBR-DEV-APP-20260914T021716Z`: READY, revision0158,
  tenant/RLS/activation/rollback checks passed, disposable schema removed and
  shared public metadata unchanged. No provider call in this DB gate.
- Production readback before release: API/four service image parity at baseline
  SHA, blue slot, Docling `kamilya-docling:05d7defe`. No production service change
  has been made in these diagnostics. Release and live acceptance remain pending.
