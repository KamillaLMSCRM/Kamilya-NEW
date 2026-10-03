"""Network-free policy/metric regression for isolated quality experiments."""

import copy
import unittest
from unittest.mock import patch

from stt_quality import (
    PROFILES,
    STATUS,
    RUNTIME,
    decode_policy,
    verify_report,
    metric_groups,
    typed_report,
)
from stt_pilot import aggregate_rows


class QualityPolicyTests(unittest.TestCase):
    def test_auto_modes_never_use_reference_language_or_previous_text(self):
        for profile in ("auto-segment-15s", "auto-segment-30s"):
            for language in ("ru", "kk", "mixed-splice"):
                policy = decode_policy(profile, language)
                self.assertIsNone(policy["language"])
                self.assertTrue(policy["multilingual"])
                self.assertFalse(policy["condition_on_previous_text"])
                self.assertEqual(policy["task"], "transcribe")
                self.assertNotIn("initial_prompt", policy)

    def test_baseline_matches_previous_known_language_policy(self):
        self.assertEqual(decode_policy("hinted-baseline", "kk")["language"], "kk")
        self.assertIsNone(decode_policy("hinted-baseline", "mixed-splice")["language"])
        self.assertEqual(decode_policy("auto-segment-15s", "kk")["chunk_length"], 15)
        with self.assertRaises(ValueError):
            decode_policy("unexpected", "kk")

    @patch("stt_quality.file_sha256", return_value="manifest")
    def test_auditor_rejects_field_claim_reference_leak_and_wrong_metrics(self, digest):
        from pathlib import Path

        clip = dict(
            file="kk-0.wav",
            language="kk",
            reference="бір екі",
            num_samples=240000,
            audio_sha256="audio",
        )
        row = dict(
            file="kk-0.wav",
            language="kk",
            reference="бір екі",
            transcript="бір",
            duration_seconds=15,
            latency_seconds=3,
            real_time_factor=0.2,
            reference_words=2,
            errors=1,
            effective_policy=decode_policy("auto-segment-15s", "kk"),
        )
        report = dict(
            profile="auto-segment-15s",
            status=STATUS,
            metric_schema=2,
            model_name="large-v3",
            runtime_versions=RUNTIME,
            artificial_splice=None,
            decode_parameters=PROFILES["auto-segment-15s"],
            source={},
            corpus_manifest_sha256="manifest",
            input_sha256={"kk-0.wav": "audio"},
            device="cpu",
            compute_type="int8",
            cpu_threads=4,
            concurrency=1,
            natural_mixed_verified=False,
            command_fields_verified=False,
            clips=[row],
            languages=aggregate_rows([row]),
        )
        verify_report(Path("."), report, {"clips": [clip]}, {})
        for mutate in (
            lambda value: value.update(command_fields_verified=True),
            lambda value: value.update(runtime_versions={}),
            lambda value: value["clips"][0]["effective_policy"].update(
                initial_prompt="бір екі"
            ),
            lambda value: value["clips"][0].update(errors=0),
            lambda value: value["clips"][0].update(latency_seconds=float("nan")),
        ):
            changed = copy.deepcopy(report)
            mutate(changed)
            with self.assertRaises(ValueError):
                verify_report(Path("."), changed, {"clips": [clip]}, {})

    def test_splice_is_mechanically_separate_and_not_acceptance_eligible(self):
        rows = [
            dict(
                language=language,
                reference_words=10,
                errors=1,
                latency_seconds=2,
                real_time_factor=0.1,
            )
            for language in ("ru", "kk", "mixed-splice")
        ]
        grouped = metric_groups(rows)
        self.assertEqual(set(grouped["languages"]), {"ru", "kk"})
        self.assertFalse(grouped["artificial_splice"]["acceptance_eligible"])
        legacy = dict(clips=rows, languages=aggregate_rows(rows))
        normalized = typed_report(legacy)
        self.assertEqual(normalized["metric_schema"], 2)
        self.assertIn("mixed-splice", legacy["languages"])
        self.assertNotIn("mixed-splice", normalized["languages"])
        legacy["languages"]["ru"]["wer"] = 0
        with self.assertRaises(ValueError):
            typed_report(legacy)


if __name__ == "__main__":
    unittest.main()
