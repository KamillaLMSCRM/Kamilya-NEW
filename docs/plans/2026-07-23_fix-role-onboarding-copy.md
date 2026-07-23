# Fix role onboarding and authentication copy

## 1. Establish scope and map affected surfaces

Inspect the canonical RBAC policy, admin onboarding component, demo role selector,
login/register flows, translations, and existing frontend tests. Preserve unrelated
working-tree changes, particularly `graphify-out/` and training-log translations.

**What I did:** Read the required project entry documents, ADR-0012, auth architecture,
existing role-policy tests, and the affected frontend components. Used Graphify to map
the initial code paths. Confirmed `graphify-out/` is an unrelated untracked directory.
**Status:** done

## 2. Make admin onboarding and quick links role-correct

Prevent admin-facing onboarding from rendering actionable methodologist routes. Keep
admin infrastructure routes actionable and present a clear non-actionable hand-off
message for learning-workforce steps.

**What I did:** Added an ADR-backed CTA ownership helper and changed the admin checklist
so only admin-permitted routes remain links; methodologist-owned reported steps are now
informational with a hand-off message.
**Checks:** Added focused CTA ownership tests for admin and methodologist routes.
**Status:** done

## 3. Align demo and auth copy with canonical role policy

Correct the demo admin description, localize the tenant-registration password hint,
and explain the Telegram code's bot destination, expiry, and recovery path in RU/KK.

**What I did:** Corrected the demo admin description and landing route; added localized
password guidance and Telegram prerequisite, destination, expiry, and recovery copy.
**Status:** done

## 4. Add focused tests and verify

Add unit/component tests for CTA ownership, role descriptions, and localized auth
copy. Run focused tests, typecheck, and build if practical for the shared workspace.

**What I did:** Added focused role-CTA and localization/copy tests. Verified locale JSON
parses. The project-required `tdd-workflow` and `verification-before-completion`
skill files were not present under the configured global skill locations, so the
repository test/build gates were used directly.
**Checks:** focused role suite (44 passed); integrated `npm.cmd test -- --run`
(10 files, 91 tests); `npm.cmd run typecheck`; Windows-compatible
`npx.cmd next build`; locale JSON parsing; repository-wide `git diff --check`.
Integration review also corrected the existing onboarding progress/trial templates
from double to single braces and added regression assertions for rendered RU/KK/EN
copy. The package build script itself remains POSIX-only on Windows; pre-existing
lint warnings remain outside this scope.
**Status:** done; production verification pending deployment
