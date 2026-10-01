# SPEECH-INTAKE mini-spec V1 — Draft

Identity: METHOD-WORKBENCH / SPEECH-INTAKE; template V2/document V1; no predecessor.
Owner/root: root; product owner: human owner; reviewer: to be assigned for ASR
packet. Approved by: **not yet approved for runtime/resource/data processing**.
Decision date 2026-10-01. Change control: benchmark proposal → data/capacity/cost
review → exact owner decision if required → freeze complete mini-spec/addendum.

## Responsibility / non-responsibilities [Core]

Bounded authorized recording → editable transcript with uncertainty/failure.
No interpretation, course generation, tools, publication, assignment or consent
decisions. Contributes voice input only; text fallback remains always available.

## Interface / inputs / outputs [Core — provisional]

`transcribe(recording, server_context) → transcript | failure`. Provisional bound
60 seconds/8 MiB; actual MIME/decode/timeouts/concurrency/latency values need
benchmark acceptance. Output retains original language, supports manual edits,
never claims critical names/dates are correct simply from ASR confidence. Final
API/storage/queue shape pending measured capacity, not ready for implementation.

## Data ownership / privacy [Core — unresolved gate]

No tables/storage/providers added now. Candidate: existing approved local/KZ
capacity, faster-whisper. No audio retention by default. If queued temporary
storage needed, exact TTL/deletion/retry/encryption/tenant/RLS contract must be
accepted first. No external fallback/audio upload without exact data and cost
approval. Never log audio/transcripts/PII. Audio corpus requires usage permission.

## Invariants / state machine / errors [Core]

received → bounded validation → queued/running → transcript / failed / cancelled.
Silence, corrupt recording, unsupported format, timeout, resource exhaustion or
model failure cannot create business commands. Show failure and text fallback.
Retry must be bounded; cancelled/finished jobs cannot execute business actions.

## Dependencies, idempotency, impact, observability [Extended — pending]

Benchmark isolated faster-whisper multilingual candidates on approved capacity;
no production dependency install. Cache weights/version only after selection.
Concurrency/retry/job ownership/resource accounting/exact metadata retention are
pending benchmark, keeping status Draft. Forbidden credentials, domain mutations,
main API-process blocking and automatic cloud fallback. Existing-module impact:
None now; future API/worker/storage seams need impact addendum. Metrics duration,
latency, error counts and resource usage, no payloads.

## Verification / implementation packet [Core]

Read scope: approved corpus + isolated tool contour + this plan. Write scope:
none until exact benchmark packet accepted. Required corpus and quality/resource
gates: [execution plan](../../../../plans/2026-10-01_ai-driven-methodologist.md).
Unknown ownership/data route/resource cost → stop. DB/neighbor/integration checks
required when runtime is added; currently NOT VERIFIED. Handoff English five
fields with model/version/hardware/corpus and per-language/critical-slot results.

## Rollout / Ready / Done [Extended / Core]

Feature flag off; no background model/resource acquisition in this stage. Text
path must remain independent. Ready requires measured quality, concrete capacity,
limits/retention/data permissions, complete API/job ownership mini-spec and owners.
Done requires real RU/KK/mixed benchmark, queue/retry/tenant/cancellation tests,
manual correction UX and authorized DEV/production readback. None claimed now.
