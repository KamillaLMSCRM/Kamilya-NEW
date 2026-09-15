# Direct source generation contract V1

Status: Accepted

The V2 engine consumes an already tenant-verified `DirectSourceCorpus`. It returns a complete projection for the existing `GenerationState`: course structure, lesson content, assessment and bounded `source_analysis` evidence.

Success requires `publishable=true`, full fact coverage, at least one lesson and at least one accepted assessment question where the source contains assessable facts. The consumer must not persist a completed course when provider realization fell back, validation remains failed, cancellation occurred or the result is not publishable.

Embeddings are an auxiliary ranking measurement. Their total failure must set degraded evidence and preserve all admitted facts. Content generation uses the existing tenant-aware async provider route; provider transport or contract exhaustion remains a retryable/interrupted job outcome.

The consumer maps into existing course/lesson/quiz schemas and existing transactional save. No endpoint, database table, review/publication rule, assignment behavior or learner-visible contract changes.
