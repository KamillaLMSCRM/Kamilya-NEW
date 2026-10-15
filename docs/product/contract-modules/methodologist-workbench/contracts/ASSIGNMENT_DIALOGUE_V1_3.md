# Assignment dialogue effective context V1.3

Status: Accepted for bounded repair, 2026-10-15.
Supersedes: ASSIGNMENT_DIALOGUE_V1_2.md for effective-context enforcement;
all V1/V1.1/V1.2 ownership, safety, scope and release obligations remain active.
Approved by Root under current owner DEV and production/live request.

R2 independent review confirmed that client-only history normalization left
public API callers able to mix stale drafts with an owned ready plan. The server
must use empty effective instruction history whenever previous_plan_id is supplied;
then validate/load that owned plan before provider work. The pure prompt builder
also enforces previous-candidate exclusivity. No user-supplied authority is added.

Relative wording in effective historical user instructions remains unresolved
unless current instruction supplies a recognizable full absolute date with year.
Current relative wording remains rejected as before. Exact calendar/time/future
candidate validation and authoritative preview/confirmation remain unchanged.
This bounded check does not claim universal date-language or semantic coverage.

Recognized negated-old-newcomer -> affirmative whole-department corrections in
RU/EN/KK may resolve a previous denied subgroup; any additional current restriction
outside that negated span still clarifies. A negated whole-department instruction
never clears the restriction. UI describes same-dialogue correction accurately.
No semantic repair call, hidden retry, enrollment ownership or provider change.

Required new regressions: owned previous plan plus denied stale history yields
only sanitized prior candidate; unrelated follow-up cannot convert old relative
deadline to guessed ISO via an adversarial provider; affirmative whole-department
recovery vs negated whole department/current extra filters; all previous guards.
Root owns critical-path integration. R3 review is bounded to repaired contracts,
source hashes and named regressions, not an unlimited language-feature expansion.
