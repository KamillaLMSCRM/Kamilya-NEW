# Free-text assignment intent addendum V3

Status: Accepted for bounded repair, 2026-10-04.
Supersedes: LLM_ASSIGNMENT_INTENT_ADDENDUM_V2.md; all V2 obligations remain.
Approved by root under the owner's ongoing implementation and DEV acceptance.

Actual existing-provider DEV RU extraction passed. KK extraction retained one
pair of guillemets around a course query, so the unchanged exact lookup could
miss the intended unquoted title. Preserve the failed provider receipt; debug by
deterministic replay, not repeated paid calls or semantic repair.

Only candidate-mode resource resolution may try two bounded exact spellings:
the original trimmed query first, and then a single paired outer delimiter
removed ONLY when the first query returns zero rows. Supported delimiters:
guillemets, curly double quotes, straight double quotes and straight single quotes.
No recursive/nested, mismatched or blank-inner unwrapping, fuzzy/substring search,
model re-call or silent candidate/confirmation mutation. Raw literal quoted names
take precedence; all duplicate choices, selected-ID checks and21-row limits stay
unchanged. Both attempts retain tenant/published-course or tenant/active/nonarchived
department predicates. At most four catalogue queries (two per resource).
Legacy exact-command mode remains unchanged.

Write scope: assignment_service.py, new quoted-resource unit tests, existing owned
DEV intent gate, root module index/changelog/error/readiness/plan evidence.
No migration, provider/routing/flags/budget/retention change. Confirmation remains
explicit and canonical. Verify real service-seam replay, literal-name priority,
duplicates/forged choices, legacy mode, SQL predicates, owned Supabase DEV isolation,
independent frozen tests, then new exact-SHA DEV and bounded provider/browser proof.
