---
name: graphify
description: Use Kamilya's local Graphify index first for code navigation, dependency paths and impact analysis; use the reviewed ASUS semantic sidecar for its approved engineering documents. Not a source of runtime truth or permission to scan/upload arbitrary files.
---

# Kamilya Graphify

## Choose the useful operation

- Code question: query the existing per-repository graph before broad source reads.
- Dependency or call flow: `path` / `explain`; blast radius: `affected`.
- Changed code: update the AST index once after the patch; no LLM needed.
- Engineering document relations: use the reviewed documentation index below,
  not an arbitrary repository upload. Plain text lookup still uses `rg`.
- Status-only or instruction editing does not require a graph rebuild.
- Never merge Kamilya LMS and landing implicitly, install hooks/watchers, change
  global config, or upgrade a shared package as a side effect.

## Verified workstation setup

CLI: `graphify`, package `graphifyy==0.9.23` in pipx.
Python: `C:/Users/user/AppData/Local/pipx/pipx/venvs/graphifyy/Scripts/python.exe`.
Run from the actual repository root; never from `C:/Kamilya New`.
Check version/import before relying on this machine-specific path after drift.

`graphify-out/.graphify_python` must be UTF-8 text containing that interpreter
path, not bytes copied from a Windows executable. `.graphify_root` must name
the actual repository. Do not interpret executable bytes as a shebang.

## Navigate and verify

1. Check graph presence, metadata and relevant source freshness. Use
   `graphify diagnose multigraph --json --max-examples 1` when validating index
   integrity, not for every query. A clean post-build graph does not prove the
   extractor retained every original edge.
2. Match the question to actual node labels; translate user terminology into
   indexed symbols. Select a few relevant labels, not the entire vocabulary.
3. Run bounded queries, normally 500-1500 tokens:
   - `graphify query "known_symbol" --budget 1000`
   - `graphify explain "known_symbol"`
   - `graphify path "source_symbol" "target_symbol"`
   - `graphify affected "known_symbol" --depth 2`
4. Verify decisive paths/symbols against current source and tests. Preserve
   `EXTRACTED/INFERRED/AMBIGUOUS` labels. Graph evidence is `GRAPH-DERIVED`.
   An undirected connection cannot prove call direction; confirm it in source.
   No path or a truncated result does not prove no dependency.
5. Record only useful evidence pointers and index gaps in the existing task.
   Do not auto-save conversational answers as project truth or flood the owner
   with graph dumps, mandatory follow-up questions or community reports.

If the CLI fails, try the documented Python with `-m graphify`. If the graph is
unavailable/stale, report the gap and continue narrowly scoped source inspection;
this does not waive required tests, journey gates or runtime verification.

## Update without sending code to a model

`graphify update .` is AST-only in the pinned CLI. For a missing index:
`graphify extract . --code-only --max-workers 2`.
Before rebuilding, check exclusions, exact root, dirty files and existing index.
Keep the shrink guard; review removed source files before approving any force.
A successful exit alone is insufficient: check counts, source existence,
diagnostics, and a representative query/path against source. Index freshness is
not a requirement for a clean checkout; account for the actual working files.

Existing canonical index: `graphify-out/graph.json`. It is derived local data,
not a deliverable, deployed artifact or replacement for project documentation.

## ASUS semantic sidecar

For the owner-approved engineering documentation index, read
`docs/SEMANTIC_ENGINEERING_INDEX.md`. Corpus preparation is local and separate
from inference; authorize an exact reviewed digest. The corpus runner uses
bounded cached chunks and records full/partial sanitized-prose coverage,
exclusions and quote provenance in `graphify-out/docs-semantic/`.
Do not confuse completed chunk coverage with exhaustive fact extraction or
unused-code proof. The two-ADR pilot below remains a separate compatibility probe.

Current owner-approved endpoint: `http://10.66.66.28:8000/v1`, model
`LibertAIDAI/GLM-5.3-Flash-NVFP4`; verify identity per request.
Use the pinned Python above:
- `scripts/ops/graphify_asus.py --probe`: one synthetic compatibility request.
- `scripts/ops/graphify_asus.py`: only selected session-transport and role-ownership
  sections of hash-reviewed ADR-0008 and ADR-0012;
  changed documents require root review before updating the allowlist.

This adapter uses Graphify's extraction prompt, parser and directed graph builder.
No external SDK installation, .env, secret, proxy, redirect, retry or provider
fallback. One request, up to 6 nodes/6 edges, output cap 2048 tokens, socket timeout
90 seconds. This is a bounded navigation summary, not exhaustive ADR extraction.
Cache identity includes content, prompt, model, output settings and Graphify
version. Cache hits do not call the server. No paid resource is created.

Outputs: `graphify-out/asus/graph.json` and `evidence.json`.
Query using `graphify query "active role" --graph graphify-out/asus/graph.json --budget 700`.
This is a separate limited document graph, not full-repository semantic coverage.
Inspect extracted claims against the ADR before using them. Do not promote stale
ADR statements into current runtime claims. No arbitrary document/media upload.

## Advanced workflows

Only when explicitly needed, read the relevant reference completely:
- [exports](references/exports.md): opt-in wiki/call-flow/visual exports;
- [extraction specification](references/extraction-spec.md): expanding reviewed
  semantic coverage;
- [upstream workflow archive](references/upstream-workflows.md): other upstream
  operations. It is reference material, not automatically active project policy.

The archived skill was marked 0.9.27 while the executable is 0.9.23. Some upstream
examples conflict with the local CLI or permissions. Verify `--help` and source
before adopting one; this project entrypoint governs operational choices.
