# Navigation applicability audit

Date: 2026-07-26
Owner: Codex
Status: in progress

## Product decision

The unfinished communication modules remain available in code and keep their
tenant data, API routes and access policy, but they are removed from the
methodologist sidebar and command palette until they provide a complete,
usable workflow:

- post-course feedback must expose response analytics and an operational
  follow-up flow;
- announcements must become a clear communication channel with recipient
  preview, delivery state and unambiguous naming.

Direct URLs remain guarded by the existing capability registry so the future
implementation can be resumed without a destructive rollback or database
migration.

## Scope

1. Hide `surveys-manage` and `announcements` from navigation surfaces.
2. Add regression coverage proving that hidden modules are still protected
   registered routes but are absent from the sidebar and command palette.
3. Record the missing product capabilities as backlog items.
4. Audit every visible navigation section for `methodologist`, `admin`,
   `student` and `superadmin`.
5. For each section record:
   - intended user job;
   - current implemented behavior;
   - role/process ownership;
   - duplication or misleading placement;
   - applicability for the first production tenant;
   - decision: keep, improve, move, merge or hide.
6. Verify route-registry tests, the full frontend test suite, TypeScript and
   production build.

## Progress

### Step 1 - hide unfinished communication modules

**What changed:** `surveys-manage` and `announcements` remain registered and
capability-protected but no longer have sidebar or command-palette metadata.
Regression coverage verifies both conditions.

**Status:** done

### Step 2 - backlog contract

**What changed:** `docs/backlog/2026-07-26_communications-modules.md` records
the current implementation, missing product capabilities and the
return-to-navigation gate.

**Status:** done

### Step 3 - role-by-role section audit

**What changed:** `docs/reports/2026-07-26_navigation-applicability-audit.md`
audits every visible route for all four roles and records keep/improve/move/
merge/hide decisions with P0-P2 priorities.

**Status:** done

### Step 4 - verification

**What changed:**

- frontend tests: 26 files, 140 tests passed;
- TypeScript: `tsc --noEmit` passed;
- Next.js production build: passed;
- `git diff --check`: passed.

**Status:** done
