# Editor correction handoff V1.1 — recover unknown outcomes before replacing intent

Status: Accepted for bounded local implementation,2026-10-14.
Approved by: Root within owner's continued assistant work. Product owner remains
repository owner; no release/provider/DB/runtime authority added. Preserves V1;
this addendum governs its correction-panel recovery invariant. Reviewer: independent
Test & Evidence Runner. Change control: Root accepts any further versioned expansion.

## Trigger and decision

Independent review reproduced two existing reset paths incompatible with a safe
handoff: locale/source change discarded an unresolved create key, and instruction
editing after lost transport did the same. Client abort does not prove server
cancellation. Three locale/source/server-pending regressions RED before repair;
the unknown-instruction-edit case is now required too. Root owns this correction
after two review rounds; no source or assertion weakening is delegated.

Correction panel owns the pending/unknown state, so enforce recovery there rather
than duplicating it in chat/page. Its instruction editor and NEW preview action
are blocked for an unknown create key, server-pending plan or unknown restored
receipt lookup. Same-key replay and same-plan GET recovery remain available;
known structured rejection allows editing normally. Do not drop the original
locale/payload/locator or issue a second provider request under a new key.
Existing ordinary lesson manual editing is unchanged.

Locale/source changes may invalidate eventual proposal application, not erase an
unresolved operation. A ready result bound to old locale/saved text is displayed
as invalid for application, with consent reset; only after its outcome is known
can a new candidate be staged. Known pending plans retain their ID and original
prepared locale through GET refresh. A failed restore of application/preview state
gets an explicit retry of the SAME canonical reads, without create/apply/inference.
Restore entry uses only the existing opaque URL plan locator and owner validation.

## Impact and verification

Write scope adds only correction-panel recovery UI/guards and its existing/new
tests, this immutable addendum/index/plan/error journal. Existing create/load/apply/
receipt interfaces, seal/idempotency, server service/schema/RLS/provider/budget,
auth/flags/roles, source files/course/manual editor/quiz/assignments remain unchanged.
No new data owner, durable state, endpoint, retry scheduler or dependency.

Unknown errors disable new intent and explain same-key/read recovery in existing
RU/KK/EN UI; pending/errors are not success receipts. Tests cross the same staging/
UI interfaces: deferred abort-resistant transport, locale/source reset, unknown
edit refusal, structured-rejection edit admission, pending status GET, offline
restore→same-ID reads, exact-key replay, no extra create/apply/PATCH. Retain original
RED/failed reviews; new source hashes and focused/full/types/lint/build required.
Ready: Root accepted these confirmed seams before repair. Done locally: regressions
and independent review pass; DEV/browser/model/release NOT_RUN until separately
authorized. Rollback is frontend-only revert; no schema/data/config rollback.
Stop on unlisted owner/API changes or a requirement to discard unknown results.
