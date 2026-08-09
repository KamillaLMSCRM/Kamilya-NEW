# ADR-0020: Candidate assessment is isolated from workforce learning

## Status

Accepted for incremental implementation.

## Context

Pre-employment assessment is an external applicant workflow. The current
employee invitation flow is intentionally coupled to a tenant `User`, a
corporate email OTP, learner activation and staff records. Enrollments, course
completion, certificates and training evidence similarly assume a tenant-owned
employee user and, in several cases, an enrollment-backed content release.

Creating fake departments, positions or staff users for applicants would pollute
staff import, assignment rules, learner trial limits, invitations, training
log, certificates and compliance evidence. It would also violate the evidence
ownership constraints that deliberately bind an event to a real tenant user and
compatible enrollment.

## Decision

Implement candidate assessment as a separate, methodologist-owned domain.

- A tenant-scoped campaign selects a published assessment/content release,
  instructions, expiry and attempt policy. A nullable position reference may
  be retained only as hiring context; it never creates staff membership.
- Candidate profiles contain only the minimum applicant identity/contact and
  consent/retention metadata needed for that campaign.
- Candidate attempts contain a frozen assessment/content snapshot, answer
  snapshot SHA-256, score, lifecycle and attempt number. Submitted attempts
  are immutable; corrections or review notes are append-only records.
- Opaque, hashed, expiring candidate links bind a candidate to a campaign. They
  use a bounded public token resolver that derives and establishes tenant
  context server-side. Public callers never supply a tenant id and do not get
  a `User`, refresh cookie or standard LMS login session.
- Candidate delivery may reuse the existing notification worker's operational
  pattern (fresh DB session, tenant context, row locking, idempotency and
  bounded retry), but not `UserInvitation` tables or `/accept-invite` routes.
- Candidate results do not create `Enrollment`, `Certificate` or
  `TrainingEvidenceEvent`. They remain outside `/staff`, `/admin/team`,
  `/invitations`, `/assignments`, `/learning-paths` and `/training-log`.

The canonical methodologist UI is `/candidate-assessments`, with a public
candidate flow at `/candidate-assessment/[token]`. Tenant admin has no normal
candidate workflow. A separate candidate-attempt entitlement is required;
candidate profiles must not consume the current trial learner limit.

All candidate tables are tenant-scoped and require `tenant_id`, ownership
validation, RLS, `FORCE ROW LEVEL SECURITY`, `lms_app` runtime grants without
`BYPASSRLS`, and negative cross-tenant/API tests. Public routes also require
hashed-token rate limiting and no disclosure of tenant or candidate identity
from an invalid or foreign token.

## Consequences

- Applicant data and decisions stay separate from employment, learning and
  regulated training evidence.
- The public workflow has its own consent, retention, export and access-log
  requirements; it is not a variation of staff invitation.
- Trial product policy must explicitly choose whether candidate assessment is
  disabled or has a separate bounded allowance before self-service exposure.
