# METHOD-WORKBENCH critical journeys V1

Status: accepted acceptance targets, not execution evidence; 2026-10-01.
Owner/root owns integration; Test & Evidence Runner executes exact later packet.

| ID | Journey | Required terminal evidence |
|---|---|---|
| CJ-01 | Attach owned source, request course draft | Exact source version, bounded AI quota/job, editable draft; no publish/enrollment |
| CJ-02 | Ask voice/text correction; review before/after | Source-grounded bounded patch, stale check, unchanged neighbors; published course needs new draft |
| CJ-03 | Human expert review → publish | No review bypass, exact content release, preview existing rule effects before confirmation |
| CJ-04 | Assign existing course to existing department once | UUID-resolved/frozen current members, timezone/deadline, actual eligible enrollments, outbox status; no DepartmentCourse rule |
| CJ-05 | Double-click/retry; course/membership changes during preview | One committed receipt; stale blocks before write; no duplicate generation/assignment |
| CJ-06 | Forged tenant/actor; active admin/student; foreign source/course/department | Denied, no foreign reads/mutations; no role capability union; DB RLS negative proof |
| CJ-07 | RU/KK/mixed voice with date/name/negation; silence/noise/timeout | Editable transcript, exact critical fields visible/clarified, uncertain input never executes |
| CJ-08 | Draft success, publish/assignment/notification failure | Completed stage persists; truthful per-stage receipts; retry only failed uncommitted operation, no whole-chain replay |

Foundation evidence covers strict payload and pure confirmation subsets of CJ-05
and CJ-06 only. It is NOT proof of database/LLM/audio/browser journeys. Tests for
source prompt injection, relative dates, duplicate names, unsupported permanent
rules and malformed tool arguments must be added to the next resolver/intent seam.

Release acceptance requires all journeys in isolated canonical Supabase DEV,
real approved speech/model calls, mobile/session/reload, then exact authorized
production candidate readback and synthetic live flow. Customer data untouched.
