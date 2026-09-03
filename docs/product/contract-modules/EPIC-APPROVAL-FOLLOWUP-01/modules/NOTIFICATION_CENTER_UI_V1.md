# Notification center UI mini-spec V1

## Identity [Core]

Accepted; document/template V1/V2; epic `EPIC-APPROVAL-FOLLOWUP-01`; frontend
module owner; product-owner approval inherited from epic; changes require V2.

## Responsibility [Core]

Present the notification HTTP projection accessibly on desktop/mobile and mark
an item read before following its allowlisted action path.

## Non-responsibilities [Core]

No deadline, recipient, unread, permission, outcome or provider inference.

## User-visible contribution [Core]

The bell is truthful: real count, no static dot, and distinct loading, error,
empty and item states with clear business wording.

## External interface and I/O [Core]

```text
listNotifications(limit) -> NotificationInboxResponse
markNotificationRead(id) -> Notification
markAllNotificationsRead() -> summary
```

Render localized kind-specific text, safe context and relative action only.

## Data ownership, invariants and state [Core]

No durable frontend data. `idle -> loading -> ready|error`; item `unread ->
marking -> read+navigate|error`. Badge exists only for count > 0. Fetch failure
is not empty. Read failure does not navigate. Existing TopBar controls remain.

## Errors, security and verification [Core]

Shared authenticated API handles auth. Retry is accessible. Unknown kind has
generic safe copy and no inferred privileged action. No token/PIN storage or
rendering. Vitest covers loading/error/retry/empty/count/read/navigation/unknown
kind and RU/KK/EN parity; browser QA covers narrow mobile.

## Implementation packet [Core]

Scope: TopBar, new notification client, locales and focused tests. Forbidden:
backend, auth interceptor behavior and unrelated layout.

## Extended requirements

Server makes duplicate reads safe. One bounded fetch per menu open prevents
stale response races. No analytics in V1. Revert may restore empty shell while
backend rows remain durable.
Every list/read request captures the current user, tenant and active role
identity. An auth or impersonation change invalidates the request and clears the
projection before an older response can render or navigate.

## Ready and done [Core]

Ready when DTO/copy/test cases are fixed. Done when focused tests, locale parity,
responsive QA and graph comparison pass.
