# MAP V2: server-owned source associations

Status: Accepted by Astra root, 2026-09-10, within the approved source-resilience task.
Supersedes: MAP output-schema and association clauses of EPIC_V1.md only.
Other scope, owners, safety/performance bounds and release gates remain unchanged.

## Stop evidence and decision

The first detailed-map candidate failed the real 932-source input with
`source_topic_map_coverage_invalid` after 21 calls / 38.78 seconds. Seventeen
batches had succeeded. Making the model reproduce and partition mechanical IDs
remains an unnecessary failure point. Independent review also found no explicit
source-to-document mapping in the architect overview and missing chunk identities
in the checkpoint digest. Root accepts a protocol revision, not further prompt tuning.

## Replacement contract

- A deterministic input batch produces ONE aggregate record. Model output is
  exactly `{summary: string, topics: string[]}`; it does not generate source IDs.
- The mapper attaches the complete exact input batch's IDs itself, checks the
  complete map against the corpus, and never lets generated text assign provenance.
- One record may describe topics across its input batch; this is navigation, not
  a claim that every fact or chunk supports every topic. Writer still reads originals.
- Keep <=16 topics, <=160 chars/topic, <=1600 summary chars, <=8000 response chars,
  <=2048 output tokens, <=6000 aggregate chars, 64 batches, concurrency3, 90s deadline.
- One full-source retry for output formatting/length only. Output with old IDs or
  arbitrary extra fields is invalid schema, never interpreted as provenance.
- Document legend explicitly maps each document to its synthetic source-ID ranges.
  Detailed and topics-only representations preserve this association; no source or
  topic clipping. Range notation is documented and exact, not sampled.
- Checkpoint digest includes protocol version, prompt/output configuration and
  ordered `(source_id, chunk_id)` pairs; prompt already includes text, document IDs,
  revisions and headings. Store namespace binds tenant/job/resolved provider/options.
- Tests use the same public producer-consumer interface; replace obsolete fixtures
  expecting model-owned IDs, retaining tests that reject legacy/foreign-ID output,
  validate corpus-to-result exact coverage and prove cross-document associations.

Root owns mapper/test changes. Checkpoint adapter interface is unchanged.
Next gate: exact representative map probe, then full course acceptance; NOT VERIFIED.
