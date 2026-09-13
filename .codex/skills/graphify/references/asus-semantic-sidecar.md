# ASUS semantic sidecar

Use this reference only for the owner-approved Kamilya engineering-document
semantic index. It does not apply to normal AST code navigation.

Read `docs/SEMANTIC_ENGINEERING_INDEX.md` before changing or running the corpus.
Corpus preparation is local and separate from inference; authorize an exact
reviewed digest. The corpus runner uses bounded cached chunks and records
sanitized-prose coverage, exclusions and quote provenance under
`graphify-out/docs-semantic/`. Coverage is not proof of exhaustive extraction or
unused code.

Current owner-approved endpoint: `http://10.66.66.28:8000/v1`; model
`LibertAIDAI/GLM-5.3-Flash-NVFP4`. Verify endpoint and model identity for the
current request. Use the pinned Python from `local-operations.md`:

- `scripts/ops/graphify_asus.py --probe` — one synthetic compatibility request;
- `scripts/ops/graphify_asus.py` — only the allowlisted, hash-reviewed sections
  of ADR-0008 and ADR-0012.

Changed documents require root review before allowlist changes. The adapter has
no external SDK install, `.env`, secret, proxy, redirect, retry, or provider
fallback. It makes one bounded request with at most 6 nodes/6 edges, a 2048-token
output cap and a 90-second socket timeout. Cache identity includes content,
prompt, model, output settings and Graphify version.

Outputs are `graphify-out/asus/graph.json` and `evidence.json`. Query example:

```powershell
graphify query "active role" --graph graphify-out/asus/graph.json --budget 700
```

This remains a limited document graph. Verify claims against the source ADR and
never promote it to runtime truth or upload arbitrary documents/media.
