# Correction source download V1

Status: Accepted by Root 2026-10-13, before implementation.
Product owner: human owner, text-assistant continuation and refinement requests.
Root/module owner: Root. Reviewer: Test & Evidence Runner.
Additive consumer contract; LESSON_CORRECTION_UI_V1 remains unchanged.
No release or external mutation authority is granted by this contract.

## Outcome, ownership and interface

An ordinary methodologist can obtain the actual source document while reviewing
a ready correction, without leaving the editor or interpreting a fragment hash
as a file-integrity certificate. Voice and real dialogue history are separate slices.

CorrectionSources V1 owns only ephemeral file preparation, one Blob URL, status
and safe filename presentation. It consumes server-normalized citations and locale.
The parent keys it by preview identity/revision/seal/locale; the existing Panel
remount key also binds token, user, tenant, course and lesson.

Directed map: ready correction -> CorrectionSources -> loadCorrectionSourceFile
-> existing authenticated api -> GET documents/{UUID} and /download -> manual
browser download. There is no new route, storage, inference or business command.

Document bytes/metadata, methodologist authorization and tenant filtering remain
owned by documents/router.py. Server metadata currently has no historical byte
revision and citations have only document_id/locator/evidence_hash. Therefore
always label the file as CURRENT, explain that it may differ from the cited
version, and do not claim revision equivalence or mismatch detection. The hash
is of a fragment, not of the downloaded bytes. Historical byte retrieval is out
of scope and requires a new server contract.

loadCorrectionSourceFile(documentId, signal) returns {blob, filename, title}.
Validate UUID before I/O; require matching metadata ID, bounded nonempty filename
and title, MIME, positive safe-integer byte size; sanitize filename path/control/
bidi characters. Require a nonempty Blob of matching size/MIME. Both GETs use
the existing authenticated client and same signal. Check abortion between awaits;
never use a URL, bucket key or signed link from metadata. No blind retries.

## State, privacy, errors and concurrency

Idle -> loading -> ready | error. Clicking a source prepares a visible manual
download link and readable filename/title, not an iframe or executable preview.
One pending preparation and one retained Blob URL per component. A new request
clears/revokes the old URL. Cleanup aborts owned work and revokes its URL. Fresh
effect ownership must survive StrictMode replay. Abort-resistant late responses
must not create URLs or update a replacement context. Duplicate citations retain
their locators/hashes, but one file action per document suffices.

403/401: access unavailable; 404: source/file unavailable; malformed metadata or
file: invalid response; other/network errors: preparation failed, explicit retry.
Never display raw server errors, storage keys, tokens or file bytes in logs/URLs/
localStorage. User-selected browser download is the only durable output.
No preview/application consent or receipt state is changed by file preparation.

## Impact, scope and gates

| Owner | Impact | Protection |
|---|---|---|
| LessonCorrectionPanel | Consumer | Existing preview/apply/receipt/consent flow unchanged; add source UI and tenant remount key |
| lessonCorrection client | Compatible local export | Existing API payloads/parsers unchanged |
| Documents API / auth client | None | Existing exact endpoints/RBAC/tenant filters; no backend edits |
| Generation/assignments/workers/providers | None | No requests or configuration changes |

Read scope: named source/panel/client/tests, existing document GET/download handlers
and schemas, existing auth client and UI-004. Write scope: CorrectionSources.tsx,
LessonCorrectionPanel.tsx, lessonCorrection.ts, their focused tests, module index,
active plan, changelog/backlog and append-only test ledger. Root owns all writes;
reviewer is read-only except one ignored evidence artifact.

Definition of Ready: source owners verified, current-versus-historical limitation
explicit, primary guard passes, scope frozen. Definition of Done: public-interface
tests for transport validation/errors/abort and UI pending/ready/manual download/
cleanup/session/StrictMode/locales; existing correction/accessibility regressions;
type/lint/build and independent review. Full release suite once per candidate.
DEV browser and actual browser download remain separate NOT VERIFIED gates until
executed. No database/RLS changes, so no new migration or synthetic DB writes.

Performance: lazy only, no fan-out/prefetch; one retained document. Observability:
sanitized local test receipt only, no new telemetry. Rollback: revert this consumer
slice; no persisted state/migration. Existing flags hide the entire correction UI.
Stop on unlisted modules, a required historical revision interface, unexpected
dirty work, paid/external changes or failed mandatory tests; Root must record and
accept a new addendum before expansion. Accepted V1 is immutable; revisions use V2.
