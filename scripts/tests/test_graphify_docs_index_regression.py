from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "graphify_docs_index_regression_target", ROOT / "scripts" / "ops" / "graphify_docs_index.py"
)
assert SPEC and SPEC.loader
index = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(index)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class GraphifyDocsIndexRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "docs" / "synthetic.md"
        self.source.parent.mkdir()
        self.output = self.root / "graphify-out" / "docs-semantic"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_fixture(self, lines: list[str]) -> tuple[Path, str, dict]:
        self.source.write_text("\n".join(lines) + "\n", encoding="utf-8")
        raw = self.source.read_bytes()
        sanitized, redactions = index.sanitize(raw.decode("utf-8-sig"))
        manifest = {
            "schema": index.SCHEMA_VERSION,
            "coverage_definition": "synthetic_regression_fixture",
            "documents": [
                {
                    "path": "docs/synthetic.md",
                    "sha256": digest(raw),
                    "chunks": index.make_chunks(sanitized),
                    "redactions": redactions,
                    "source_lines": len(sanitized),
                }
            ],
            "excluded": [],
        }
        manifest_path = self.root / "graphify-out" / "docs-corpus.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path, digest(manifest_path.read_bytes()), manifest

    @staticmethod
    def response(label: str = "Synthetic concept", line: int = 1, input_tokens: int = 11) -> dict:
        return {
            "model": index.MODEL,
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps({"concepts": [{"label": label, "line": line}]})},
                }
            ],
            "usage": {"prompt_tokens": input_tokens, "completion_tokens": 7},
        }

    def test_workers_two_drains_window_after_first_failure_without_third_dispatch(self) -> None:
        manifest_path, approved, manifest = self.write_fixture(["A" * 6000, "B" * 6000, "C" * 6000])
        self.assertEqual(len(manifest["documents"][0]["chunks"]), 3)
        calls: list[dict] = []

        def requester(_path: str, spec: dict) -> dict:
            calls.append(spec)
            first_line = spec["messages"][1]["content"].split("|", 1)[1]
            if first_line.startswith("A"):
                raise RuntimeError("synthetic provider failure")
            return self.response(line=1)

        evidence = index.run(
            approved,
            3,
            workers=2,
            root=self.root,
            manifest_path=manifest_path,
            output_dir=self.output,
            requester=requester,
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(evidence["requests_dispatched"], 2)
        self.assertEqual(evidence["coverage"], "partial")
        self.assertEqual(evidence["accepted"], 1)
        self.assertEqual([item["status"] for item in evidence["chunks"]], ["INCOMPLETE", "ACCEPTED", "PENDING"])
        self.assertEqual(evidence["failure"], "RuntimeError")

    def test_cache_only_second_run_has_zero_tokens_and_no_requests(self) -> None:
        manifest_path, approved, manifest = self.write_fixture(["A" * 6000, "B" * 6000])
        self.assertEqual(len(manifest["documents"][0]["chunks"]), 2)
        requester = Mock(return_value=self.response())
        first = index.run(
            approved, 2, root=self.root, manifest_path=manifest_path, output_dir=self.output, requester=requester
        )
        self.assertEqual(first["requests_successful"], 2)
        requester.reset_mock()

        second = index.run(
            approved, 2, root=self.root, manifest_path=manifest_path, output_dir=self.output, requester=requester
        )

        requester.assert_not_called()
        self.assertEqual(second["requests_dispatched"], 0)
        self.assertEqual(second["requests_successful"], 0)
        self.assertEqual(second["tokens"]["this_run_known"], {"input": 0, "output": 0})
        self.assertTrue(all(item["source"] == "CACHE" for item in second["chunks"]))

    def test_discarded_or_incomplete_chunk_declaration_is_rejected_before_network(self) -> None:
        manifest_path, approved, manifest = self.write_fixture(["Synthetic line"])
        manifest["documents"][0]["chunks"] = []
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        approved = digest(manifest_path.read_bytes())
        requester = Mock(return_value=self.response())

        with self.assertRaisesRegex(ValueError, "incomplete_chunk_coverage"):
            index.run(
                approved,
                1,
                root=self.root,
                manifest_path=manifest_path,
                output_dir=self.output,
                requester=requester,
            )

        requester.assert_not_called()

    def test_corrupted_cache_stops_with_truthful_partial_evidence_and_no_network(self) -> None:
        manifest_path, approved, manifest = self.write_fixture(["A" * 6000, "B" * 6000])
        requester = Mock(return_value=self.response())
        index.run(approved, 2, root=self.root, manifest_path=manifest_path, output_dir=self.output, requester=requester)
        chunks = index.checked_chunks(manifest, self.root)
        second_spec = index.request_spec(chunks[1])
        index.cache_path(second_spec, self.output / "cache").write_text("{corrupted", encoding="utf-8")
        requester.reset_mock()

        evidence = index.run(
            approved, 2, root=self.root, manifest_path=manifest_path, output_dir=self.output, requester=requester
        )

        requester.assert_not_called()
        self.assertEqual((evidence["coverage"], evidence["status"], evidence["accepted"]), ("partial", "PARTIAL", 1))
        self.assertEqual(evidence["denominator"], 2)
        self.assertEqual(evidence["failure"], "cache_invalid")
        self.assertEqual(evidence["chunks"][1]["reason"], "cache_invalid")

    def test_repeated_quote_uses_selected_line_for_source_location(self) -> None:
        chunk = {
            "path": "docs/synthetic.md",
            "id": "1",
            "start_line": 10,
            "end_line": 12,
            "text": "repeat\n\nrepeat",
        }
        concepts, _usage = index.response_extraction(self.response(label="Selected line", line=2), chunk["text"])
        self.assertEqual(concepts[0], {"label": "Selected line", "quote": "repeat", "line": 3})
        graph = index.build_graph([(chunk, concepts)])
        reference = next(edge for edge in graph["links"] if edge["relation"] == "references")
        self.assertEqual(reference["source_location"], "L12-L12")
        self.assertEqual(reference["span"], {"start_line": 12, "end_line": 12})

    def test_request_spec_numbers_only_nonempty_lines_densely(self) -> None:
        chunk = {"text": "first\n\n  second  \n\nthird"}
        user_content = index.request_spec(chunk)["messages"][1]["content"]
        self.assertEqual(user_content, "1|first\n2|  second  \n3|third")

    def test_model_line_must_be_integer_in_range_and_nonblank(self) -> None:
        for line in (0, 3):
            with self.subTest(line=line), self.assertRaisesRegex(ValueError, "extraction_provenance_invalid"):
                index.response_extraction(self.response(line=line), "selected\n\nother")
        concepts, _usage = index.response_extraction(self.response(line=2), "selected\n\nother")
        self.assertEqual(concepts, [{"label": "Synthetic concept", "quote": "other", "line": 3}])
        with self.assertRaisesRegex(ValueError, "extraction_provenance_invalid"):
            index.validate_extraction(
                {"concepts": [{"label": "Synthetic concept", "quote": "other", "line": 2}]},
                "selected\n\nother",
            )
        with self.assertRaisesRegex(ValueError, "extraction_provenance_invalid"):
            index.response_extraction(self.response(line=True), "selected")

    def test_exception_secret_text_is_neither_emitted_nor_persisted(self) -> None:
        manifest_path, approved, _manifest = self.write_fixture(["Synthetic safe line"])
        secret = "provider-secret-value-should-not-leak"
        output = io.StringIO()

        def requester(_path: str, _spec: dict) -> dict:
            raise RuntimeError(secret)

        with contextlib.redirect_stdout(output):
            evidence = index.run(
                approved,
                1,
                root=self.root,
                manifest_path=manifest_path,
                output_dir=self.output,
                requester=requester,
            )

        self.assertEqual(evidence["failure"], "RuntimeError")
        self.assertNotIn(secret, output.getvalue())
        persisted = b"".join(path.read_bytes() for path in self.output.rglob("*") if path.is_file())
        self.assertNotIn(secret.encode(), persisted)


if __name__ == "__main__":
    unittest.main()
