#!/usr/bin/env python3
"""Focused CPU-only contract tests for the methodologist walkthrough tooling."""

from __future__ import annotations

import base64
import json
import os
import re
import struct
import subprocess
import tempfile
import unittest
from unittest import mock
import wave
from pathlib import Path

import render_methodologist_walkthrough as renderer
import synthesize_methodologist_walkthrough as synth


def write_wav(path: Path, duration: float = 0.6, sample_rate: int = 8000) -> None:
    frames = int(duration * sample_rate)
    values = []
    for index in range(frames):
        values.append(1200 if index % 40 < 20 else -1200)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(struct.pack("<%dh" % len(values), *values))


def png_header(width: int = 1, height: int = 1) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height)


def manifest() -> dict:
    chapters = []
    for chapter_index in range(1, 9):
        segments = []
        for segment_index in range(1, 5):
            segments.append({
                "shot_id": f"m{chapter_index:02d}-s{segment_index:02d}-shot",
                "route": "/dashboard",
                "required_visible_controls": ["Задачи"],
                "action_before_capture": "Откройте тестовую страницу.",
                "narration_ru": f"Полная инструкция главы {chapter_index}, шага {segment_index}: проверьте видимые элементы и сохраните результат.",
                "expected_result": "Тестовый результат виден.",
                "capture_privacy_notes": "Синтетические данные.",
            })
        chapters.append({"id": f"{chapter_index:02d}-chapter", "title_ru": f"Глава {chapter_index}", "segments": segments})
    return {"schema_version": 1, "title_ru": "Тест", "recording_disclosure_ru": "Локальная запись.", "chapters": chapters}


def segments_for(data: dict) -> list[dict]:
    return renderer.segments_for(data)


class CaptionContracts(unittest.TestCase):
    def test_every_narration_word_survives_and_cues_are_complete(self) -> None:
        data = manifest()
        clips = {segment["shot_id"]: {"duration_seconds": 1.0} for segment in segments_for(data)}
        for segment in segments_for(data):
            cues = renderer.wrap_cues(segment["narration_ru"])
            self.assertEqual(" ".join(" ".join(cue.split()) for cue in cues).split(), segment["narration_ru"].split())
            self.assertLessEqual(max(len(line) for cue in cues for line in cue.splitlines()), 80)
            self.assertTrue(all(len(cue.splitlines()) <= 2 for cue in cues))

    def test_each_video_starts_at_zero_and_ends_within_duration(self) -> None:
        data = manifest()
        chapter = data["chapters"][1]
        chapter_segments = [segment for segment in segments_for(data) if segment["chapter_id"] == chapter["id"]]
        clips = {segment["shot_id"]: {"duration_seconds": 1.0} for segment in chapter_segments}
        cues = renderer.cue_entries(chapter_segments, clips, 0.0)
        self.assertEqual(cues[0]["start"], 0.0)
        self.assertLessEqual(cues[-1]["end"], 4.6)
        self.assertGreater(cues[-1]["end"], cues[-1]["start"])

    def test_wav_validation_measures_pcm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clip.wav"
            write_wav(path)
            info = synth.validate_wav(path)
            self.assertGreater(info["peak_amplitude"], 0)
            self.assertGreater(info["active_sample_ratio"], 0)
            self.assertTrue(info["finite_pcm_measured"])


