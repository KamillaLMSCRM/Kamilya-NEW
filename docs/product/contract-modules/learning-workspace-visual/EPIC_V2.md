# Whole LMS workspace redesign V2

Status: Accepted,2026-11-02. Supersedes the delivery scope of EPIC_V1.md, which
remains immutable history. Standard V2, ADR-0024/0025. Product owner: requesting
owner. Root/integration owner: OpenCode. Approved by: explicit owner request
"сделай весь редизайн как сделал курсы" after the remaining-screen inventory.
Independent reviewers are read-only and never accept their own implementation.

## Outcome and scope change

Every canonical screen in the Kamilya LMS Next application receives a deliberate
page composition matching `/courses`: hierarchy, task actions, filter/tool bars,
paper content areas, lists/cards/tables/forms/workspaces and honest state handling.
Shared colours or a frame alone are not completion. Existing V1 catalogue/shell
are retained as the reference, not rebuilt again.

V1's public-screen exclusion is explicitly superseded: login/registration,
invitations, bounded access/reviewer/candidate/kiosk forms, public certificate
verification and legal-document presentation are included. Legal text, consent,
OTP/auth challenges and token boundaries remain unchanged. Marketing in the
separate kamilya-landing repository, static video/presentation assets, backend,
models, providers, billing, schema, VERSION and release are excluded.

Starting code: de811b67995654e29c5699573beb23258aa04dc2, clean linked checkout
learning-visual-prod-20261102, branch feat/learning-visual-prod-20261102. Preserve
the inherited0f31ffd5 reviewer/session/security/settings fixes and VERSION69.
No merge, push, activation or production rollout is authorized.

## Shared presentation interface (root-owned)

Existing APIs/state owners -> existing route UI owners -> presentational design
components -> real built-page acceptance. No new server/data owner is introduced.

New module `features/workspace-design` exports:

- `WorkspacePage`: div wrapper; required `id` becomes `data-redesign-page`; optional
  title/description/eyebrow/icon/actions plus children/className. No fetching,
  inference, auth, storage or implicit navigation.
- `WorkspacePageHeader`: title/description/eyebrow/icon/actions; renders one h1,
  readable existing copy and wrapping actions. No invented translations or counts.
- `WorkspacePanel`: section with optional title/description/actions, children,
  className/bodyClassName, `padded` (default true), optional id. Existing table or
  card content can use padded=false; avoid unnecessary nested card borders.
- `WorkspaceToolbar`: wrapping paper toolbar, children/className; optional native
  attributes/role/aria-label supplied by its owner.
- `WorkspaceEmpty`: existing confirmed-empty title/description/icon/action;
  caller owns the distinction from error/loading/filtered empty.
- `WorkspaceStat`: label/value/hint/icon/tone; null/undefined display an em dash,
  never zero. No global totals, quality scores or grants derived from local arrays.
- `PublicWorkspace`: presentational main/div frame for bounded forms/document
  surfaces, existing logo and supplied copy/children. No automatic home link that
  would broaden kiosk/candidate/reviewer capability navigation.

Existing controls, validators, exact API payloads, active-role conditions,
ownership IDs, loading/retry/empty state, error recovery, callbacks and test stack
remain authoritative. New copy, if necessary, is RU/KK/EN. Semantic foregrounds,
generated dark CSS, portal inheritance and reduced-motion visibility remain V1
invariants. V2 may extend the same theme to public LMS pages; no new fonts/assets.

## Screen families and one-writer boundaries

| Family | Required surfaces | Ownership |
|---|---|---|
| Content/learning | overview, sources, generator, editor, quiz constructor, template adaptation, approval, learner dashboard/lists/reader/quiz/results/certificates | Named bounded writer packets after inventory |
| Delivery/reconciliation | assignments, learning paths/cycles, workbench, training log/mandatory matrix/procedures/retention/rules | Named packets; shared query/state services untouched |
| Workforce | staff/import/structure, positions/detail, cohorts, invitations, candidates, competencies | Named packets; staff/qualification/history owners unchanged |
| Tenant/platform/service | admin/team/kiosks/audit/settings/integrations/AI/forms, superadmin tenants/detail/operations/providers, profile/surveys/announcements | Named packets; no provider/tier/security mutation |
| Public/bounded access | login/register/invite/access/kiosk/review access/candidate runner/certificate/legal | Root; preserve all auth/capability/consent/content invariants |
| Shared primitives/theme/testing/docs | design module, global CSS/RootLayout as needed, coverage manifest/tests/browser fixtures, canonical docs | Root, serialized interfaces/integration |

Every discovered app/page.tsx is classified as canonical UI, inherited owner,
redirect/alias, or retained non-product example. Thin aliases reuse their one
canonical redesigned owner; no duplicate screens. Inventory/coverage must catch
unlisted routes and dynamic detail states rather than declaring "all" from a
sample. At most two independent leaf writers, no shared-file overlap. Root owns
interfaces, critical blockers, final diff/verification and release judgement.

## Per-screen exit contract

1. Page header and action hierarchy, and a substantive body composition change
   (toolbar/panels/form grouping/reader outline/result/list/table layout), not only
   a theme class/import/marker. Keep actual records, copy and protected states.
2. Responsive readable layout with long RU/KK/EN labels, text fit and real pointer
   targets. Native bounded access/OTP/time limits and privileged no-write preview
   must survive; no fake success/readiness/source provenance/answer review.
3. Focused existing behavioural neighbours plus new presentation regressions.
   Source declarations or a marker alone do not prove visual acceptance.
4. Machine-readable route coverage maps route -> canonical owner -> redesigned
   composition; aliases/redirects are explicit, with executable coverage of the
   discovered page inventory. Runtime uses routeRegistry, not this test inventory.
5. Built browser acceptance uses explicit synthetic API contracts and all roles;
   no live backend passthrough, paid model calls, real tenant writes or entitlement
   bypass. Cover loading/error/empty/populated and critical commands proportionally.
6. Independent requirements/correctness/accessibility/complexity review, root
   screenshot review, final all-writer freeze before full web/type/lint/build.
   Publish a precise remaining-gate list; do not call partial screen coverage done.

## Completion / authority

Done locally means every canonical page family has a redesigned owner, route
coverage and proportional visual/functional evidence, reviewed isolated commits,
clean checkout, retained original prototypes and safe cleanup. External CI,
deployed DEV/business/real-device acceptance and exact-SHA production release are
separate owner gates. No version/tag/release/merge/push here. Frontend rollback
reverts the isolated visual source range, never data/history/schema.

Stop on an unlisted shared interface, behaviour/schema/data ownership change,
needed provider/billing/auth bypass, secret access or external mutation. Root
updates the accepted packet before that work; local access is not authorization.

## Active owner scope amendment R1

Owner subsequently excluded dedicated admin and superadmin screens for now.
Those family rows above are DEFERRED, not implementation targets or completion
claims. Shared primitives/theme may naturally apply, but do not recompose tenant
configuration/team/kiosk management/audit/integrations/AI-provider/billing/platform
operations/tenant detail or superadmin login/tenant-registration administration.

Methodologist workforce, invitations, training log and evidence/review workflows
remain included even when their canonical implementation lives under `app/admin`.
Canonical `/admin/course-approvals` configuration is deferred; the author/reviewer
flow's own status/request/review components remain included. Generic user login,
invitation and bounded student/reviewer/candidate/kiosk access forms remain in
scope; route coverage must explicitly distinguish those from admin-only pages.
