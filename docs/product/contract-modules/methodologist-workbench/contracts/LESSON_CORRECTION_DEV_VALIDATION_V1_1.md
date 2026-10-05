# WB-LESSON-CORRECTION-DEV-VALIDATION V1.1

Accepted compatible neighbor repair impact, root/module owner, 2026-10-05.
Preserves V1. Failed runtime A/B receipts remain immutable. B proved model column
presence but SQLSTATE42804 at ORM block insertion. Canonical read-only DEV probe
proved public0175/content_blocks.metadata=jsonb, matching migration0002; model
incorrectly uses Text. Do not replace the fixture with raw SQL to hide this.

Extend exact root write scope to `apps/api/app/modules/lessons/models.py`,
`apps/api/app/modules/lessons/schemas.py` and focused
`apps/api/tests/unit/test_content_block_metadata_contract.py`.
Use PostgreSQL JSONB(none_as_null=True) for the existing metadata column. Existing
API create/update remains optional string, serialized as a JSON string scalar;
None remains SQL NULL. No schema migration, data rewrite, new metadata API type,
business capability, RLS or provider change.

Response reads `metadata_`, not declarative Base.metadata. Keep serialized public
field `metadata` and optional string wire shape. Existing historical JSON objects/
arrays/scalars normalize to deterministic JSON text for the response; strings
remain exact, None remains None. Ordinary dict-shaped response input with public
metadata key remains supported. No change to draft status/review invalidation,
course release shape, source-actuality copying or publication authority.

Require RED before repair: bind type/NULL/string encoding, response ORM alias and
legacy JSON normalization. GREEN must also include real isolated ORM insert/read
of null, string and object metadata and matching response serialization. Existing
course snapshot freshness and quiz-review/source-actuality neighbors regressions
remain mandatory. Root owns acceptance; independent agent reviews source only.
No public/production mutation or activation authority is added.
