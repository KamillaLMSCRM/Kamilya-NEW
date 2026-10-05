# WB-LESSON-CORRECTION-APPLICATION-DEV V1.1

Accepted root-owned allowlist correction before driver implementation, 2026-10-05.
Source inventory confirms the release owner is courses/release_models.py and
the single table is content_releases, not the two planned names in V1. Replace
course_content_releases/course_content_release_items in V1's clone allowlist
with content_releases only. No release rows are copied from public. All other
scope, failure, isolation and release gates remain unchanged.