class SynthesisContracts(unittest.TestCase):
    def test_model_fingerprint_detects_same_size_weight_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "model"
            model.mkdir()
            weight = model / "weights.bin"
            weight.write_bytes(b"AAAA")
            first = synth.model_fingerprint(model)
            weight.write_bytes(b"BBBB")
            second = synth.model_fingerprint(model)
            self.assertEqual(first["size_bytes"], second["size_bytes"])
            self.assertNotEqual(first["sha256"], second["sha256"])

    def test_text_change_does_not_invalidate_unrelated_clip_key(self) -> None:
        args = type("Args", (), {})()
        args.max_new_tokens = 512
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "model"
            model.mkdir()
            (model / "config.json").write_text("model")
            ref = Path(tmp) / "ref.wav"
            write_wav(ref)
            args.model = model
            args.reference_audio = ref
            args.reference_text = "тестовый голос"
            data = manifest()
            config = synth.synthesis_config(args, data)
            first = segments_for(data)[0]
            second = segments_for(data)[1]
            key_one_before = synth.receipt_key(config, first)
            second_before = synth.receipt_key(config, second)
            changed = dict(first, narration_ru=first["narration_ru"] + " Дополнение.")
            key_one_after = synth.receipt_key(config, changed)
            self.assertNotEqual(key_one_before["text_sha256"], key_one_after["text_sha256"])
            self.assertEqual(second_before["config_sha256"], synth.receipt_key(config, second)["config_sha256"])

    def test_partial_receipt_can_resume_only_unfinished_clip(self) -> None:
        data = manifest()
        segments = segments_for(data)[:2]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            wav = output / f"{segments[0]['shot_id']}.wav"
            write_wav(wav)
            config = {"engine": "qwen-tts"}
            first_clip = {**synth.receipt_key(config, segments[0]), "wav_path": str(wav), "sha256": synth.sha256_file(wav), "ready": True}
            receipt = {"config_sha256": synth.sha256_text(synth.canonical_json(config)), "clips": [first_clip]}
            (output / synth.RECEIPT_NAME).write_text(json.dumps(receipt))
            loaded = synth.read_receipt(output / synth.RECEIPT_NAME)
            self.assertIsNotNone(loaded)
            prior = next(item for item in loaded["clips"] if item["shot_id"] == segments[0]["shot_id"])
            self.assertEqual(prior["sha256"], synth.sha256_file(wav))
            self.assertFalse((output / f"{segments[1]['shot_id']}.wav").exists())


