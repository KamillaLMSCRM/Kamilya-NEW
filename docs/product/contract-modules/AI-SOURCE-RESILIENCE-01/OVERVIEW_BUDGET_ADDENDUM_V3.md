# Overview budget V3

Status: Accepted by Astra root, 2026-09-10, within source-resilience approval.
Supersedes: EPIC_V1 MAP overview limit of 24000 characters only.
MAP_ADDENDUM_V2 and other safety/authority clauses remain active.

Evidence: real validated cache contains 44 records, 501 topics, 23837 topic
characters (480 unique topics / 22967 chars), 23732 summary characters and all932
sources. Cache replay required zero provider calls. Therefore 24000 chars cannot
contain the topics plus their source/document references without losing information.

Decision: bound the overview at28000 characters. The EXISTING combined architect
prompt limit remains32000 and is checked before its provider call. Request count,
mapper request/output/deadline limits, source/tenant isolation and provider config
are unchanged. This is deterministic budget allocation, not reliance on model
character counting. If the complete topics-only view exceeds28000, or user guidance
pushes the full architect prompt over32000, retain explicit failure; never truncate.

Verification: exact real cached map must fit and architect validate three modules;
tests exercise hard overflow and complete expansion of source ranges. Large-source
full course/save/browser acceptance remains a distinct gate.
