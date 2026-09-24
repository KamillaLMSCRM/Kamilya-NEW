# Methodologist dashboard — action navigation V2

Status: implementation in progress.

## Outcome

The dashboard is an operational entry point rather than a static report. A methodologist can open the canonical training log from a supported metric or a specific priority assignment, see the same filter restored in the interface, and return to the learning overview without relying on browser history.

## Browser contract

- Canonical route: `/training-log`.
- Supported browser filters mirror the operational filters exposed by the current training-log screen: `enrollment_id`, `course_id`, `department_id`, `position_id`, `status`, `delivery_type`, `date_from`, `date_to`, `search`, and `history`.
- Dashboard links add `return_to=/dashboard`.
- `return_to` accepts only the allow-listed local dashboard path. External, protocol-relative, malformed, or unknown paths are ignored.
- API-only pagination/export parameters are not accepted from dashboard links.

## Truthful mapping

- `not started` -> `status=assigned`;
- `in progress` -> `status=in_progress`;
- `completed` -> `status=completed`;
- `overdue` -> `status=overdue`;
- a priority learner -> exact `enrollment_id` plus `course_id`;
- the action-center link -> the unfiltered training log action-center anchor.

Aggregate indicators without an exact server filter remain informational. In particular, failed quizzes, exhausted attempts, weak questions, all problem assignments, and generation-job states must not masquerade as a different filter.

## Acceptance

- [x] URL parsing rejects unknown and malformed values.
- [x] URL building emits only supported canonical parameters.
- [x] Training-log controls restore from and update the canonical URL.
- [x] A safe visible return link appears for dashboard-originated navigation.
- [x] Exact priority-assignment navigation is tenant-scoped by the existing API and RLS contract.
- [x] Supported dashboard metrics are keyboard-operable links; unsupported metrics remain visually passive.
- [ ] Unit, type, lint, DEV browser, and production browser acceptance pass.
