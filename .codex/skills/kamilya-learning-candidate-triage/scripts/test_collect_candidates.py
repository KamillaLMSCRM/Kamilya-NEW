from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).with_name("collect_candidates.py")
SPEC = importlib.util.spec_from_file_location("collect_candidates", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def event(**overrides):
    base = {"event_id": "EVT-0000000000000001", "observed_at": "2026-08-23T10:00:00Z", "project": "Kamilya-NEW", "kind": "TEST_FAILURE", "fingerprint": "OBS-a1b2c3d4e5f60708", "error_class": "TIMEOUT", "evidence_label": "NOT VERIFIED", "source_type": "agent_report", "source_ref": "REF-0000000000000001", "sensitive": False}
    base.update(overrides)
    return base


def second_event(**overrides):
    values = {
        "event_id": "EVT-0000000000000002",
        "source_ref": "REF-0000000000000002",
    }
    values.update(overrides)
    return event(**values)


def envelope(events=None, reviewed=None):
    return {"schema_version": 1, "events": list(events or []), "reviewed_revisions": list(reviewed or [])}


class CandidateTests(unittest.TestCase):
    def run_main(self, payload, argv=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = MODULE.main(argv or [], io.StringIO(json.dumps(payload)))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_single_observation_is_quiet(self):
        self.assertEqual(MODULE.collect_candidates([event()]), [])

    def test_two_reports_remain_inert(self):
        item = MODULE.collect_candidates([event(), second_event()])[0]
        self.assertEqual(item["state"], "CANDIDATE_ONLY")
        self.assertEqual(item["evidence_state"], "UNVERIFIED_REPORT_PATTERN")
        self.assertEqual(item["authority"], "NONE; ROOT REVIEW REQUIRED")
        self.assertEqual(item["distinct_reported_refs"], 2)

    def test_direct_evidence_does_not_promote(self):
        item = MODULE.collect_candidates([event(source_type="test", evidence_label="GIT-DERIVED"), second_event()])[0]
        self.assertEqual(item["evidence_state"], "DIRECT_EVIDENCE_PRESENT")
        self.assertEqual(item["state"], "CANDIDATE_ONLY")

    def test_programmatic_api_enforces_contract(self):
        unsafe = event(); unsafe["payload"] = "forbidden"
        with self.assertRaises(MODULE.InputContractError): MODULE.collect_candidates([unsafe, second_event()])
        with self.assertRaises(MODULE.InputContractError): MODULE.collect_candidates([event(project="Docvoice"), second_event()])

    def test_schema_version_requires_exact_integer_type(self):
        for invalid_version in (True, 1.0):
            with self.subTest(schema_version=invalid_version):
                payload = envelope()
                payload["schema_version"] = invalid_version
                with self.assertRaises(MODULE.InputContractError):
                    MODULE.validate_envelope(payload)

    def test_programmatic_api_rejects_invalid_min_occurrences_types(self):
        for invalid_value in (True, 2.0, "2"):
            with self.subTest(min_occurrences=invalid_value):
                with self.assertRaises(MODULE.InputContractError):
                    MODULE.collect_candidates([], min_occurrences=invalid_value)

    def test_programmatic_api_rejects_min_occurrences_below_two(self):
        with self.assertRaises(MODULE.InputContractError):
            MODULE.collect_candidates([], min_occurrences=1)

    def test_programmatic_api_rejects_non_iterable_events(self):
        with self.assertRaises(MODULE.InputContractError):
            MODULE.collect_candidates(None)

    def test_programmatic_api_enforces_event_count_limit(self):
        events = [
            event(
                event_id=f"EVT-{index:016x}",
                source_ref=f"REF-{index:016x}",
            )
            for index in range(MODULE.MAX_EVENTS + 1)
        ]
        with self.assertRaises(MODULE.InputContractError):
            MODULE.collect_candidates(events)

    def test_duplicate_and_conflicting_semantics(self):
        original = event()
        self.assertEqual(MODULE.collect_candidates([original, dict(original)]), [])
        with self.assertRaises(MODULE.InputContractError): MODULE.collect_candidates([original, event(source_ref="REF-0000000000000002")])

    def test_recurrence_requires_distinct_reported_refs(self):
        self.assertEqual(MODULE.collect_candidates([event(), second_event(source_ref="REF-0000000000000001")]), [])

    def test_source_label_pair_is_enforced(self):
        with self.assertRaises(MODULE.InputContractError): MODULE.collect_candidates([event(source_type="test", evidence_label="NOT VERIFIED"), second_event()])

    def test_opaque_and_sensitive_boundaries(self):
        cases = [event(source_ref="person@example.com"), event(source_ref="C:\\Docvoice\\report"), event(fingerprint="person-7072750007"), event(sensitive=True)]
        for unsafe in cases:
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(MODULE.InputContractError): MODULE.collect_candidates([unsafe, second_event()])

    def test_timestamp_requires_timezone(self):
        with self.assertRaises(MODULE.InputContractError): MODULE.collect_candidates([event(observed_at="2026-08-23T10:00:00"), second_event()])

    def test_equivalent_timestamps_have_same_revision(self):
        utc = MODULE.collect_candidates([event(), second_event()])[0]
        offset = MODULE.collect_candidates([event(observed_at="2026-08-23T15:00:00+05:00"), second_event(observed_at="2026-08-23T15:00:00+05:00")])[0]
        self.assertEqual(utc["revision_id"], offset["revision_id"])
        self.assertEqual(offset["observed_from"], "2026-08-23T10:00:00.000000Z")

    def test_baseline_suppresses_only_exact_revision(self):
        events = [event(), second_event()]
        first = MODULE.collect_candidates(events)[0]
        reviewed = {(first["candidate_id"], first["revision_id"])}
        self.assertEqual(MODULE.collect_candidates(events, reviewed), [])
        changed = events + [event(event_id="EVT-0000000000000003", source_ref="REF-0000000000000003", source_type="test", evidence_label="GIT-DERIVED")]
        item = MODULE.collect_candidates(changed, reviewed)[0]
        self.assertEqual(item["candidate_id"], first["candidate_id"])
        self.assertNotEqual(item["revision_id"], first["revision_id"])

    def test_invalid_programmatic_review_ids_are_rejected(self):
        with self.assertRaises(MODULE.InputContractError): MODULE.collect_candidates([event(), second_event()], {("bad", "bad")})

    def test_envelope_schema_is_exact(self):
        payload = envelope(); payload["payload"] = "forbidden"
        code, _, stderr = self.run_main(payload)
        self.assertEqual(code, 2); self.assertIn("schema is invalid", stderr)

    def test_reviewed_revision_schema_is_exact(self):
        code, _, stderr = self.run_main(envelope(reviewed=[{"candidate_id": "bad", "revision_id": "bad"}]))
        self.assertEqual(code, 2); self.assertIn("invalid candidate ID", stderr)

    def test_cli_is_fail_quiet(self):
        self.assertEqual(self.run_main(envelope([event()])), (0, "", ""))

    def test_cli_candidate_and_baseline(self):
        events = [event(), second_event()]
        code, stdout, stderr = self.run_main(envelope(events))
        self.assertEqual((code, stderr), (0, ""))
        item = json.loads(stdout)["candidates"][0]
        reviewed = [{"candidate_id": item["candidate_id"], "revision_id": item["revision_id"]}]
        self.assertEqual(self.run_main(envelope(events, reviewed)), (0, "", ""))

    def test_stdin_size_limit(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = MODULE.main([], io.StringIO("x" * (MODULE.MAX_INPUT_BYTES + 1)))
        self.assertEqual(code, 2); self.assertIn("size limit", stderr.getvalue())

    def test_runtime_does_not_open_files(self):
        with mock.patch("builtins.open", side_effect=AssertionError("filesystem read")):
            code, stdout, stderr = self.run_main(envelope([event(), second_event()]))
        self.assertEqual(code, 0); self.assertTrue(stdout); self.assertEqual(stderr, "")

    def test_event_order_is_deterministic(self):
        events = [event(), second_event()]
        self.assertEqual(MODULE.collect_candidates(events)[0], MODULE.collect_candidates(reversed(events))[0])


if __name__ == "__main__":
    unittest.main()
