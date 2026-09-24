# Methodologist dashboard — operational overview V1

Status: implemented locally, awaiting DEV and production acceptance.

## Outcome

The first screen answers four operational questions without requiring the methodologist to know the product navigation:

1. Does training need attention now?
2. What share of current assignments is complete?
3. Which learners or assessments should be handled first?
4. What is happening with courses and course-generation jobs?

## Information hierarchy

1. **Needs attention** — problem assignments, weak questions, open actions, overdue actions, and the first three affected learners.
2. **Training health** — completed/current total, not started, in progress, overdue, failed, and exhausted attempts.
3. **Content in progress** — published/draft courses and only active or problematic course-generation jobs.
4. **Quick actions** — create a course, review courses, or open the training log.
5. Role-specific onboarding remains available below the operational overview and no longer displaces it.

## Data ownership and interface

The dashboard does not introduce a second learning-statistics implementation. Its primary interface is `GET /v1/admin/learning-actions`, which already owns:

- the current training-log summary;
- attention items;
- weak-question signals;
- open and overdue learning actions.

The frontend adapter in `apps/web/src/features/dashboard/api.ts` combines that read model with the existing course and AI-job lists. The pure model in `model.ts` owns UI derivation and filtering. The page itself only selects the role-specific dashboard.

Tenant administrators do not request learner-level information. Their landing screen remains limited to organisation setup/navigation in accordance with ADR-0012.

## Truthfulness rules

- Missing learning data is shown as unavailable, never as zero.
- A zero completion percentage is shown only when the read model is available and the current-assignment total is actually zero.
- Cancelled and completed generation jobs do not occupy dashboard space.
- Unknown non-terminal generation statuses remain visible as requiring attention.
- Historical cancelled/superseded assignments do not enter current training-health totals.

## Acceptance

- [x] One primary learning read model; no duplicate call to `/training-log/summary`.
- [x] Methodologist-only access to learner-level dashboard data.
- [x] Abort stale requests on identity or tenant change.
- [x] Russian, Kazakh, and English user-facing copy.
- [x] Responsive grid with no fixed-width horizontal board.
- [x] Unit coverage for healthy, partial-failure, empty, failed-job, and role-boundary states.
- [ ] DEV browser acceptance at desktop, 1024 px, and mobile width.
- [ ] Production browser acceptance with exact deployed SHA readback.
