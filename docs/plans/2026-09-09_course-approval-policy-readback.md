# Course approval policy readback incident

Root owner: current Kamilya orchestrator. Baseline: 59a3af0c (existing origin/master).

Observed: publication returns HTTP 409 with `details.code=approval_required` while the course is reviewed and the policy checkbox is unchecked. Live course detail omits the policy field. No customer content or identifiers are persisted here.

Scope: tenant-scoped read-only policy API, authoritative UI policy loading, readable publication failure, focused regressions. No migration or policy default changes. Existing enforced approval and content review invariants remain intact. One bounded implementation worker owns named API/UI files; root owns integration and this plan.

1. Reproduce and verify missing read contract: DONE (live response and source).
2. Implement explicit policy GET and UI loading/error/readback; keep writes disabled until policy is known.
3. Verify missing policy defaults without creating a row, cross-tenant denial, enabled policy render, fetch error and course switch, publish error translation.
4. Review diff and run focused backend/frontend tests and appropriate static checks.
5. Customer recovery uses the existing policy action only after owner resolves whether separate approval is required. Never manufacture an approval.
6. Release requires exact production identity, CI and the canonical deployment gate; no deployment is implied by local passing checks.

Acceptance: reopening the editor/approval page reflects server policy; no unchecked fallback on failed read; publication retains server approval enforcement; customer course disposition matches explicit owner choice.

## Verified outcome and remaining release boundary

- Steps 1-5 complete locally or through the specifically authorized customer recovery.
- Production recovery: explicit policy false readback and publish HTTP 200; published
  course and assignment action visible. No fabricated approval or bulk policy changes.
- General patch includes editor/approval-page policy readback and localized conflicts
  across list, editor and AI-generation publication paths (RU/KK/EN).
- Independent read-only review found the missing AI-generation path; it was added
  with a rendered-page regression. One bounded implementation worker and a separate
  read-only reviewer were used; root retained integration ownership.
- Backend: 55 focused approval, publication, follow-up and release-contract tests pass.
- Python quality baseline passes: ruff=1090, mypy=2353; no baseline relaxation.
- Frontend: final full suite 106 files / 554 tests passes, including the added
  rendered AI-publication conflict regression.
- TypeScript and diff whitespace checks pass. No migration, default change, provider
  change, Git publication or systemic production deployment performed.
- Graph navigation used the canonical existing graph, with findings verified in source.
  The isolated worktree has no derived graph; no rebuild or external semantic upload
  was performed. Refresh the candidate AST index if continuing to release preparation.
- Release order: approved exact-SHA API first (new GET, no migration), frontend second,
  then synthetic methodologist browser readback for saved false/true, reload, switching
  course and publish conflict. Current local tests are not DEV/RLS/live-release proof.
