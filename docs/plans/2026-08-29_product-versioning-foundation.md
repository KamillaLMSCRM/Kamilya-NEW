# Plan: Product Versioning Foundation

Date: 2026-08-29 · Scope: isolated worktree `_opencode-versioning` · Status: done

## Goal

Establish a deterministic product-versioning foundation: canonical `VERSION`,
Keep a Changelog workflow with `[Unreleased]`, release docs and note template,
AGENTS.md authority rules, and a deterministic check that `VERSION`,
`apps/api/pyproject.toml` and `apps/web/package.json` agree.

## Steps and gates

1. `VERSION` = `0.1.0` — matches both manifests (accepted initial 0.1.0; no
   manifest edit needed).
2. `CHANGELOG.md` — Keep a Changelog style, `[Unreleased]` with
   Added/Changed/Fixed/Security.
3. `docs/releases/README.md` — SemVer + release lifecycle; `docs/releases/RELEASE_NOTE_TEMPLATE.md`.
4. `AGENTS.md` — mandatory changelog rule + root-orchestrator-only release authority.
5. `scripts/validate_version.py` — deterministic validator (exit 0/1).
6. `scripts/tests/test_validate_version.py` — focused pytest asserting real
   repo agreement plus synthetic mismatch/edge cases.
7. Gate: run only `python scripts/validate_version.py` and focused pytest on the
   new test file. No commit/push/tag/deploy.

## Non-goals

No manifest edits (all already 0.1.0), no CI wiring, no release execution.
