# ADR-0013: Cohorts are reusable audiences

**Status:** accepted  
**Date:** 2026-07-27

## Context

The original cohort module stored members and course links, then materialized
enrollments through a separate apply action. This duplicated the course and
assignment surfaces, obscured where an enrollment came from, and let a change
inside a group unexpectedly affect learning delivery.

Kamilya LMS already has canonical delivery owners:

- a course creates a direct assignment;
- a learning program assigns an ordered set of courses;
- organization, department, and position rules create automatic assignments.

## Decision

A cohort stores only a named, tenant-scoped set of active learners.

- Membership is managed in `/cohorts`.
- Courses are not selected or applied from the cohort screen.
- A published learning program or another explicit assignment rule may use a
  cohort as its audience.
- New cohort course links and cohort apply operations are rejected.
- Existing `cohort_courses` data remains readable for expand compatibility but
  is not an active product contract.
- Historical enrollments with `source=cohort` remain immutable evidence and are
  shown as legacy rule-managed assignments.

## Consequences

- The user starts delivery from the course, program, or rule that owns it.
- Group membership can be reused without creating a second course catalog.
- Removing a learner from a cohort does not silently erase completed learning.
- Automatic assignments are not removed through the manual-assignment UI.
- Future migration may archive `cohort_courses` only after production data has
  been audited.
