# Kamilya LMS navigation and module applicability audit

Date: 2026-07-26  
Scope: every route currently exposed in the sidebar for `methodologist`,
`admin`, `student` and `superadmin`  
Evidence: route registry, page implementation, invoked API endpoints, current
role policy and production behavior verified during the 2026-07-26 release

## Decision scale

- **Keep** — the module has a distinct user job and belongs to the current role.
- **Improve** — the module is applicable, but its flow or presentation is
  incomplete.
- **Move** — the job is valid but belongs in another navigation group or role.
- **Merge** — a separate top-level entry duplicates an existing workflow.
- **Hide** — the flow is too incomplete to advertise in the current product.

## Methodologist

| Section | What it currently does | Applicability and ownership | Decision |
|---|---|---|---|
| Dashboard | Course totals, enrollment statistics, recent courses and AI jobs | Correct operational start for the learning owner. It should answer what requires attention, not repeat the full training log | **Keep; improve** with overdue/review/failed-job actions |
| AI course generation | Upload/select sources, compatibility check, generation job, review, lesson editing, AI chat and publication | Core differentiator and correctly owned by the methodologist. The 1,400-line screen contains too many stages and repeats document upload | **Keep; improve** by using the document library as the canonical source picker and splitting the UI into bounded stages |
| Courses | Course catalog, manual creation, SCORM import, review, publication, archive and deletion | Canonical course inventory. It is distinct from generation because it manages the complete lifecycle of all course types | **Keep**; remove the duplicated `methodologist || methodologist` role condition and clarify course origin/status filters |
| Test constructor | Test and question editing plus an embedded assignment panel | Required methodologist workflow. The screen is overloaded and mixes authoring with delivery | **Keep**, but make `Constructor` and `Assignments` explicit internal tabs |
| Documents | Upload, indexing, versions, usage, download, reindex and deletion | Correct canonical tenant source library. It overlaps with direct uploads inside AI generation | **Keep** as the only document-management surface; AI generation should select from it |
| Learning programs | Versioned ordered curricula, required/optional courses, audience assignment, dates and learner progress | Clear distinct job: multi-course learning program rather than one course assignment | **Keep** |
| Cohorts | Creates groups, selects users and courses, then materializes assignments | Grouping users is useful. Storing and applying courses here overlaps with learning programs and direct course assignments | **Improve/reshape**: cohorts should primarily define reusable audiences; assignments should be launched from Courses or Programs |
| Competency catalog | Creates competencies and links them to positions and courses | Valid reference directory, while position cards apply those competencies to a concrete role. The distinction is real but not obvious from labels | **Keep**, group with Positions under `Qualifications` |
| Staff schedule | Excel/CSV import, manual employee creation, structure tree, department/position course rules and tenant-wide courses | Import and organizational structure belong here. Course-rule and company-course tabs overlap with Positions and Assignments and make the screen too broad | **Keep import + structure**; move training rules to qualification/assignment workflows |
| Invitations | Email invitations, invitation links, status, expiry and resend | Correct methodologist ownership because it creates learners, not system administrators | **Keep** |
| Positions | Position directory, job instructions, qualification profile, competencies, mandatory courses and onboarding test | Correct methodologist workflow and the natural aggregate for position requirements | **Keep**; use it as the destination for position-level training rules currently duplicated in Staff |
| Course assignments | Selects a course, assigns active learners and manages enrollments | Correct atomic delivery workflow for one course; distinct from a multi-course program | **Keep** |
| Test assignments | Deep-links to the assignment panel on the same `/quizzes` page | Applicable function, but not a separate module: both navigation entries open the same large screen | **Merge** into one `Tests` menu item with internal tabs |
| Training log | Filtered learning records, status/progress/scores/certificates, summaries and reader-facing CSV | Correct control and evidence surface for the methodologist | **Keep** in `Control and results`, not mixed with content creation |
| Post-course feedback | Creates one rating question; learner responds after completion | Collection works, but the methodologist cannot view responses or aggregates | **Hide now**; backlog requires analytics and operational follow-up |
| Announcements | Draft and synchronous email delivery to the tenant or one course audience | Useful foundation, but `Notifications` conflicts with the top-bar bell and delivery lacks preview, scheduling, retry and recipient details | **Hide now**; rebuild as `Mailings/Announcements` |

## Tenant administrator

