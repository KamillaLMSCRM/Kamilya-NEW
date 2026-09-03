# Workflow notification contracts V2

**Status:** Accepted
**Supersedes:** `WORKFLOW_NOTIFICATION_V1.md`
**Reason:** The V1 semantic operations did not fully specify the HTTP seam.
**Approved by:** Root owner as a compatible implementation clarification under
the accepted EPIC; no business rule, role or production authority changed.

## WorkflowNotificationIntentV1

Unchanged from V1: tenant UUID, recipient user UUID, source delivery UUID, kind
`course_review_assigned|course_review_reminder|course_review_overdue`, bounded
context `{course_title, due_at}` and an allowlisted relative action path.

Forbidden: PIN, token, capability URL, encrypted payload, answer key, arbitrary
HTML, arbitrary external URL or raw provider response.

## NotificationInboxHttpV1

All routes use the existing authenticated tenant-user transport.

```http
GET /v1/notifications?limit=20
```

`limit` is required to be in `1..50` and defaults to 20. There is no cursor in
V1. Items are the newest bounded rows; `unread_count` counts all unread rows for
the authenticated tenant/user, not only the returned page.

```json
{"items":[{"id":"uuid","kind":"course_review_assigned","context":{"course_title":"...","due_at":null},"action_path":"/course-review-requests/uuid","read_at":null,"created_at":"ISO-8601"}],"unread_count":1}
```

```http
POST /v1/notifications/{notification_id}/read
```

Returns the updated notification object. On success `read_at` is non-null.
Repeated calls return the same logical state. Unknown, other-user or
cross-tenant IDs return `404` and disclose no ownership information.

```http
POST /v1/notifications/read-all
```

Returns `{"updated": <non-negative integer>, "unread_count": 0}`. It updates
only the authenticated tenant/user rows and is idempotent.

Backend-owned action-path allowlist:

```text
/course-review-requests/<uuid>
/admin/course-approvals?courseId=<uuid>
```

No scheme, host, fragment, traversal segment or additional query key is allowed.
Frontend navigates only after a successful mark-read response. Unknown future
kinds use generic localized text and no action until their contract is added.

## ApprovalFollowupEmailV1

Unchanged from V1. Reminder and escalation interfaces do not accept PIN or
credential-rotation input.
