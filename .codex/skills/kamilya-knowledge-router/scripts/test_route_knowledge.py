from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import socket
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).with_name("route_knowledge.py")
SPEC = importlib.util.spec_from_file_location("route_knowledge", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
FIXTURE = Path(__file__).parents[1] / "examples" / "synthetic-request.json"


def request():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class KnowledgeRouterTests(unittest.TestCase):
    def test_results_are_cited_labelled_bounded_and_deterministic(self):
        payload = request()
        first = MODULE.route(payload)
        second = MODULE.route({**payload, "records": list(reversed(payload["records"]))})
        self.assertEqual(first, second)
        self.assertEqual(first["result_count"], 3)
        self.assertRegex(first["query_hash"], r"^QH-[0-9a-f]{20}$")
        for result in first["results"]:
            self.assertTrue(result["citation"].startswith(result["path"] + ":"))
            self.assertIn(result["evidence_label"], {"GIT-DERIVED", "GRAPH-DERIVED", "NOT VERIFIED"})

        limited = MODULE.route({**payload, "limit": 1})
        self.assertEqual(limited["result_count"], 1)
        self.assertTrue(limited["truncated"])

    def test_project_scope_and_record_scope_fail_closed(self):
        payload = request()
        with self.assertRaises(MODULE.RouterContractError):
            MODULE.route({**payload, "project": "Docvoice"})
        foreign = dict(payload["records"][0]); foreign["project"] = "kamilya-landing"
        with self.assertRaises(MODULE.RouterContractError):
            MODULE.route({**payload, "records": [foreign]})

    def test_graphify_is_navigation_evidence_only(self):
        payload = request()
        graph = dict(payload["records"][1]); graph["evidence_label"] = "RUNTIME-DERIVED"
        with self.assertRaises(MODULE.RouterContractError):
            MODULE.route({**payload, "records": [graph]})

    def test_candidate_cannot_activate(self):
        payload = request()
        candidate = dict(payload["records"][2]); candidate["activation_state"] = "ACTIVE"
        with self.assertRaises(MODULE.RouterContractError):
            MODULE.route({**payload, "records": [candidate]})
        result = MODULE.route({**payload, "query": "candidate retrieval", "records": [payload["records"][2]]})
        self.assertEqual(result["results"][0]["activation_state"], "CANDIDATE_ONLY")
        self.assertEqual(result["authority"], "NONE; EVIDENCE MUST BE VERIFIED AT SOURCE")

    def test_secret_contact_and_unsafe_path_are_rejected(self):
        payload = request()
        for unsafe_text in ("api_key=hidden", "person@example.test", "+7 700 000 0000"):
            record = dict(payload["records"][0]); record["text"] = unsafe_text
            with self.subTest(unsafe_text=unsafe_text):
                with self.assertRaises(MODULE.RouterContractError):
                    MODULE.route({**payload, "records": [record]})
        record = dict(payload["records"][0]); record["path"] = "../.env"
        with self.assertRaises(MODULE.RouterContractError):
            MODULE.route({**payload, "records": [record]})

    def test_citation_is_exact_bounded_and_sanitized(self):
        payload = request()
        invalid_citations = (
            "PROJECT.md:0",
            "PROJECT.md:1:0",
            "PROJECT.md:1\nINJECTED",
            "PROJECT.md:1 person@example.test",
            "PROJECT.md:1 api_key=hidden",
            "PROJECT.md:" + "1" * 400,
        )
        for citation in invalid_citations:
            record = dict(payload["records"][0]); record["citation"] = citation
            with self.subTest(citation=citation):
                with self.assertRaises(MODULE.RouterContractError):
                    MODULE.route({**payload, "records": [record]})

    def test_graph_git_candidate_and_size_boundaries(self):
        payload = request()
        graph = dict(payload["records"][1]); graph["path"] = ".graphify/../.env"
        graph["citation"] = ".graphify/../.env:1"
        with self.assertRaises(MODULE.RouterContractError):
            MODULE.route({**payload, "records": [graph]})

        git_record = dict(payload["records"][0])
        git_record.update({
            "source_kind": "git",
            "path": "git:commit/not-a-sha",
            "citation": "git:commit/not-a-sha:1",
        })
        with self.assertRaises(MODULE.RouterContractError):
            MODULE.route({**payload, "records": [git_record]})

        candidate = dict(payload["records"][2]); candidate["candidate_id"] = "bad"
        with self.assertRaises(MODULE.RouterContractError):
            MODULE.route({**payload, "records": [candidate]})
        with self.assertRaises(MODULE.RouterContractError):
            MODULE.route({**payload, "query": "x" * (MODULE.MAX_QUERY_CHARS + 1)})
        oversized = dict(payload["records"][0]); oversized["text"] = "x" * (MODULE.MAX_TEXT_CHARS + 1)
        with self.assertRaises(MODULE.RouterContractError):
            MODULE.route({**payload, "records": [oversized]})

    def test_no_match_is_fail_quiet_and_no_index_is_persisted(self):
        payload = request()
        self.assertIsNone(MODULE.route({**payload, "query": "несовпадающийтермин"}))
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with (
                mock.patch("builtins.open", side_effect=AssertionError("filesystem access")),
                mock.patch.object(subprocess, "run", side_effect=AssertionError("subprocess access")),
                mock.patch.object(socket, "socket", side_effect=AssertionError("network access")),
            ):
                code = MODULE.main(io.StringIO(json.dumps({**payload, "query": "несовпадающийтермин"})))
        self.assertEqual((code, stdout.getvalue(), stderr.getvalue()), (0, "", ""))

        oversized_input = io.StringIO("x" * (MODULE.MAX_INPUT_BYTES + 1))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(MODULE.main(oversized_input), 2)

    def test_equal_score_ties_are_path_citation_and_id_stable(self):
        payload = request()
        left = dict(payload["records"][0])
        right = dict(payload["records"][0])
        right.update({
            "record_id": "KR-0000000000000009",
            "path": "docs/PRODUCT_BACKLOG.md",
            "citation": "docs/PRODUCT_BACKLOG.md:1",
        })
        tie_request = {**payload, "query": "tenant", "records": [right, left]}
        result = MODULE.route(tie_request)
        self.assertEqual(
            [item["path"] for item in result["results"]],
            ["PROJECT.md", "docs/PRODUCT_BACKLOG.md"],
        )

    def test_schema_and_duplicate_ids_are_rejected(self):
        payload = request()
        invalid = dict(payload); invalid["extra"] = True
        with self.assertRaises(MODULE.RouterContractError):
            MODULE.route(invalid)
        duplicate = [payload["records"][0], dict(payload["records"][0])]
        with self.assertRaises(MODULE.RouterContractError):
            MODULE.route({**payload, "records": duplicate})


if __name__ == "__main__":
    unittest.main()
