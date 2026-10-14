# Editor correction handoff V1.2 — explicitly review a plain-text follow-up

Status: Root accepted for bounded local repair, 2026-10-14.
Owner: repository owner; latest request covers live DEV findings and repair before
production. Root owns integration and review; independent Test & Evidence Runner
reviews final source. V1/V1.1 remain unchanged. This adds no execution authority.

## Observed failure and decision

Actual DEV50-R2 first response supplied a valid selected-lesson replacement.
The subsequent "make this version simpler" preserved the source constraints but
returned only ordinary reply text and no replacement marker. The earlier card
remained usable; the methodologist could not send the latest answer for review.
Preserve the exact synthetic provider response as a deterministic replay fixture.
Do not retry inference automatically, parse prose into executable metadata, demand
a magic user prompt, or treat prior model output as a source or a receipt.

For an ordinary selected-lesson reply after a valid replacement in the SAME open
session, offer an explicit "Review this reply against sources" action only when:
the existing correction callback is present; the response came from the current
lesson request (not audience/course/module intent); server history_eligible is
strictly true; it has nonblank bounded reply text, no replacement payload and no
audience recommendation; the prior card targets the same selected lesson.
Unknown eligibility, refusal, request error, audience result, initial advice,
other target/context and missing correction owner do not admit this action.

Only deliberate selection transfers the FULL latest reply and its own original
instruction as UNVERIFIED text through the existing <=4000-codepoint builder.
No truncation, inference, HTTP mutation, create, apply or legacy PATCH at handoff.
Oversize input is rejected locally. Explain that this is an answer, not an approved
edit; the source-owned preview may differ. Existing page/panel auth/role/flags,
dirty/busy/context/unknown-result guards remain the decisive staging boundary.
Application still requires current saved draft, original sources, human review,
explicit consent and exact server seal, receipt and post-application reload.

## Impact and acceptance

Write only AIChatPanel, its focused handoff tests/replay fixture, this addendum,
module index and existing canonical docs. No callback/interface/API/schema/model/
provider/server/DB/roles/flags/retention changes. No new legacy apply path.
Tests must replay the exact plain-text result and cover initial/refusal/unknown
eligibility/audience/wrong prior target/no owner, oversize local rejection and
pending request disablement, no silent old-card substitution and no extra fetch.
Retain RED before implementation; then focused/neighbor/full/types/lint/build,
independent source review, new exact-SHA DEV and real model/source/apply/reload.
Root requires final production same-flow acceptance after normal release gates.
Rollback is frontend-only; retained normal QA receipts/audits are not erased.
