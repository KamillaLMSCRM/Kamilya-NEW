# WB-LESSON-CORRECTION-PREVIEW V1.3

Accepted local freshness impact addendum, 2026-10-05, root/module owner.
Preserves V1/V1.1/V1.2, extending exact write scope to the existing course release
snapshot builder and one focused database-free regression file.

`build_course_release_snapshot` gains optional `populate_existing: bool = False`.
All its child/document/SCORM SELECT statements forward this execution option.
Default false preserves existing publication/approval callers and output schema.
The correction resolver passes true; its initial lesson/module/course SELECT
already refreshes current course fields. No global session expiration, changed
transaction isolation, domain write or publication change is introduced.

Reason: initial resolution loads related ORM identities in the same session.
A second SELECT alone may retain old non-target lesson/block/quiz/module fields,
defeating the complete-course change seal. Forced refresh prevents that cached
identity reuse. It is not an atomic lock of every source/domain record; later
application still needs same-transaction locks and revalidation under its own
contract. Add local option-forwarding/snapshot-change regressions and retain the
isolated DEV concurrent-other-lesson/module/block/quiz gate before activation.

Existing source helpers otherwise remain unchanged. No new flag, provider,
schema, billing or release authority. Root owns shared signature and integration.
