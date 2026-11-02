# Production workspace visual design V1

Status: Accepted implementation packet,2026-11-02; contract standard V2,
ADR-0024/0025. Product owner: requesting owner. Root/integration owner: OpenCode.
Approved by: owner challenged the omitted production design and `/courses`;
root accepts the bounded correction below. Independent reviewer: read-only after
source freeze, never the implementation writer. No release authority is implied.

## Observable outcome and finding

The prior UX branch5ec30252 changed learning/authoring behaviour but did not
change `/courses`, global theme or shared visual primitives. Its contract even
excluded a global styling overhaul. This was a scope/acceptance omission, not a
browser cache or successful production redesign. New work starts from refetched
origin/master076dba752432b4d161e0a419660ff277bc4c3e3d, not the older UX tree;
preserve the intervening release/security/settings fixes and VERSION0.11.68.

Deliver the approved prototypes' actual visual language in the authenticated
application, including its formerly omitted course catalogue. Design references
remain in the preserved `learning-workspace-ux-20261101/docs/prototypes` checkout;
they supply appearance only, never production records or authority.

## Visual contract

- Cool near-white canvas, white paper surfaces, navy ink, restrained blue primary,
  readable muted text, fine slate borders,12–16px corners, light purposeful shadows.
  Use semantic tokens, not new hard-coded component colours or model-made images.
- Authenticated theme only; public/login/landing retain their existing brand.
  Theme tokens must reach portal dialogs too, support dark mode, and disappear on
  leaving the authenticated shell. Use the existing font families/dependencies;
  no added font/package/model assets. Remove grain/decorative gradient covers.
- Shell: deliberate sidebar/header/content hierarchy, quieter readable section
  labels (at least12px), precise active navigation, comfortable desktop spacing and
  usable mobile drawer. Preserve all role, help/support/guide/notification controls.
  No renamed canonical routes or merging of active-role capabilities.
- `/courses`: own courses are the primary content, not an industry-template
  storefront. Title/description/actions, visible search/status filters, compact
  legible course cards, explicit native/SCORM/AI/review states, focused next actions.
  Templates remain accessible as a secondary expandable section below the list.
  Do not remove manual creation, SCORM import, blueprint adaptation, publication,
  assignment, archive/delete or their existing server guards.
- Readiness/score/recipient/progress/global counts may not be fabricated. A count
  of loaded results must be labelled as the current list, not a global total.
  Loading/error/retry/empty and filtered-empty are distinct; no invisible cards
  dependent on animation. Reduced motion must retain visible content.
- New copy is RU/KK/EN. Preserve question keys, evidence/OTP, assignment history,
  learner focused mode, approved snapshots and dirty drafts from the existing UX.

## Module/ownership map

`existing APIs -> course catalogue presentation -> authenticated shell/tokens`

| Module | Writer | Permitted files | Protected interface |
|---|---|---|---|
| Catalogue | Bounded writer C | courses/page.tsx; new features/course-catalog/*; its new visual tests | Existing endpoints/payloads/roles/routes and source IDs |
| Workspace theme/shell | Root | globals.css; Layout/Sidebar/TopBar; UI button/input/card hooks if needed; focused tests | Auth/session/navigation/notifications/command palette unchanged |
| Browser acceptance/integration/docs | Root | Dedicated synthetic e2e fixture/spec/config; canonical design/changelog/readiness/handoff/ledger | No live API passthrough, business/provider writes or deployment |
| API/DB/workers/providers/dependencies/version/public pages | None | No writes | Negative-space diff and public-theme check |

New local presentation may consume the same course API; it must reject obsolete
read responses/actor transitions rather than expose another scope's cards/actions.
No new data owner, storage, migration, permissions or automated mutation is added.
Shared-file ownership is serialized; leaf writers stop at an unlisted path.

## Acceptance and rollout

1. Capture real `/courses` before/after on identical synthetic data, not only the
   reader/editor prototypes. Assert actual computed theme, card hierarchy and
   primary-list-before-templates; inspect screenshots at1440/1270/768/390/360.
2. Verify keyboard focus, pointer hit targets, mobile drawer/collapse, long RU/KK
   labels, dark/reduced-motion/zoom, loading/error/empty/filter recovery, portal
   contrast and no document-level horizontal overflow. Include public-theme
   negative space and representative reader/editor/assignment screens.
3. Focused behavioural/role/action/blueprint regressions during edits; independent
   requirements/correctness/accessibility/complexity review after assembly.
4. Freeze ALL writers before one full web suite plus lint/type/build. Browser tests
   use the real build with strictly intercepted synthetic APIs; no paid calls or
   real tenant credentials. Keep failed evidence separate from accepted gates.
5. Root reviews final diff/clean tree and prepares an isolated commit/handoff.
   Push, merge, release/version change and production deployment require a
   separate owner decision. Local screenshots/build are not deployed acceptance.

Rollback is an isolated frontend source revert; no data reset/backfill or schema
downgrade. Stop on unsupported feature simulation, widened roles, changed API or
paid/provider/release requirements. Record any changed visual contract explicitly;
do not silently return to behaviour-only acceptance.

## Accepted visual compatibility addendum R1

Independent review found eight existing hard-coded `text-white` consumers of
semantic primary/success fills in ai/generate, courses/[id], courses/quiz/[quizId]
and courses/templates/[blueprintId]. The new dark fills require their matching
semantic foregrounds. Root may change those eight class tokens only, plus a
bounded AST regression and actual dark-control contrast checks. No handlers,
API/role/content/quiz semantics or publication gates change. Catalogue cards must
also retain a usable minimum width with an expanded tablet rail; document-level
overflow alone does not prove that sibling actions do not overlap.

## Accepted visual compatibility addendum R2

The existing modal uses the page canvas as its surface. Root may add a semantic
`dialog-surface` alias to shared CSS/Tailwind and change only the modal background
class: public default remains its original canvas; authenticated dialogs use the
paper/card token, including dark mode. Portal styles must be measured after the
workspace has mounted, not before auth/hydration. Test locale initialization is
restricted to the allowed loopback document origin, never `about:blank` frames.

## Accepted visual compatibility addendum R3

Manual inspection of the built "dark" screenshot found a light canvas despite a
passing DOM-class check. Generated CSS confirmed Tailwind had removed the scoped
`.dark` base rule because application content did not contain that literal class.
Use equivalent root attribute matching `[class~="dark"]` to retain the rule without
changing the global/public dark-utility policy. Prove this with real PostCSS/
Tailwind output and require computed dark tokens in browser contrast/screenshot
gates. A DOM class or contrast value in the wrong mode is not dark acceptance.

## Integration baseline addendum R4

While this visual work was in progress, origin/master advanced with the ordinary
review-transport/session-fencing fix and VERSION0.11.69. Before final acceptance,
this owned feature branch fast-forwarded to
`0f31ffd5812f1751fc0f1c98f716e65580b1b2ae`; all visual changes were preserved.
The earlier076 before screenshots remain valid for appearance comparison because
the catalogue, theme and shell were unchanged by those two upstream commits.
The active comparison/testing base is now0f31ffd5, VERSION remains0.11.69, and the
visual diff must not modify upstream API/review transport, release or dependency
changes. This was not a feature merge into master or a deployment. Rebuild and
run the final browser/full gates on this synchronized base, not the earlier build.
