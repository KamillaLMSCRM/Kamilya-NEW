# Lesson correction learner-history proof V1

Status: Accepted for LOCAL/owned synthetic DEV implementation, 2026-10-06.
Owner: root integration owner under the approved correction acceptance plan.

## Scope and public seam

Extend only the disposable correction application verifier. Add an exact opt-in
learner-history contour to its existing owned-schema gate; default application
and lifecycle contours retain their table set, check set and evidence labels.
No application/model/migration/public-schema/provider/production writes.

The opt-in clones only enrollments, quiz_attempts and certificates in addition
to the existing tables. Preserve actual public model shapes and catalog-bound
immediate local FKs, including release/enrollment/quiz/course/self/user links
where both endpoints are cloned. Require those minimum history relationships,
FORCE RLS and existing synthetic tenant policy; no guessed schema or public FK.
External nullable assignment links remain unpopulated, not a proof of those
separate assignment features. Reuse the existing canonical DEV identity, lms_app,
three-connection cap, bounded statements/600-second verifier, exact cleanup and
fresh public-metadata-neutrality readback. No Docker PostgreSQL or limit changes.

Seed one ordinary synthetic student, one completed release-bound enrollment,
one completed passed attempt with nonempty answers/evidence/hash/points, and one
active certificate with metadata/PDF hash. Bind the existing historical content
release to course.current_release_id before preview. Never write a PDF or call
a real model/storage/email provider. Snapshot all columns of the three nonempty
history tables, full historical release row and course release pointer. Compare
canonical SHA256 at successful concurrent apply/replay, later-edit replay and
wrong-seal refusal. Require row counts and populated evidence; an empty set can
never pass. Do not expose IDs, rows, answers, secrets or model input in receipts.

## Verification and authority

Test-first public proof helper must refuse empty/missing history, changed answers,
changed certificate metadata, release-row changes and release-pointer changes.
Driver binds exact source hashes before/after the owned run, exclusive evidence
creation and exact required check set. Learner-history VERIFIED is permissible
only for a passing opt-in result with all four history checks; a failed run is
NOT_VERIFIED. Old receipts stay unchanged and do not inherit this new proof.
Root owns SQL fixtures/driver; cheap agents may review/test local scope only.
The opt-in matrix keeps the existing application checks except its destructive
empty0177 down/up probe: that older contour would remove the0178 receipt policy.
Retain populated0177 downgrade refusal, and keep the historical default empty
probe unchanged. The new matrix is23 application checks plus4 history checks.

Stop on catalog/identity/ACL/cleanup/neutrality/source drift or unknown outcome.
No weakening assertions, dropping historical failures, public activation or
automatic retry. This is learner-record preservation proof, not real-provider
semantic quality, signed-PDF verification, browser acceptance or release GO.
