import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops"))
import graphify_docs_corpus as corpus


class CorpusTests(unittest.TestCase):
    def test_case_filename_and_unknown_skill_exclusions(self):
        for path in (
            "docs/Marketing/report.md",
            "docs/customer.md",
            "docs/Archive/note.md",
            ".codex/skills/private-notes/SKILL.md",
        ):
            self.assertIsNotNone(corpus.selection(path))

    def test_selected_boundaries(self):
        for path in ("AGENTS.md", "docs/adr/0008-auth-strategy.md", ".codex/skills/graphify/SKILL.md"):
            self.assertIsNone(corpus.selection(path))
        for path in (
            "docs/marketing/report.md",
            "docs/customer/test.md",
            "apps/api/README.md",
            "docs/plans/old.md",
            "docs/legal/dpa.md",
            "docs/DocumentKZ/README.md",
            "docs/product/2026-08-22_kamilya-pricing-policy-proposal.md",
        ):
            self.assertIsNotNone(corpus.selection(path))

    def test_sensitive_and_fenced_lines_removed_without_line_shift(self):
        text = "# Safe\n```sh\nsecret data\n```\nuser@example.com\npassword=example\n10.1.2.3\nKeep"
        lines, counts = corpus.sanitize(text)
        self.assertEqual(lines, ["# Safe", "", "", "", "", "", "", "Keep"])
        self.assertEqual(counts["sensitive_line"], 3)

    def test_url_credentials_and_queries_not_sent(self):
        lines, _ = corpus.sanitize("See https://example.com/?key=private\nhttps://u:p@host/path")
        self.assertEqual(lines, ["See [URL OMITTED]", ""])

    def test_quoted_credentials_uuid_customer_context_removed(self):
        lines, _ = corpus.sanitize('"token": "synthetic"\nTenant 00000000-0000-0000-0000-000000000000\nKarcher example')
        self.assertEqual(lines, ["", "", ""])

    def test_chunk_coverage_exact(self):
        lines = ["abc", "def", "ghi", "", "jkl"]
        parts = corpus.chunks(lines, limit=9)
        self.assertEqual([p["text"] for p in parts], ["abc\ndef", "ghi\n\njkl"])
        self.assertEqual([(p["start_line"], p["end_line"]) for p in parts], [(1, 2), (3, 5)])

    def test_long_line_stops_instead_of_silent_truncation(self):
        with self.assertRaises(ValueError):
            corpus.chunks(["x" * 11], limit=10)


if __name__ == "__main__":
    unittest.main()
