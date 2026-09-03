# Workflow notification contracts V1

## WorkflowNotificationIntentV1

Fields: tenant UUID, recipient user UUID, source delivery UUID, kind
`course_review_assigned|course_review_reminder|course_review_overdue`, bounded
context `{course_title, due_at}` and an allowlisted relative action path.

Forbidden: PIN, token, capability URL, encrypted payload, answer key, arbitrary
HTML, arbitrary external URL or raw provider response.

## NotificationInboxHttpV1

```json
{"items":[{"id":"uuid","kind":"course_review_assigned","context":{"course_title":"...","due_at":null},"action_path":"/course-review-requests/uuid","read_at":null,"created_at":"ISO-8601"}],"unread_count":1}
```

Newest first, limit 1..50. Unknown/cross-tenant read ID is 404. Mark-read is
idempotent. Additive response fields are compatible; kind semantics are fixed.

## ApprovalFollowupEmailV1

Reminder takes recipient identity, course title, existing action URL, due time
and idempotency key. Escalation takes requester identity, course title, admin
action URL, due time and idempotency key. Neither accepts PIN or rotation input.
