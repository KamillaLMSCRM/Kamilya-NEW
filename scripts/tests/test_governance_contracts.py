from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


class GovernanceContractTests(unittest.TestCase):
    def test_persistent_runners_use_one_owner_and_one_handoff_interface(self) -> None:
        project_rules = read("AGENTS.md")
        test_runner = read(".codex/agents/test-runner/AGENTS.md")
        compatibility_entrypoint = read(
            ".codex/agents/test-evidence-runner/AGENTS.md"
        )
        release_runner = read(".codex/agents/release-runner/AGENTS.md")

        self.assertIn("Единственный канонический контракт", project_rules)
        self.assertIn("compatibility redirect", test_runner)
        self.assertIn("canonical Test Runner contract", compatibility_entrypoint)
        self.assertLessEqual(len(compatibility_entrypoint.splitlines()), 8)

        required_fields = ("result:", "changed:", "verified:", "blockers:", "next:")
        for contract in (test_runner, release_runner):
            for field in required_fields:
                self.assertIn(field, contract)
        self.assertNotIn("STATUS: READY", release_runner)

    def test_release_authority_and_evidence_modules_have_distinct_owners(self) -> None:
        project_rules = read("AGENTS.md")
        release_lifecycle = read("docs/releases/README.md")
        evidence_skill = read(".codex/skills/kamilya-release-evidence-gate/SKILL.md")

        self.assertIn("root retains GO/NO_GO and acceptance", release_lifecycle)
        self.assertIn("scripts/ci/release-contract-gate.py", project_rules)
        self.assertIn("Do not confuse it with", evidence_skill)
        self.assertNotIn("No phase can be skipped", evidence_skill)

    def test_graphify_archive_is_non_operational_and_semantic_runner_is_pinned(self) -> None:
        archive = read(".codex/skills/graphify/references/upstream-workflows.md")
        semantic_index = read("docs/SEMANTIC_ENGINEERING_INDEX.md")

        self.assertTrue(archive.startswith("# Archived upstream Graphify workflows"))
        self.assertIn("It is not a skill", archive)
        self.assertIn("graphifyy/Scripts/python.exe", semantic_index)
        self.assertIn("PRODUCTION_READINESS.md", semantic_index)


if __name__ == "__main__":
    unittest.main()
