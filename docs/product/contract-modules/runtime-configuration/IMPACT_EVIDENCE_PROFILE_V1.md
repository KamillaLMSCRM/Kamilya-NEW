# Evidence profile hot controls V1

Accepted root2026-10-16, same DEV-only owner scope. Final source review discovered
document answers use `request_profile=evidence_low`, which overrides ordinary
max_tokens/provider_deadline for managed DeepSeek with8192/45. Expose the actual
profile controls rather than claim fallback knobs govern managed DeepSeek.

Add `evidence_low.deepseek_seconds` default45/range5..60 and
`evidence_low.max_tokens` default8192/range4096..8192. Existing thinking-low profile,
schemas, fallback/BYOK normal caps remain. Validate profile + one fallback +5s <=
document answer total. Active inventory INVENTORY_V2.md, initial catalog31keys.
Public0182 not yet applied: include frozen SQL/parity constraints before release.
Existing45/8192 profile regressions must remain unchanged, add changed-value
transport proof, rerun isolated SQL on final migration. No new inference on save,
embedding/route/auth/billing/ASUS or production changes.
