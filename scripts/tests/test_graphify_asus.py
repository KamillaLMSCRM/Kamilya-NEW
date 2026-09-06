"""Offline invariants for the limited ASUS semantic indexer."""
import copy
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SOURCE = Path(__file__).resolve().parents[1] / "ops" / "graphify_asus.py"
SPEC = importlib.util.spec_from_file_location("graphify_asus", SOURCE)
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


class GraphifyAsusTests(unittest.TestCase):
    def setUp(self):
        self.result = {
            "finish_reason": "stop",
            "nodes": [{"id": "a", "label": "Course", "source_file": "adr.md"},
                      {"id": "b", "label": "Lesson", "source_file": "adr.md"}],
            "edges": [{"source": "a", "target": "b", "relation": "contains",
                       "confidence": "EXTRACTED"}],
        }

    def test_complete_graph(self):
        tool.validate_result(self.result, {"adr.md"})

    def test_truncated_response_rejected(self):
        self.result["finish_reason"] = "length"
        with self.assertRaisesRegex(ValueError, "generation_incomplete"):
            tool.validate_result(self.result, {"adr.md"})

    def test_dangling_edge_rejected(self):
        self.result["edges"][0]["target"] = "unknown"
        with self.assertRaisesRegex(ValueError, "invalid_edge"):
            tool.validate_result(self.result, {"adr.md"})

    def test_external_source_rejected(self):
        self.result["nodes"][0]["source_file"] = "../private.md"
        with self.assertRaisesRegex(ValueError, "provenance"):
            tool.validate_result(self.result, {"adr.md"})

    def test_missing_document_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing_document_coverage"):
            tool.validate_result(self.result, {"adr.md", "second.md"})

    def test_summary_budget_is_enforced(self):
        self.result["edges"] = self.result["edges"] * 7
        with self.assertRaisesRegex(ValueError, "summary_budget_exceeded"):
            tool.validate_result(self.result, {"adr.md"})

    def test_selected_section_excludes_unrelated_text(self):
        documents = {"adr.md": "# ADR\nUnrelated\n## Included\nSafe\n## Excluded\nPrivate"}
        with patch.object(tool, "SECTIONS", {"adr.md": "## Included"}):
            selected = tool.reviewed_sections(documents)["adr.md"]
        self.assertEqual(selected, "Original source lines L3-L4:\n## Included\nSafe")

    def test_duplicate_id_rejected(self):
        self.result["nodes"].append(copy.deepcopy(self.result["nodes"][0]))
        with self.assertRaisesRegex(ValueError, "provenance"):
            tool.validate_result(self.result, {"adr.md"})

    def test_document_changes_require_review(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            document = root / "adr.md"
            document.write_text("Approved public example", encoding="utf-8")
            digest = hashlib.sha256(document.read_bytes()).hexdigest()
            self.assertEqual(tool.approved_documents(root, {"adr.md": digest}),
                             {"adr.md": "Approved public example"})
            document.write_text("Unreviewed content", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "requires_review"):
                tool.approved_documents(root, {"adr.md": digest})

    def test_outside_root_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "out_of_scope"):
                tool.approved_documents(Path(folder), {"../secret.md": "unused"})

    def test_graph_publication_is_valid_json(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "out" / "graph.json"
            tool.atomic_json(path, {"nodes": ["old"]})
            tool.atomic_json(path, self.result)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), self.result)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_redirect_is_rejected_without_retry(self):
        connection = MagicMock()
        connection.getresponse.return_value.status = 302
        with patch.object(tool.http.client, "HTTPConnection", return_value=connection) as factory:
            with self.assertRaisesRegex(ValueError, "http_status_302"):
                tool.request_json("/v1/models")
            factory.assert_called_once_with("10.66.66.28", 8000, timeout=90)
            connection.request.assert_called_once()
            connection.close.assert_called_once()

    def test_unapproved_endpoint_never_opens_connection(self):
        with patch.object(tool.http.client, "HTTPConnection") as factory:
            with self.assertRaisesRegex(ValueError, "request_out_of_scope"):
                tool.request_json("/admin/restart", {})
            factory.assert_not_called()

    def test_response_limit(self):
        connection = MagicMock()
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = b"x" * 1_000_001
        with patch.object(tool.http.client, "HTTPConnection", return_value=connection):
            with self.assertRaisesRegex(ValueError, "response_too_large"):
                tool.request_json("/v1/models")

    def test_wire_payload_is_utf8_without_credentials(self):
        connection = MagicMock()
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = b'{"data": []}'
        with patch.object(tool.http.client, "HTTPConnection", return_value=connection):
            self.assertEqual(tool.request_json("/v1/chat/completions", {"text": "роль"}), {"data": []})
        args, kwargs = connection.request.call_args
        self.assertEqual(args, ("POST", "/v1/chat/completions"))
        self.assertEqual(kwargs["body"].decode("utf-8"), '{"text": "роль"}')
        self.assertEqual(kwargs["headers"], {"Content-Type": "application/json"})


if __name__ == "__main__":
    unittest.main()