class RenderContracts(unittest.TestCase):
    def test_public_tree_descendants_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            public = Path(tmp) / "public"
            public.mkdir()
            with self.assertRaises(SystemExit):
                renderer.check_output(public / "media", public, False)
            with self.assertRaises(SystemExit):
                renderer.check_output(Path(tmp), public, False)

    def test_atomic_write_text_emits_deterministic_utf8_lf_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "captions.srt"
            renderer.atomic_write_text(path, "1\r\nПривет\r\n")
            self.assertEqual(path.read_bytes(), b"1\n\xd0\x9f\xd1\x80\xd0\xb8\xd0\xb2\xd0\xb5\xd1\x82\n")

    def test_text_html_embeds_png_bytes_and_alt_text(self) -> None:
        data = manifest()
        png = png_header(1920, 1080)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            screens = {segment["shot_id"]: output / f"{segment['shot_id']}.png" for segment in segments_for(data)}
            for path in screens.values():
                path.write_bytes(png)
            chapters = [{"id": data["chapters"][0]["id"], "title_ru": data["chapters"][0]["title_ru"], "segments": [segments_for(data)[0]], "recorded_date": "2026-01-01"}]
            renderer.render_text(output, data, chapters, "rev", screens)
            page = (output / "text.html").read_text(encoding="utf-8")
            expected = base64.b64encode(png).decode("ascii")
            self.assertIn(f"data:image/png;base64,{expected}", page)
            self.assertNotIn(f"{segments_for(data)[0]['shot_id']}.png", page.split("base64,")[1].split('"')[0])

    def test_non_square_overlay_uses_png_pixel_geometry(self) -> None:
        data = manifest()
        chapter = data["chapters"][0]
        segment = chapter["segments"][0]
        segment["marks"] = [[10, 20, 30, 10]]
        png = png_header(1920, 1080)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            screens = {segment["shot_id"]: output / f"{segment['shot_id']}.png"}
            screens[segment["shot_id"]].write_bytes(png)
            chapters = [{
                "id": chapter["id"],
                "title_ru": chapter["title_ru"],
                "segments": [segment],
                "recorded_date": "2026-01-01",
            }]
            renderer.render_text(output, data, chapters, "rev", screens)
            page = (output / "text.html").read_text(encoding="utf-8")
            self.assertIn('viewBox="0 0 1920 1080"', page)
            match = re.search(r'<rect x="([^"]+)" y="([^"]+)" width="([^"]+)" height="([^"]+)" rx="5"', page)
            self.assertIsNotNone(match)
            x, y, width, height = (float(value) for value in match.groups())
            self.assertAlmostEqual(x, 192.0)
            self.assertAlmostEqual(y, 216.0)
            self.assertAlmostEqual(width, 576.0)
            self.assertAlmostEqual(height, 108.0)
            rendered_scale = 832.0 / 1920.0
            self.assertAlmostEqual(x * rendered_scale, 83.2)
            self.assertAlmostEqual(width * rendered_scale, 249.6)
            self.assertIn('<circle cx="188.00" cy="208.00" r="15"', page)
            self.assertIn('<text x="188.00" y="213.00" text-anchor="middle">1</text>', page)
            self.assertIn('stroke-width:2.5', page)
            self.assertIn('font:bold 17px Arial,sans-serif', page)

    def test_non_square_capture_receipt_maps_to_png_pixels(self) -> None:
        data = manifest()
        chapter = data["chapters"][0]
        segment = chapter["segments"][0]
        png = png_header(1920, 1080)
        with tempfile.TemporaryDirectory() as tmp:
            screens_dir = Path(tmp)
            screens = {segment["shot_id"]: screens_dir / f"{segment['shot_id']}.png"}
            screens[segment["shot_id"]].write_bytes(png)
            receipt = {
                "shot_id": segment["shot_id"],
                "png_sha256": synth.sha256_file(screens[segment["shot_id"]]),
                "viewport": {"width": 1440, "height": 1000},
                "visible_controls_verified": True,
                "verified_controls": [{
                    "name": "Задачи",
                    "boundingBox": {"x": 144, "y": 200, "width": 432, "height": 100},
                }],
            }
            (screens_dir / f"{segment['shot_id']}.capture.json").write_text(json.dumps(receipt))
            marks = renderer.load_capture_marks(screens_dir, screens, data)
            self.assertAlmostEqual(marks[segment["shot_id"]][0]["rect"][0], 192.0)
            self.assertAlmostEqual(marks[segment["shot_id"]][0]["rect"][1], 216.0)
            self.assertAlmostEqual(marks[segment["shot_id"]][0]["rect"][2], 576.0)
            self.assertAlmostEqual(marks[segment["shot_id"]][0]["rect"][3], 108.0)
            output = screens_dir / "out"
            output.mkdir()
            chapters = [{
                "id": chapter["id"],
                "title_ru": chapter["title_ru"],
                "segments": [segment],
                "recorded_date": "2026-01-01",
            }]
            renderer.render_text(output, data, chapters, "rev", screens, marks)
            page = (output / "text.html").read_text(encoding="utf-8")
            self.assertIn('viewBox="0 0 1920 1080"', page)
            self.assertIn('<rect x="192.00" y="216.00" width="576.00" height="108.00" rx="5"', page)
            self.assertIn('<circle cx="188.00" cy="208.00" r="15"', page)
            self.assertIn('<text x="188.00" y="213.00" text-anchor="middle">1</text>', page)

    def test_resume_rejects_same_duration_stale_render_key(self) -> None:
        key_a = {"segments": [{"audio_sha256": "a", "screen_sha256": "s", "narration_sha256": "n"}], "renderer": "ffmpeg_concat_v1", "paused": False}
        key_b = {"segments": [{"audio_sha256": "b", "screen_sha256": "s", "narration_sha256": "n"}], "renderer": "ffmpeg_concat_v1", "paused": False}
        self.assertNotEqual(renderer.sha256_text(renderer.canonical_json(key_a)), renderer.sha256_text(renderer.canonical_json(key_b)))

    def test_public_guard_rejects_symlink_into_public_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            public = Path(tmp) / "apps" / "web" / "public"
            public.mkdir(parents=True)
            child = public / "media"
            child.mkdir()
            link = Path(tmp) / "linked-media"
            try:
                link.symlink_to(child, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation unsupported or permission-denied: {exc}")
            with self.assertRaises(SystemExit):
                renderer.check_output(link, public, False)

    def test_main_accepts_resume_and_uses_matching_audio_clip_name(self) -> None:
        data = manifest()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            screens = root / "screens"
            audio = root / "audio"
            output = root / "out"
            screens.mkdir()
            audio.mkdir()
            output.mkdir()
            png = png_header(1920, 1080)
            clips = []
            for segment in segments_for(data):
                shot = segment["shot_id"]
                (screens / f"{shot}.png").write_bytes(png)
                wav = audio / f"{shot}.wav"
                write_wav(wav, duration=0.4, sample_rate=8000)
                clips.append({
                    "shot_id": shot,
                    "chapter_id": segment["chapter_id"],
                    "text": segment["narration_ru"],
                    "text_sha256": synth.sha256_text(segment["narration_ru"]),
                    "wav_path": f"/remote/linux/{shot}.wav",
                    "sha256": synth.sha256_file(wav),
                    "duration_seconds": 0.4,
                    "ready": True,
                })
            receipt = {
                "config_sha256": "a" * 64,
                "manifest_sha256": synth.sha256_text(renderer.canonical_json(data)),
                "clips": clips,
            }
            (audio / "tts-receipt.json").write_text(json.dumps(receipt))
            args = type("Args", (), {})()
            args.manifest = root / "manifest.json"
            args.manifest.write_text(json.dumps(data))
            args.screens = screens
            args.audio = audio
            args.output = output
            args.source_revision = "rev"
            args.public_dir = None
            args.resume = True
            def fake_ffmpeg_concat(segment_items, screen_items, clip_items, chapter_mp4: Path) -> None:
                chapter_mp4.parent.mkdir(parents=True, exist_ok=True)
                chapter_mp4.write_bytes(b"fake-mp4")

            def fake_poster(chapter_mp4: Path, screen_items, first_shot: str, poster_path: Path) -> None:
                poster_path.parent.mkdir(parents=True, exist_ok=True)
                poster_path.write_bytes(b"fake-poster")

            def fake_media_metadata(path: Path) -> dict:
                payload = path.read_bytes()
                return {
                    "duration_seconds": 1.6,
                    "video_codec": "h264",
                    "audio_codec": "aac",
                    "width": 1920,
                    "height": 1080,
                    "pix_fmt": "yuv420p",
                    "sample_rate": 48000,
                    "channels": 2,
                    "size_bytes": len(payload),
                    "sha256": synth.sha256_file(path),
                }

            with mock.patch.object(renderer, "ffmpeg_concat", side_effect=fake_ffmpeg_concat), \
                 mock.patch.object(renderer, "poster", side_effect=fake_poster), \
                 mock.patch.object(renderer, "media_metadata", side_effect=fake_media_metadata), \
                 mock.patch.object(
                     renderer,
                     "encoded_step_starts",
                     side_effect=lambda path, segments, clip_durations: renderer.segment_starts(
                         segments, clip_durations
                     ),
                 ):
                self.assertEqual(renderer.main([
                    "--manifest", str(args.manifest),
                    "--screens", str(screens),
                    "--audio", str(audio),
                    "--output", str(output),
                    "--source-revision", "rev",
                    "--resume",
                ]), 0)


class EncodedStepBoundaryContracts(unittest.TestCase):
    def mapped(self, nominal: float, timestamps: list[str]) -> list[dict]:
        segments = [{"shot_id": "first"}, {"shot_id": "second"}]
        clips = {"first": {"duration_seconds": nominal}, "second": {"duration_seconds": 4.0}}
        result = subprocess.CompletedProcess([], 0, json.dumps({"frames": [{"best_effort_timestamp_time": value} for value in timestamps]}), "")
        with mock.patch.object(renderer, "FFPROBE", "ffprobe"), mock.patch.object(renderer.subprocess, "run", return_value=result):
            return renderer.encoded_step_starts(Path("accepted.mp4"), segments, clips)

    def test_rounds_up_actual_scene_start_instead_of_nominal_audio(self) -> None:
        steps = self.mapped(17.28, ["0.042643", "8.375977", "16.709310", "17.309310"])
        self.assertEqual([step["start"] for step in steps], [0.0, 17.310])

    def test_regular_keyframe_before_nominal_is_not_a_scene_start(self) -> None:
        steps = self.mapped(8.4, ["0.042643", "8.375977", "8.442643"])
        self.assertEqual([step["start"] for step in steps], [0.0, 8.443])

    def test_missing_boundary_is_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            self.mapped(8.4, ["0.042643"])

    def test_ambiguous_boundary_is_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            self.mapped(8.4, ["0.042643", "8.410000", "8.440000"])

    def test_nonfinite_timestamp_is_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            self.mapped(8.4, ["0.042643", "NaN"])


if __name__ == "__main__":
    unittest.main()
