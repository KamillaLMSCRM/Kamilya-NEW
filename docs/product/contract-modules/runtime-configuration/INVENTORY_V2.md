# Runtime inventory V2

Accepted root2026-10-16. Supersedes INVENTORY_V1.md for initial catalog count and
document-answer control interpretation; retains V1 category exclusions and704file/
800heuristic source-scan evidence. Active catalog31keys, not29.

All29 V1 controls remain. Two additional controls own the existing managed
DeepSeek `evidence_low` request profile: `evidence_low.deepseek_seconds` and
`evidence_low.max_tokens`. Defaults45s/8192 preserve current behavior. Normal
`document_answer.provider_seconds`/`max_tokens` govern fallbacks and BYOK; managed
DeepSeek deliberately uses these separate profile fields. Profile + one fallback
+5s must fit the content answer total. Impact/tests: IMPACT_EVIDENCE_PROFILE_V1.md.
Credentials/endpoints/order remain separate; no model availability claim.
