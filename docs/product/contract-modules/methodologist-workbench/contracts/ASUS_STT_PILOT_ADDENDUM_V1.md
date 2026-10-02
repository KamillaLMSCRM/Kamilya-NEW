# ASUS-STT-PILOT addendum V1

Status: Accepted for isolated benchmark only. Version: V1; no predecessor.
Owner/module owner: root. Product owner: human owner. Independent reviewer:
`voice_pilot_contract_review`. Decision date: 2026-10-03.
Authority: owner named the ASUS access handoff and requested implementation plan
and tests; owner explicitly authorized obtaining public human recordings online.
Root accepts this limited benchmark packet, not production speech processing.

## Objective, boundary and interface

Measure multilingual recognition quality and resource use before choosing a
product ASR adapter. Existing SPEECH-INTAKE V1 remains Draft for LMS integration.
The pilot is standalone: `prepare → immutable input manifest → benchmark → report`.
It does not call LMS endpoints, interpret commands, execute assignments, accept
customer audio, change quotas, or expose an HTTP service.

Read scope: public MIT model artifacts, CC-BY-4.0 Google FLEURS test metadata and
licensed recordings; named ASUS access handoff; host resource/tool inventory.
Write scope: `scripts/dev/stt_pilot.py`, its focused tests/requirements, canonical
plan/index/error records, and only newly created task directory
`/home/superuser/projects/kamilya-stt-pilot-20261003` on ASUS. Root owns all writes.
No OS packages, sudo, drivers, existing project virtualenvs, services/timers,
network configuration, production, databases, provider or billing mutations.

The verified local alias uses the owner handoff's SSH configuration with strict
host checking; it is not the VM126 executor or the old WireGuard access path.
No credentials or token values are copied into source/evidence. Public downloads
use no HF token and inference runs offline; no audio leaves ASUS for an ASR API.

## Data, dependencies and errors

Input: first five distinct test sentences per RU/KK lasting 15–30 seconds,
selected by metadata before inference, with exact reference text and audio SHA256.
Optional derived RU+KK splice is marked artificial, never natural code switching.
Model/dataset repository revisions, licenses and local weights hash are recorded.
Archive download bound 700 MiB per language; selected audio bound 8 MiB per file;
only selected bytes are read, never arbitrary archive paths extracted to disk.
Public metadata requests timeout after 45 seconds; each remote run has an outer
bounded timeout. Failure aborts the benchmark; no hidden model/provider fallback.

CPU baseline: small/int8, 4 threads, one worker/concurrent request. Comparator:
multilingual large-v3/int8, same input clips and decode settings. CUDA is accepted
only after actual model execution, not GPU inventory or package installation.
Pinned independent runtime requirements do not enter application dependencies.
Initial pip operations used the ordinary user download cache, not global package
installation; no shared-cache purge is authorized. Subsequent installs must set
PIP_CACHE_DIR inside the task root. Existing project packages/venvs are unchanged.

Report: per-language weighted word error rate, clip duration/latency/RTF,
model-load/first-clip latency and process peak RSS; transcripts are public-corpus
benchmark artifacts, not production logs. RSS does not prove GPU memory usage.
Five samples per language are a smoke baseline, not a stable p95 or product-quality
claim. Dates, course/department names, negations and natural mixed speech require
a separate domain corpus; no confidence score proves those fields are correct.

Public licensed inputs/model cache and reports remain in the task-owned directory
for reproducibility. This does not authorize retaining private customer recordings.
LMS raw-audio retention/temporary queue TTL remain unresolved integration gates.
No business state or idempotency is involved. Benchmark comparison is sequential
to avoid shared model/corpus writes or contaminating resource measurements.

## Ready, Done, impact and rollback

Ready: current SSH identity/resources verified; permitted public artifacts;
isolated directory; fixed selection/metrics/runtime; bounded execution.
Done for pilot: actual reports, focused unit tests, independent source review,
host negative-space comparison, canonical plan with failures and next decision.
This is not Done for SPEECH-INTAKE or CJ-07. New API/job/storage/session seams
require a separate versioned impact contract and DEV isolation/acceptance.

Existing-module impact: None for learner chat, editor preview/apply, workbench
plans/receipts, authentication/RBAC/RLS, workers, migrations and public UI.
Negative-space checks: no new listening service; protected ASUS timers unchanged;
pre-existing unrelated book-service failure is recorded, not repaired or hidden.
Rollback: stop bounded pilot processes; leave existing services and LMS intact.
No broad cache cleanup, deleted old project, driver replacement or paid API retry.
Unknown artifact license/cost, host identity mismatch, insufficient capacity or
required write outside the owned directory stops the affected action at root.
