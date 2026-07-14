# First-Tenant Production E2E Report

**Date:** 2026-07-14  
**Environment:** production API, Supabase Postgres, Render, VPS worker/Valkey  
**Result:** passed

## Flow verified

1. Created an isolated temporary trial tenant with administrator, methodologist, and learner accounts.
2. Logged in as tenant administrator and loaded trial usage.
3. Logged in as methodologist.
4. Created a course, module, lesson, and quiz with a correct answer.
5. Published the course.
6. Assigned the course to the learner.
7. Logged in as learner and loaded the student dashboard.
8. Marked the lesson complete.
9. Submitted the quiz and received a passing result.
10. Completed the course.
11. Confirmed certificate issuance and public certificate verification.
12. Loaded the administrator training log and confirmed one completed record.

## Observed result

- Course assignment returned one enrollment.
- Quiz result: `passed=true`.
- Course completion returned a certificate number.
- Learner certificate list contained one certificate.
- Public verification returned `valid=true`.
- Training log returned one completed row.

## Cleanup

The temporary tenant and its associated test data were deleted through the protected superadmin deletion service immediately after the run. No credentials or secret values were recorded.

## Scope note

This run verifies the native course flow. SCORM import/launch/commit and kiosk privacy remain separate E2E scenarios.

