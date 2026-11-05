# Whole LMS workspace redesign V2

Status: Implemented locally, prepared for owner review. Contract:
[`learning-workspace-visual/EPIC_V2.md`](EPIC_V2.md)
(see its owner amendment R1: dedicated admin/superadmin screens deferred).
V1 catalogue/shell work is already on `master`; V2 extends the same language to
every other canonical LMS page.

## What changed

- New pure presentation module `apps/web/src/features/workspace-design`:
  `WorkspacePage`, `WorkspacePageHeader`, `WorkspacePanel`, `WorkspaceToolbar`,
  `WorkspaceEmpty`, `WorkspaceStat`, `PublicWorkspace` and RU/KK/EN public copy.
  No fetching, auth, storage or business inference lives there.
- Every canonical non-deferred page now composes real content with those parts or
  the equivalent V1 catalogue marker. `apps/web/tests/wholeLmsCoverage.test.ts`
  enumerates the discovered `app/**/page.tsx` inventory and fails if a page is
  unclassified, if a redesigned owner lacks a real composition, or if a deferred
  admin page claims a partial redesign.
- Public LMS surfaces (sign-in, invitation, assignment access, reviewer PIN/inbox,
  candidate assessment, kiosk, certificate verification, legal documents, demo and
  tenant registration) share the same design while keeping their token/OTP/consent
  and capability boundaries.

## Verification (local, synthetic only)

- Full web suite, typecheck, lint, production build and the 3027/3026 built-page
  browser matrices are recorded in `docs/testing/TEST_RUN_LEDGER.md`,
  `RUN-20261102-WHOLE-LMS-VISUAL-01`.
- Browser evidence: `apps/web/test-results/whole-lms-final` and
  `apps/web/test-results/visual-v2-regression2`.
- Deployed DEV/production, real devices, CI and release remain separate owner
  gates. No push, merge, version bump, provider call or paid model was used.

## Reviewer notes

- Review source diff against `96a76b8f`; the branch is one implementation commit
  plus this documentation commit.
- Re-run `pnpm.cmd test`, `pnpm.cmd run typecheck`, `pnpm.cmd run lint`,
  `pnpm.cmd run build`, then the two Playwright configs with
  `PLAYWRIGHT_SKIP_WEBSERVER=1` against a freshly built local server.
- Rollback is a source revert of the V2 range; no data, schema or history change.
