---
name: graphify
description: Navigate non-trivial Kamilya code dependencies and impact with the local Graphify index. Use for cross-module flow or blast-radius analysis, not exact-file edits, text search, runtime verification, or permission decisions.
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

If the CLI fails or the index must be created/updated, read
[local operations](references/local-operations.md). If the graph remains
unavailable or stale, continue with narrowly scoped source inspection and report
the navigation gap; required tests and runtime verification still apply.

The reviewed ASUS semantic documentation sidecar is a separate opt-in workflow.
Read [ASUS semantic sidecar](references/asus-semantic-sidecar.md) only when the
task explicitly concerns that engineering-document index.

## Advanced workflows

Only when explicitly needed, read the relevant reference completely:
- [exports](references/exports.md): opt-in wiki/call-flow/visual exports;
- [extraction specification](references/extraction-spec.md): expanding reviewed
  semantic coverage;
- [upstream workflow archive](references/upstream-workflows.md): other upstream
  operations. It is reference material, not automatically active project policy.

Upstream examples may target a different executable version or conflict with
local permissions. Verify the installed `--version`, `--help` and source before
adopting one; this project entrypoint governs operational choices.
