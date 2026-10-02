"""Network-free regression checks for the standalone pilot's metric surface."""

import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from stt_pilot import (
    MODELS,
    deadline,
    edit_distance,
    file_sha256,
    normalize,
    public_get,
    select_clips,
    selected_audio,
    validate_manifest,
    validate_model,
    validate_decoded_duration,
    aggregate_rows,
    validate_report_policy,
    LANGUAGE_POLICY,
    DECODE_PARAMETERS,
)


class MetricsTests(unittest.TestCase):
    def test_aggregate_has_manually_calculated_oracle(self):
        rows = [
            dict(
                language="ru",
                reference_words=3,
                errors=error,
                latency_seconds=latency,
                real_time_factor=0.5,
            )
            for error, latency in ((1, 2), (0, 4))
        ]
        self.assertEqual(
            aggregate_rows(rows),
            {
                "ru": dict(
                    clips=2,
                    wer=1 / 6,
                    median_latency_seconds=3,
                    maximum_latency_seconds=4,
                    mean_real_time_factor=0.5,
                )
            },
        )

    def test_report_policy_rejects_tampered_claims_and_decode(self):
        report = dict(
            status="MEASURED_NOT_PRODUCT_ACCEPTANCE",
            language_policy=LANGUAGE_POLICY,
            decode_parameters=DECODE_PARAMETERS,
            mixed_speech_verified=False,
            command_fields_verified=False,
        )
        validate_report_policy(report)
        for key, value in (
            ("status", "PRODUCT_PASS"),
            ("mixed_speech_verified", True),
            ("command_fields_verified", True),
            ("decode_parameters", {}),
            ("language_policy", "all-auto"),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_report_policy(dict(report, **{key: value}))

    def test_decoded_duration_matches_metadata_and_language_bucket(self):
        clip = dict(language="ru", num_samples=240000)
        validate_decoded_duration(clip, 15)
        for duration in (0, 14.999, 20, 60, 61):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                validate_decoded_duration(clip, duration)
        validate_decoded_duration(dict(language="mixed-splice", num_samples=480000), 30)

    def test_case_punctuation_and_yo(self):
        self.assertEqual(normalize("Ещё, КУРС!"), ["еще", "курс"])

    def test_kazakh_letters_are_preserved(self):
        self.assertEqual(
            normalize("Қазақ тілі, Ә Ө Ү Ұ І Ң"),
            ["қазақ", "тілі", "ә", "ө", "ү", "ұ", "і", "ң"],
        )

    def test_negation_is_not_removed(self):
        self.assertEqual(
            edit_distance(normalize("не назначай курс"), normalize("назначай курс")), 1
        )

    def test_empty_reference(self):
        self.assertEqual(edit_distance([], ["ошибка"]), 1)

    def test_empty_hypothesis(self):
        self.assertEqual(edit_distance(["курс", "отдел"], []), 2)

    def test_identical(self):
        self.assertEqual(edit_distance(["a", "b"], ["a", "b"]), 0)

    def test_substitution_insertion_deletion(self):
        self.assertEqual(edit_distance(["a", "b", "c"], ["a", "d", "e", "c"]), 2)

    def test_date_difference_is_counted(self):
        self.assertEqual(
            edit_distance(normalize("до 09.10.2026"), normalize("до 10.10.2026")), 1
        )

    def test_private_or_non_https_source_rejected_before_io(self):
        for url in (
            "http://huggingface.co/file",
            "https://127.0.0.1/file",
            "file:///etc/passwd",
            "https://example.com/file",
        ):
            with self.subTest(url=url), patch("stt_pilot.urlopen") as request:
                with self.assertRaises(ValueError):
                    public_get(url)
                request.assert_not_called()

    def test_embedded_credentials_and_port_rejected(self):
        for url in (
            "https://secret@huggingface.co/file",
            "https://huggingface.co:444/file",
        ):
            with self.subTest(url=url), patch("stt_pilot.urlopen") as request:
                with self.assertRaises(ValueError):
                    public_get(url)
                request.assert_not_called()

    def test_corpus_selection_precedes_inference_and_skips_duplicate_sentences(self):
        tsv = "\n".join(
            f"{sid}\t{file}.wav\tТекст {sid}\tnormal\tchars\t{samples}\tMALE"
            for sid, file, samples in (
                (1, 1, 16000),
                (2, 2, 240000),
                (2, 3, 320000),
                (3, 4, 480000),
            )
        )
        selected = select_clips(tsv, 2)
        self.assertEqual([row["source_file"] for row in selected], ["2.wav", "4.wav"])

    def test_corpus_traversal_and_short_selection_rejected(self):
        for tsv in ("1\t../x.wav\ttext\tnorm\tchars\t240000\tMALE", ""):
            with self.subTest(tsv=tsv), self.assertRaises(ValueError):
                select_clips(tsv, 1)

    def test_duplicate_reference_with_different_ids_is_skipped(self):
        rows = (
            "1\t1.wav\tКурс\tnorm\tchars\t240000\tMALE\n"
            "2\t2.wav\tКУРС!\tnorm\tchars\t240000\tMALE\n"
            "3\t3.wav\tДругой\tnorm\tchars\t240000\tMALE"
        )
        self.assertEqual(
            [row["source_file"] for row in select_clips(rows, 2)], ["1.wav", "3.wav"]
        )

    def test_archive_read_never_extracts_paths_and_rejects_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "test.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                entry = tarfile.TarInfo("test/1.wav")
                entry.size = 3
                tar.addfile(entry, io.BytesIO(b"wav"))
            self.assertEqual(
                selected_audio(archive, [{"source_file": "1.wav"}]), {"1.wav": b"wav"}
            )
            self.assertEqual(list(Path(directory).iterdir()), [archive])
            with self.assertRaises(ValueError):
                selected_audio(archive, [{"source_file": "2.wav"}])

    def test_archive_rejects_links_and_duplicate_members(self):
        for link in (True, False):
            with self.subTest(link=link), tempfile.TemporaryDirectory() as directory:
                archive = Path(directory) / "test.tar.gz"
                with tarfile.open(archive, "w:gz") as tar:
                    entry = tarfile.TarInfo("test/1.wav")
                    if link:
                        entry.type = tarfile.SYMTYPE
                        entry.linkname = "/etc/passwd"
                        tar.addfile(entry)
                    else:
                        entry.size = 3
                        tar.addfile(entry, io.BytesIO(b"wav"))
                        tar.addfile(entry, io.BytesIO(b"wav"))
                with self.assertRaises(ValueError):
                    selected_audio(archive, [{"source_file": "1.wav"}])

    def test_archive_noncanonical_selected_path_rejected(self):
        for name in ("../../1.wav", "other/1.wav", "1.wav"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                archive = Path(directory) / "test.tar.gz"
                with tarfile.open(archive, "w:gz") as tar:
                    entry = tarfile.TarInfo(name)
                    entry.size = 3
                    tar.addfile(entry, io.BytesIO(b"wav"))
                with self.assertRaises(ValueError):
                    selected_audio(archive, [{"source_file": "1.wav"}])

    def test_model_label_and_artifacts_are_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hashes = {}
            for name in ("model.bin", "config.json", "tokenizer.json"):
                (root / name).write_bytes(b"artifact")
                hashes[name] = file_sha256(root / name)
            source = dict(
                model=MODELS["small"], model_license="mit", artifact_sha256=hashes
            )
            validate_model("small", source, root)
            with self.assertRaises(ValueError):
                validate_model("large-v3", source, root)
            (root / "config.json").write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                validate_model("small", source, root)

    def test_manifest_paths_counts_references_duration_and_hashes_bound(self):
        import copy

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "smoke").mkdir()
            clips = []
            for language in ("ru", "kk"):
                file = root / "smoke" / f"{language}-0.wav"
                file.write_bytes(b"wav")
                clips.append(
                    dict(
                        file=file.name,
                        language=language,
                        num_samples=240000,
                        reference="Reference",
                        audio_sha256=file_sha256(file),
                    )
                )
            corpus = dict(
                source=dict(dataset="google/fleurs"), license="CC-BY-4.0", clips=clips
            )
            validate_manifest(root, corpus)
            for key, invalid in (
                ("file", "../ru-0.wav"),
                ("reference", ""),
                ("num_samples", 16000),
                ("audio_sha256", "bad"),
                ("language", "en"),
            ):
                changed = copy.deepcopy(corpus)
                changed["clips"][0][key] = invalid
                with self.subTest(key=key), self.assertRaises(ValueError):
                    validate_manifest(root, changed)
            changed = copy.deepcopy(corpus)
            changed["clips"] *= 21
            with self.assertRaises(ValueError):
                validate_manifest(root, changed)

    def test_watchdog_raises_and_cleans_up(self):
        import signal

        with (
            patch.object(signal, "SIGALRM", 14, create=True),
            patch.object(signal, "alarm", create=True) as alarm,
            patch.object(signal, "signal") as install,
        ):
            with self.assertRaises(TimeoutError):
                with deadline(90):
                    handler = install.call_args.args[1]
                    handler(14, None)
            self.assertEqual(
                [call.args for call in alarm.call_args_list], [(90,), (0,)]
            )

    def test_response_size_limit(self):
        with patch("stt_pilot.urlopen") as request:
            request.return_value.__enter__.return_value.read.return_value = b"12345"
            with self.assertRaises(ValueError):
                public_get("https://huggingface.co/file", limit=4)


if __name__ == "__main__":
    unittest.main()
