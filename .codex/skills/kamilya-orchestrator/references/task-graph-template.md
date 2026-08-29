# Kamilya epic task-graph template

Copy this template to `docs/plans/YYYY-MM-DD_<slug>.md` only for an epic that
meets the activation criteria in `AGENTS.md`. Remove unused fields rather than
filling the plan with placeholders.

```markdown
# <Epic title>

## Scope and truth

- Owner: <root or explicit owner>
- Repositories and exact commits: <repo=commit; dirty state>
- Environments/providers: <only those in scope>
- Last updated: <ISO date/time and timezone>
- Exclusions: <explicit non-goals>

| Claim area | Canonical source | Freshness / limitation |
|---|---|---|
| Product | `PROJECT.md` | ... |
| Current system | `docs/PROJECT-CONTEXT.md` | ... |
| Production | `docs/PRODUCTION_READINESS.md` | ... |
| Open work | `docs/PRODUCT_BACKLOG.md` | ... |

## Ownership

| Scope or operation | Owner | Writer | Reviewer | Overlap rule |
|---|---|---|---|---|
| ... | ... | ... | ... | no overlapping writer |

## Dependency graph

`NODE-A -> NODE-B -> NODE-C`

Use multiple lines for independent branches. Do not invent dependencies merely
to make the graph look connected.

## Nodes

### <STABLE-NODE-ID> — <Outcome>

- Status: `NOT_STARTED | READY | IN_PROGRESS | IN_REVIEW | BLOCKED | DONE | CANCELLED`
- Scope: <repository/module/provider>
- Owner: <one owner>
- Writer: <one writer or none>
- Write/mutation scope: <exact paths or external objects>
- Dependencies: <node IDs or none>
- Exit gate: <observable checks>
- Evidence:
  - `GIT-DERIVED`: <pointer or NOT VERIFIED>
  - `RUNTIME-DERIVED`: <pointer or NOT VERIFIED>
  - `PROVIDER-CONFIRMED`: <pointer or NOT APPLICABLE>
- Approval gate: <exact mutation approval or NOT REQUIRED>
- Blocker / next action: <named condition and owner>
- Cleanup / rollback: <exact reversible action or NOT APPLICABLE>

## Decisions and approvals

| ID | Decision or exact approved mutation | Evidence | Owner | State |
|---|---|---|---|---|
| ... | ... | `OWNER-CONFIRMED` ... | ... | OPEN / USED / SUPERSEDED |

## Completion gate

- [ ] Required nodes satisfy their exit gates.
- [ ] `BLOCKED` nodes have an accepted external condition and next owner.
- [ ] No overlapping writer or unreviewed external mutation remains.
- [ ] Cleanup and residual-state audit pass.
- [ ] Durable facts moved to canonical documentation.
- [ ] Temporary task graph removed after transfer.
```

Keep evidence compact. Link paths, commits, commands with summarized results,
runtime IDs, and provider execution IDs; do not paste raw logs or secrets.
