# ASUS-STT-PILOT addendum V2

Status: Accepted for isolated decoder-policy comparison only. Version: V2.
Predecessor: [V1](ASUS_STT_PILOT_ADDENDUM_V1.md); its data, access, resource,
retention, negative-space and rollback boundaries remain unchanged.
Owner/module owner: root. Product owner: human owner. Date: 2026-10-03.
Authority: owner requested continuation of the approved RU/KK quality pilot.
Independent source reviewer: `stt_decoder_policy_review`; root accepts runtime
evidence separately. This is not approval of LMS speech processing or deployment.

## Bounded delta

Only standalone `scripts/dev/stt_quality.py` and its focused tests are added.
Reuse the installed MIT large-v3 weights, pinned runtime and immutable eleven
CC-BY-4.0 FLEURS inputs. No download, dependency installation or GPU change.
Compare sequential CPU/int8/four-thread/one-worker profiles: known-language
baseline versus automatic multilingual detection with 15- or 30-second chunks.
Every profile uses transcription, beam5, no previous-text reuse and no VAD.
Reference words cannot enter inference or initial prompts. No provider fallback.
Each process has a 600-second deadline; earlier raw reports cannot be overwritten.

Reports bind runtime versions, model/source/input hashes, per-row policy,
references/durations, edit distance and timing. Schema2 keeps RU/KK in `languages`
and the derived clip under `artificial_splice`, explicitly diagnostic-only and
`acceptance_eligible=false`. The preserved first 15-second report uses schema1;
its separate audit receipt normalizes the metric groups without modifying the raw
file. False `natural_mixed_verified` and `command_fields_verified` flags are
mandatory. This audit is reproducibility/self-consistency evidence, not an
external attestation or rerun of inference.

## Acceptance and next boundary

Done for this delta: real sequential reports and independent hashes/row sums;
source review and network-free regression tests; host postcheck; canonical plan
records both rejected and retained profiles. No inference service remains.
Measured five clips per language and one artificial splice cannot establish
natural code-switching, domain-field accuracy, p95 or product readiness.
The 15-second profile is rejected. The 30-second profile is an exploratory
candidate, not a selected production adapter; it did not improve KK-only WER.

A recording phrase kit may reference the existing synthetic DEV QA fixture.
Identity and names are checked using its canonical read-only procedure: exact
DEV health/actor/tenant/course IDs and ordinary auth plus GET requests only.
No business records, department creation, assignments, progress or passwords
may change. A missing department means negative test only, not automatic setup.
The kit does not authorize sending private audio to an external provider or
executing the spoken commands. Recording custody/TTL needs a separate intake
decision before private/customer audio is processed.

A researched KK-adapted model is not part of this accepted installation delta.
Before testing it, record immutable revision/license, evaluation contamination
limits, conversion/runtime dependencies, download/disk/time bounds and isolated
rollback. No new OS package, shared environment, service, driver or billable
resource is authorized as an implicit next step. Natural domain recordings and
VM126 resource evidence remain prerequisites to any LMS voice release.
