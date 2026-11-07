# Source preparation with document parts and illustrations V1

Status frozen for implementation on 2026-11-07. Owner approval is the current
request to implement both features, verify the two supplied files in DEV and
release after successful acceptance. Product owner is the Kamilya owner. Root
owns the shared contract, backend integration and release. Terra workers own
bounded implementation paths and independent review of paths they did not write.

## Observable result

A methodologist uploads any supported document, sees its server-derived content
parts and illustrations, can change the selected teaching material, reviews real
uncertainties and approves an immutable edition. Generation and learner figures
use the exact approved material. The original file stays available and unchanged.
The order/instruction and cash-instruction fixtures are examples of this shared
mechanism. Administrative dates and HR order administration are outside this scope.

## Module map and ownership

`original blob -> native blocks/assets -> cached visual reading -> part plan ->
selected recognized source -> editorial review/approval -> pinned generation ->
lesson images -> authorized learner`

- Native extraction owns ordered text, heading, table, image and page blocks,
  original image bytes, dimensions and source locators. It performs no inference,
  storage, database or network operations. Initial native adapters cover DOCX
  and PDF, with the ordinary converter providing text for other supported types.
  Unsupported visual content must be explicit, never represented as no images.
- Preparation owns the full recognized block manifest, image readings and the
  semantic part plan. One visual reading per original image hash is reused.
  Whole-page scans become recognized page content, not automatic lesson figures.
- Existing source review owns event history, optimistic revisions, command IDs,
  human decisions and immutable approvals. No parallel approval table is added.
- Existing course persistence owns image content blocks bound to approved source
  assets. Existing release snapshots preserve their metadata and membership.
- Source asset delivery owns tenant/role/enrollment/release membership checks.
  Existing file storage holds content-addressed image bytes. Historical course
  releases retain their referenced source documents until normal deletion permits
  cleanup. Existing document cleanup also removes task-owned derived blobs.

## Native extraction interface

`extract_native_source(blob, filename, document_sha256, *, max_image_bytes,
max_image_pixels) -> NativeSource | None`.

`NativeAsset` has asset_id, sha256, mime_type, data bytes, width, height and locator.
`NativeBlock` has block_id, kind, text, asset_ids tuple, page optional and locator.
`NativeSource` has blocks tuple, assets tuple, page_count optional and warnings
tuple. IDs are deterministic from original identity, source location and bytes.
Locators are server-derived JSON with package member/relationship or PDF page.
None delegates text conversion. Raster image verification is required. No external
OOXML relationships or arbitrary filesystem paths may be followed.

## Versioned prepared source contract

Prepared source v1 binds original blob SHA, parser policy, full recognized-text
SHA, ordered blocks, image manifests and a complete ordered partition into parts.
Each part identifies server block endpoints, title, role learning/supporting/
administrative and a selection recommendation with reason. Model-returned ranges
must resolve to known blocks without omissions, overlaps or duplicate coverage.
Selected part IDs compile deterministic text and an original-location map.
Image transcripts and descriptions remain distinguishable from source prose.
Filled examples never establish universal amounts, names or document numbers.

Public image manifests contain ID, content hash, type, dimensions, caption,
location and recognition status. Storage keys and binary data are server-owned.
Image interpretation and part planning use existing enabled DeepSeek/Luna routes.
The local content-dependent DeepSeek image control passed both image orders.
No model routing, provider plan or new infrastructure resource is authorized here.
Operational tunables use the existing runtime_settings catalog and history.

## State and consistency

`not_started/failed -> queued -> running -> in_review -> approved` remains the
normal flow. Preparation and visual checkpoints use existing analysis_block
events. A changed selection queues analysis with the prepared-manifest identity
and selected server IDs. It invalidates current decisions only after the new
analysis succeeds, while old approved snapshots stay immutable and readable.
Every checkpoint/write verifies original identity and active claim. Unknown paid
call outcomes stay explicit. Completed cached image readings are reused after a
failure. A stale revision or changed original returns a conflict.

Approvals bind selection and image manifests together with text/edit hashes.
Old whole-document and page-range approvals keep their original payloads and
digests. Fix the existing selected-pages readback mismatch as a compatibility
regression. Generation uses the pinned approved text and assets, not a fresh
conversion. Image markers are server-bound before lesson persistence.

## Critical acceptance

- Scanned nine-page PDF identifies the order on pages1-2 and instruction on3-9,
  preserving useful page9 provisions while excluding signature/register forms
  from the default teaching selection. Original bytes remain identical.
- Cash DOCX retains all ten image placements and meaningful relationships among
  1C controls, PKO/RKO examples and the cash-book illustration. Model output and
  source-visible figures are independently reviewed against the originals.
- Changing selection changes the next analysis/generation source. Unknown IDs,
  stale commands, concurrent changes, duplicate commands and original replacement
  cannot silently reuse approvals or paid stages from another source.
- An assigned learner sees only images present in their authorized course release.
  Cross-tenant, unassigned, revoked and foreign-image requests return404. Edits to
  live lessons do not change old release membership or purge its images.
- Local synthetic tests precede actual DEV ordinary-worker runs on both files.
  Verify source review, source approval, generation, lesson/test quality, displayed
  figures, stored sources, interruption/recovery and exposed token/time usage.
  Release the exact accepted candidate through normal protected procedures,
  then run a bounded synthetic production source-to-course/image journey.

## Impact and evidence

Extends source_editorial_review, direct_source, ai persistence, course image
delivery, document retention and the common lesson renderer. Existing legacy
approvals, source pins, text-only lessons, quizzes, tenant isolation, course
approval and frozen learner history remain covered by neighboring regressions.
Current CodeGraph and Graphify were rebuilt with zero inference and passing
exclusions. Source confirms read_approval -> resolve_pins -> pipeline persistence.
Graph method-name collisions are static candidates and need source verification.
