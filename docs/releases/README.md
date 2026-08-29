# Releases

This project uses [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html)
and [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) conventions.

## Semantic Versioning

Given a version `MAJOR.MINOR.PATCH` (for example `0.1.0`):

- **MAJOR** — increment for incompatible API changes (breaking user-visible or
  API-visible behavior).
- **MINOR** — increment for new backwards-compatible functionality.
- **PATCH** — increment for backwards-compatible bug fixes.

While the product is in `0.x.y`, the MAJOR component is `0` and minor
increments may carry breaking changes, which is the standard pre-1.0
convention.

Kamilya currently publishes stable versions only, in the exact `X.Y.Z`
format. Pre-release (`-rc.1`) and build (`+build.1`) suffixes are intentionally
not accepted by the version gate. If release candidates are introduced later,
the policy, validator, tests, and release tooling must change together.

## Version sources of truth

- `VERSION` at repository root is the single canonical product version string.
- `apps/api/pyproject.toml` (`[tool.poetry] version`) and
  `apps/web/package.json` (`version`) must agree with `VERSION`.
- The deterministic check `scripts/validate_version.py` (with focused tests in
  `scripts/tests/test_validate_version.py`) asserts this agreement.

## Release lifecycle

1. **Develop** — work lands on a branch. Every user-visible change (feature,
   fix, security change) must be added under `CHANGELOG.md` →
   `[Unreleased]` in the matching category (Added/Changed/Deprecated/Removed/
   Fixed/Security) in the same change.
2. **Validate** — run `python scripts/validate_version.py` locally and in CI;
   it exits non-zero when `VERSION` and app manifests disagree or the
   changelog has no `[Unreleased]` section.
3. **Release (root orchestrator only)** — the root orchestrator:
   - moves `[Unreleased]` changelog entries into a dated
     `## [X.Y.Z] - YYYY-MM-DD` section,
   - bumps `VERSION` and both app manifests to the same `X.Y.Z`,
   - creates the release tag,
   - claims the release and deploys.
4. **Post-release** — a fresh empty `[Unreleased]` section starts the next
   cycle.

The first release has no changelog comparison link because no earlier product
tag exists. From the second release onward, root adds an `[Unreleased]`
comparison URL using the actual repository and the latest published tag.

## Rules for all agents

- Add user-visible changes to `CHANGELOG.md` under `[Unreleased]`.
- Do **not** bump `VERSION`, create tags, claim a release, or deploy. Only the
  root orchestrator performs those actions (see `AGENTS.md`).
