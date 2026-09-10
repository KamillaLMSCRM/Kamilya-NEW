# MAP serialized admission budget — V7

Status: Accepted for bounded implementation by root,2026-09-10, under the owner's
full-source reliability repair request. Not release approval.
Supersedes: V3 map admission calculation only. All28000overview/32000planner,
provider/deadline/retry/source-preservation and tenant constraints remain unchanged.
Writer: root; independent reviewer: bounded worker; product owner: requester.
Change control: EPIC_V1; earlier accepted contracts remain immutable.

Evidence: normal043 job failed source_topic_map_overview_budget_exceeded before
course creation. A separate44call diagnostic on the same932chunks produced504topics
and27215overview characters in54.69seconds, demonstrating nondeterministic proximity
to the fixed limit, not proving the failed response's exact size. Static code permits
6000characters per batch without allocating the shared serialized overview budget.

Allocate the exact empty topics-only overview framing/document/source-range cost
first, then divide its remaining capacity across known batches. Validate each
serialized, boundary-escaped topic array against its allocation before accepting
or caching it. Tell the model the separate topic budget up front; summaries retain
their existing1600character limit and do not consume the topics-only allocation.
An over-budget batch uses the existing single full-source retry requesting shorter
topic names; never shorten/delete already accepted topics or source references.

Public interface and persistence unchanged. No larger model context, new inference
stage, higher call/concurrency/deadline limits, schema/provider/billing change.
If even framing plus minimum topic allocation cannot fit, fail before inference.
This ensures accepted maps fit mechanically, not semantic completeness of model prose.

Acceptance: synthetic overflowing JSON-escape responses rejected before acceptance;
bounded retry preserves all16short topic labels/all source IDs; long summaries still
allowed; cache revalidation and exact serialized final bound; full regression,
real whole-source candidate and normal queued production/browser/cleanup.
