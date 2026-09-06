# Engineering semantic index

Scope: Kamilya-NEW engineering Markdown and project instructions, as requested on
2026-09-05. Landing and application-code semantics are separate future scopes.
Graph evidence is navigation, never runtime truth or deletion authority.

## Reproducible operation

Use the pinned Graphify Python from `.codex/skills/graphify/SKILL.md` and run from
the repository root. Existing owner-approved ASUS transport is documented in
`PROJECT-CONTEXT.md`; no SDK, billing change or server configuration is required.

1. `scripts/ops/graphify_docs_corpus.py` performs local inventory only. It writes
   `graphify-out/docs-corpus.json` and prints its SHA-256 and coverage counts.
2. Review document selection, omissions and sanitized content before authorizing
   that exact digest. The script does not grant approval to itself.
3. Run `& 'C:/Users/user/AppData/Local/pipx/pipx/venvs/graphifyy/Scripts/python.exe'
   -m scripts.ops.graphify_docs_index --approved-sha256 <reviewed-digest>
   --max-requests <remaining-chunk-count> --workers 2`. Start with one request for
   a changed transport/prompt. Maximum two in flight; no automatic retry/fallback.
4. Inspect `graphify-out/docs-semantic/evidence.json`. Partial output is not
   complete coverage. Failed generation must be diagnosed before resuming.
5. Query `graphify query "known concept" --graph
   graphify-out/docs-semantic/graph.json --budget 700`, then verify the linked
   quote and source lines. Cache hits make no inference request.

Full coverage means all eligible sanitized prose chunks in a reviewed snapshot
were processed, not every possible fact extracted. Fenced code, sensitive lines,
URLs, customer/legal/marketing documents, historical plans/evidence and upstream
reference archives are excluded. The manifest records omissions. Up to four
concepts per chunk keep processing bounded; zero-concept chunks remain visible.
The sanitizer is defense in depth, not a replacement for corpus review.

Graph nodes retain document and source spans. Quoted text is checked against the
sanitized source; concept interpretation still needs human/source review. Shared
normalized labels create INFERRED navigation links, not proof of equivalent
behavior or duplicate responsibilities. No absent edge proves unused code.

Derived manifests, cache, graph and run evidence stay ignored in `graphify-out/`.
Never overwrite the main AST graph. Changed sources invalidate approval; unchanged
sanitized chunks reuse their content/prompt/model/version cache. No scheduler or
automatic model calls are installed.

## Canonical ownership after reconciliation

Keep one operative source per responsibility; graph similarity alone does not
justify deletion. These ownership rules concern documentation, not live runtime.

| Responsibility | Canonical source | Duplication boundary |
|---|---|---|
| Onboarding navigation | [CODEX_HANDOFF.md](CODEX_HANDOFF.md) | Link to environment/release evidence; do not copy mutable release SHA, migration revision or PASS snapshots |
| Production/dev topology | [Environment map](PROJECT-CONTEXT.md#карта-окружений-и-доступов) | VPS guide uses this map; a dev frontend name does not prove isolated backend/data |
| Release acceptance | [Root gate](../AGENTS.md#production) and target-specific runbook | Preserve API/DB/worker exact identity and business smoke; Render evidence cannot close KZ production |
| Test & Evidence Runner | [test-runner contract](../.codex/agents/test-runner/AGENTS.md) | Alternate `test-evidence-runner` path is only a redirect for saved references; no second packet or implicit ledger-write permission |
| API documentation discovery | [Documentation index](DOCUMENTATION_INDEX.md) → environment map | No environment-free Live OpenAPI link that silently selects dev/legacy |

Do not classify accepted V1 EPIC/contracts as disposable merely because V2 exists:
the immutable-version rule in `product/contract-modules/README.md` requires their
preservation. Temporary plans require individual completion/consumer checks before
removal; semantic similarity alone is insufficient.
