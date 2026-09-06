from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "graphify_docs_index", ROOT / "scripts" / "ops" / "graphify_docs_index.py"
)
assert SPEC and SPEC.loader
index = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(index)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class GraphifyDocsIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "docs" / "safe.md"
        self.source.parent.mkdir()
        self.source.write_text("# Safe\n\nUseful concept here.\n", encoding="utf-8")
        raw = self.source.read_bytes()
        self.manifest = {
            "schema": 1,
            "coverage_definition": "test_sanitized_prose",
            "documents": [
                {
                    "path": "docs/safe.md",
                    "sha256": digest(raw),
                    "chunks": [
                        {"id": "1", "start_line": 1, "end_line": 3, "text": "# Safe\n\nUseful concept here."}
                    ],
                    "redactions": {"fenced_code": 0, "sensitive_line": 0, "urls": 0},
                    "source_lines": 3,
                }
            ],
            "excluded": [{"path": "docs/private.md", "reason": "not reviewed"}],
        }
        self.manifest_path = self.root / "graphify-out" / "docs-corpus.json"
        self.manifest_path.parent.mkdir()
        raw_manifest = json.dumps(self.manifest).encode()
        self.manifest_path.write_bytes(raw_manifest)
        self.approved = digest(raw_manifest)
        self.output = self.root / "graphify-out" / "docs-semantic"

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def valid_response() -> dict:
        return {
            "model": index.MODEL,
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": '{"concepts":[{"label":"Useful concept","line":2}]}'},
                }
            ],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7},
        }

    def test_scope_and_hash_approval_are_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "approved_sha256_required"):
            index.load_manifest(self.root, self.manifest_path, None)
        with self.assertRaisesRegex(ValueError, "manifest_digest_mismatch"):
            index.load_manifest(self.root, self.manifest_path, "0" * 64)
        self.manifest["documents"][0]["path"] = "../outside.md"
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        approved = digest(self.manifest_path.read_bytes())
        with self.assertRaisesRegex(ValueError, "document_out_of_scope"):
            index.checked_chunks(index.load_manifest(self.root, self.manifest_path, approved), self.root)

    def test_cache_invalidation_and_no_network_on_hit(self) -> None:
        requester = Mock(return_value=self.valid_response())
        first = index.run(
            self.approved,
            1,
            root=self.root,
            manifest_path=self.manifest_path,
            output_dir=self.output,
            requester=requester,
        )
        self.assertEqual(first["requests_successful"], 1)
        requester.reset_mock()
        second = index.run(
            self.approved,
            1,
            root=self.root,
            manifest_path=self.manifest_path,
            output_dir=self.output,
            requester=requester,
        )
        requester.assert_not_called()
        self.assertEqual(second["chunks"][0]["source"], "CACHE")
        self.assertEqual(second["tokens"]["this_run_known"], {"input": 0, "output": 0})
        changed = self.source.read_text(encoding="utf-8").replace("here.", "again.")
        self.source.write_text(changed, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "source_hash_mismatch"):
            index.run(
                self.approved,
                1,
                root=self.root,
                manifest_path=self.manifest_path,
                output_dir=self.output,
                requester=requester,
            )

    def test_schema_truncation_and_provenance_are_rejected(self) -> None:
        chunk = index.checked_chunks(self.manifest, self.root)[0]
        with self.assertRaisesRegex(ValueError, "generation_incomplete"):
            index.response_extraction(
                {"model": index.MODEL, "choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
                chunk["text"],
            )
        with self.assertRaisesRegex(ValueError, "extraction_provenance_invalid"):
            index.validate_extraction({"concepts": [{"label": "x", "quote": "not present"}]}, chunk["text"])
        with self.assertRaisesRegex(ValueError, "extraction_schema_invalid"):
            index.validate_extraction({"concepts": [], "extra": True}, chunk["text"])

    def test_truthful_partial_coverage_and_orphan_endpoints(self) -> None:
        requester = Mock(
            return_value={"model": index.MODEL, "choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}
        )
        evidence = index.run(
            self.approved,
            1,
            root=self.root,
            manifest_path=self.manifest_path,
            output_dir=self.output,
            requester=requester,
        )
        self.assertEqual((evidence["coverage"], evidence["accepted"], evidence["denominator"]), ("partial", 0, 1))
        self.assertEqual(evidence["chunks"][0]["status"], "INCOMPLETE")
        with self.assertRaisesRegex(ValueError, "graph_orphan_endpoint"):
            index.validate_node_link({"nodes": [{"id": "doc"}], "links": [{"source": "doc", "target": "missing"}]})

    def test_graphify_attributes_and_original_quote_location(self) -> None:
        chunk = index.checked_chunks(self.manifest, self.root)[0]
        graph = index.build_graph([(chunk, [{"label": "Useful concept", "quote": "Useful concept here"}])])
        concept = next(node for node in graph["nodes"] if node["kind"] == "concept")
        reference = next(edge for edge in graph["links"] if edge["relation"] == "references")
        self.assertEqual(
            (concept["source_file"], concept["source_location"], concept["file_type"]),
            ("docs/safe.md", "L3-L3", "concept"),
        )
        self.assertEqual(
            (reference["confidence"], reference["source_file"], reference["source_location"]),
            ("EXTRACTED", "docs/safe.md", "L3-L3"),
        )


if __name__ == "__main__":
    unittest.main()
