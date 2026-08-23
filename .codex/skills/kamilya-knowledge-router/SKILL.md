---
name: kamilya-knowledge-router
description: Deterministically route a sanitized local Kamilya question over ephemeral cited records from canonical docs, Graphify, source/tests/migrations, Git evidence, and inert learning candidates. Use for bounded agent knowledge lookup; do not scan files, persist an index, activate candidates, or access network, databases, providers, secrets, PII, or production.
---

# Kamilya Knowledge Router

Use one deep local module to rank already-sanitized, explicitly cited records.
The router is not a crawler, indexer, source adapter, memory store, or authority.
Its canonical implementation path is this skill directory; no root-level wrapper
or runtime API copy is maintained.

## Safety contract

- Input is one exact JSON envelope on stdin. The caller supplies ephemeral
  records; the router never opens files, invokes Git, scans Graphify, calls a
  provider, accesses a database, or writes state.
- Projects are limited to `Kamilya-NEW` and `kamilya-landing`. Every record must
  match the request project and an allowlisted source-kind/path shape.
- Every result carries its source path, citation, source kind, and permitted
  evidence label. Citations use exact `path:line[:column]` syntax.
  `GRAPH-DERIVED` remains navigation evidence only.
- HERMES-like records must remain `CANDIDATE_ONLY`, carry no authority, and use
  `NOT VERIFIED`. Any active/promotion state is rejected.
- Query and record text containing secret-like or contact-like values is
  rejected. Do not supply tenant payloads, production records, credentials,
  contacts, or personal data.
- Output is transient stdout. No source or result is copied into another
  canonical store, and no local index is created.

## Input

See `examples/synthetic-request.json`. Required top-level fields are exactly:
`schema_version`, `project`, `query`, `limit`, and `records`.

Run:

```powershell
Get-Content -Raw .codex\skills\kamilya-knowledge-router\examples\synthetic-request.json |
  python .codex\skills\kamilya-knowledge-router\scripts\route_knowledge.py
```

No matching records produce no output and exit successfully. Invalid input exits
with code 2 and a bounded reason code on stderr.

## Interpretation

- `GIT-DERIVED` means the supplied citation points to source, tests, migrations,
  canonical documentation, or explicit Git commit evidence. The router does not
  independently prove checkout freshness or runtime state.
- `GRAPH-DERIVED` is architecture navigation only.
- `NOT VERIFIED` on a candidate means root review is still required. Frequency,
  lexical score, and ranking never grant authority.

Any persistence, skill/rule activation, filesystem adapter, scheduler, provider,
database, deployment, or production use is a separate reviewed change with its
own approval gate.