| Section | What it currently does | Applicability and ownership | Decision |
|---|---|---|---|
| Admin dashboard | Tenant plan/trial usage, remaining limits, system-team preview and governance quick actions | Correct governance-only home; does not expose learning operations | **Keep** |
| Team management | Creates and manages tenant administrators and methodologists, including multiple roles for one email | Correct system-account workflow and intentionally excludes learners | **Keep** |
| Kiosks | Creates kiosk links/QR, activates devices, selects position scope and shows access logs | Device security and activation belong to admin. Choosing learning content does not | **Keep** device management here; methodologist must own courses assigned to kiosk audiences |
| Settings | Loads and edits `/users/me`, mainly personal name/language/profile data | The page is a personal profile but is presented as tenant configuration and is visible only to admin | **Move/rename** to `My profile` in the user menu; create a separate tenant settings screen only when company-level fields exist |
| Notification integrations | Configures WhatsApp, SMTP/email and Telegram connections | Correct tenant infrastructure responsibility. Methodologist should use configured channels but not own credentials | **Keep** |
| Certificate template | Tenant certificate appearance and issuer/signature fields | Branding and issuer identity are tenant governance; course completion rules remain methodologist-owned | **Keep**; complete i18n and provide a reliable preview |

## Learner

| Section | What it currently does | Applicability and ownership | Decision |
|---|---|---|---|
| Dashboard | Current progress and the next course to continue | Correct start screen | **Keep** |
| My courses | Assigned course catalog and course entry points | Correct primary learning inventory | **Keep** |
| My tests | Independent assigned/enrolled tests, availability and deadlines | Useful because tests can be assigned outside the immediate lesson flow | **Keep** |
| Certificates | Issued certificate list, view and download | Required completion evidence | **Keep** |
| Learning programs | Shows assigned programs, order, progress and locked/available steps, but has no sidebar entry | The implemented learner workflow is applicable and should not require a hidden direct URL | **Add to learner navigation** after final product copy review |
| Post-course feedback | One rating after course completion, currently reachable only by direct route after manager module is hidden | Incomplete until the manager can use collected results | **Keep hidden** with the manager module |

## Superadministrator

| Section | What it currently does | Applicability and ownership | Decision |
|---|---|---|---|
| Platform home | Tenant summary/top 10, provider summary and operational links | Correct platform overview, but the sidebar label is derived from `Tenants` and understates the actual dashboard | **Keep; rename** sidebar item to `Platform` |
| Tenant management | Full list/detail, lifecycle actions, plan/trial data and first-admin creation | Core superadmin responsibility, currently reached through the platform dashboard rather than its own sidebar item | **Keep**; add a direct `Tenants` navigation child when the platform menu is expanded |
| AI providers | Encrypted provider keys, activation, test, status and error information | Correct high-privilege platform operation | **Keep**, with audit logging and strict secret handling |

## Cross-module findings

### P0 — current navigation truth

1. Hide Feedback and Announcements from sidebar and command palette while
   retaining guarded routes and data. **Implemented in this change.**
2. Current documentation must not instruct users to open hidden modules.
   **Implemented in this change.**

### P1 — first-tenant clarity

1. Add **Learning programs** to learner navigation.
2. Replace the admin `Settings` item with **My profile** in the account menu;
   do not present personal fields as tenant settings.
3. Collapse `Test constructor` and `Test assignments` into one **Tests** entry
   with URL-backed tabs.
4. Make Documents the canonical source library and remove duplicate document
   intake from AI generation.
5. Reframe Cohorts as reusable audiences; start course/program assignment from
   the object being assigned.

### P2 — information architecture consolidation

1. Create a `Qualifications` group containing Positions and Competency catalog.
2. Keep Staff focused on people/import/structure; move course rules out of it.
3. Create a `Control and results` group for Training log and future survey
   analytics.
4. Split kiosk device administration from learning-scope configuration.
5. Rename the superadmin home to Platform and expose Tenants directly.

## Overall conclusion

The four active roles are now separated correctly at the capability level.
Most visible modules are applicable, but the methodologist surface still
exposes implementation boundaries rather than a clean task sequence.

The target methodologist information architecture should be:

1. **Overview:** Dashboard, Training log.
2. **Content:** Documents, AI generation, Courses, Tests, Learning programs.
3. **People and assignments:** Staff, Invitations, Cohorts, Course assignments.
4. **Qualifications:** Positions, Competency catalog.
5. **Communications:** hidden until the backlog gate is complete.

This preserves every real workflow while removing unfinished modules and
reducing duplicated course-to-audience configuration.
