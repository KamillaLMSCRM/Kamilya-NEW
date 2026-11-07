# Author identities and retained-response replay V1

Status: frozen local correction after actual DEV course job30861eb9 failed before
saving. Its owned quarantine contains a complete HTTP200 Luna6 reply:7lessons,
20questions,45,847bytes,111956ms,26365input/5896output tokens. The sole observed
structural defect is17 repeated question labels across different lessons. All
reported field, answer-index, choice and source-ref syntax checks otherwise pass;
this is not semantic course acceptance. Raw SHA
c24faa3715c8355982843e5eb4eaf149d2a7c065a935a9692afa46592c869040.

## Bounded behavior

- Model-local question labels may repeat across uniquely identified lessons.
  The server derives deterministic global IDs for those repeated labels from the
  parent lesson and original label. Already globally unique responses stay exact.
  Strict course validation remains unchanged after normalization. Same-lesson
  duplicates, ambiguous lesson IDs, identity/source collisions, invalid references,
  choices, answer indices, missing fields and blank content remain invalid.
- Normalize a copy, never the captured response. Text, images, order, answers,
  explanations and source references stay byte-for-byte equivalent. V31 uses the
  normalized strict result for subsequent editorial stages. Prompt/request/format
  bytes stay unchanged so the retained exact first author reply can be replayed.
- Ordinary resume may authorize only one retained, complete managed HTTP200
  structured-shape rejection for the initial practical V31 author. No source/job
  IDs or body hashes are hardcoded in runtime policy. Unknown/incomplete responses,
  unsupported stages and failed source/route/actor checks retain existing holds.
- Public retained_response_replay_available requires owned private-plan inspection;
  a pure job-result metadata candidate is not permission to invoke or finalize.
  Resume records a server-owned digest-bound authorization, retains the original
  pending marker/reservation, and still admits exactly one delivery under locks.
  This job is not counted twice against its own active-job limit.
- The practical-service producer serializes its output cap in the stored group:
  `practical:author:editorial:v31:output=<cap>`. Candidate and audit validation
  share the exact supported-group predicate; unsuffixed helper-only fixtures,
  review groups, malformed or unsupported caps are not the actual replay path.
  Test through the practical-service wrapper as well as checkpoint primitives.
- Worker inspection rechecks exact source, stage/group, original claim marker and
  result/claim keys. Replay consumes a freshly prepared deterministic capability
  and verifies actor/job/stage/route, exact wire-request hash, raw SHA/length,
  returned model and structured format. It performs no HTTP inference. A mismatch
  holds; it never falls through to a new POST.
- Only the existing finalization transaction can consume that original marker,
  save the validated response and usage once, and append a closed source-bound
  replay audit. Original rejected bytes/receipt remain unchanged and rejected;
  this is structural recovery, not semantic approval or publication.
- Fix future managed Luna6 capture metadata to pass its actual configured model.
  Old mislabeled receipts are not rewritten. Historical replay uses exact raw
  returned model plus route/wire proof, rather than fabricating an old metadata fix.
- UI offers an explicit continuation of the saved response only when the API
  capability is present. Unknown dispatch acknowledgements retain the same-job
  GET reconciliation fence; no automatic second resume POST or new generation.

## Ownership and gates

Terra asset_seams owns practical_contract/editorial_cycle identity adaptation and
tests. Terra parts_review_seams owns managed replay/capture, owned-stage inspection,
the additive finalization audit, API/resume/claim wiring and tests. Root owns this
contract, frontend capability/copy/interaction tests, integration and execution.
English-only agent communication; no provider/model/DB/Git mutations by workers.
Read-only Git calls inside canonical test wrappers are allowed and required.

First saved/synthetic shape/replay/negative/concurrency/usage gates without model
calls, then actual isolated DEV ownership/claim/finalization rollback verification.
Exact CI/image/DEV update precedes ordinary browser resume of the original job.
Its original author POST must not repeat. Continue remaining editorial stages,
then both requested full courses and protected image/learner acceptance. Production
is conditional on those results; no customer, provider-plan or role changes.
