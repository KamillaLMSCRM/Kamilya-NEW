# Writer prompt budget V4

Status: Accepted by Astra root, 2026-09-10, within the approved large-Excel repair.
Supersedes: EPIC_V1 exclusion of writer changes only for request packing below.

Real cold 932-source test mapped44batches in53.54s and created3modules/6lesson
outlines in67.85s. Writer failed before its first inference call with
`direct_source_prompt_budget_exceeded`. Its selection budgets source text alone;
repeated filename/revision/headings/wrappers also consume the32000-char request.

Root owns direct_source.py and focused tests. Interface remains compatible:
write_direct_course returns the same CourseContent and exact sent source references.
Pack whole ranked chunks with both original24000-char text cap and exact serialized
32000-char combined prompt cap. Reserve fixed system/lesson metadata first. Preserve
every requested document, no clipped chunks or false provenance. If even one whole
chunk per requested document cannot fit, retain an explicit budget error before LLM.
Selection remains per-lesson bounded retrieval; whole-corpus coverage remains in MAP.
Do not raise provider limits, remove quality checks, alter embedding/provider order,
or claim every source fact is taught. Escape untrusted source wrapper markers.

Tests: long repeated metadata fixture reproduces the real pre-call failure; repaired
request fits both bounds, includes all selected documents, and persisted references
match sent whole chunks. Oversized fixed metadata and unrepresentable documents fail
without provider calls. Existing small-source and semantic fallback tests unchanged.
Root repeats the representative writer then assessment/save/browser gates.
