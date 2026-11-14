#!/usr/bin/env python3
"""Render the methodologist walkthrough video and standalone text page.

The renderer is intentionally conservative: it refuses to write public output
unless every manifest segment has a real screenshot and a matching synthesized
WAV receipt. It never reads customer data, never contacts a remote service and
never invents UI elements.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import math
import os
import re
import shutil
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
CHAPTERS = 8
MEDIA_FOLDER = "methodologist-qwen-male-20261113"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
SHOT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,95}$")
PNG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.png$")
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"ERROR: {message}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        fail(f"not a valid PNG with IHDR: {path}")
    width, height = struct.unpack(">II", header[16:24])
    if width <= 0 or height <= 0:
        fail(f"PNG has invalid dimensions: {path}")
    return width, height


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    tmp.write_bytes(normalized.encode("utf-8"))
    os.replace(tmp, path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"manifest not found: {path}")
    except json.JSONDecodeError as exc:
        fail(f"manifest is not valid JSON: {exc}")
    if not isinstance(manifest, dict):
        fail("manifest root must be an object")
    required = {"schema_version", "title_ru", "recording_disclosure_ru", "chapters"}
    missing = required - set(manifest)
    if missing:
        fail(f"manifest missing keys: {sorted(missing)}")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        fail(f"unsupported manifest schema_version: {manifest.get('schema_version')!r}")
    chapters = manifest.get("chapters")
    if not isinstance(chapters, list) or len(chapters) != CHAPTERS:
        fail(f"manifest must contain exactly {CHAPTERS} chapters")
    seen_chapters: set[str] = set()
    seen_shots: set[str] = set()
    for chapter in chapters:
        if not isinstance(chapter, dict):
            fail("each chapter must be an object")
        chapter_id = chapter.get("id")
        if not isinstance(chapter_id, str) or not ID_RE.match(chapter_id):
            fail(f"invalid chapter id: {chapter_id!r}")
        if chapter_id in seen_chapters:
            fail(f"duplicate chapter id: {chapter_id}")
        seen_chapters.add(chapter_id)
        if not isinstance(chapter.get("title_ru"), str) or not chapter["title_ru"].strip():
            fail(f"chapter {chapter_id} has empty title_ru")
        segments = chapter.get("segments")
        if not isinstance(segments, list) or not (3 <= len(segments) <= 5):
            fail(f"chapter {chapter_id} must contain 3-5 segments")
        for segment in segments:
            if not isinstance(segment, dict):
                fail(f"chapter {chapter_id} contains a non-object segment")
            required_segment = {
                "shot_id",
                "route",
                "required_visible_controls",
                "action_before_capture",
                "narration_ru",
                "expected_result",
                "capture_privacy_notes",
            }
            missing = required_segment - set(segment)
            if missing:
                fail(f"chapter {chapter_id} segment missing keys: {sorted(missing)}")
            shot_id = segment.get("shot_id")
            if not isinstance(shot_id, str) or not SHOT_RE.match(shot_id):
                fail(f"invalid shot_id: {shot_id!r}")
            if shot_id in seen_shots:
                fail(f"duplicate shot_id: {shot_id}")
            seen_shots.add(shot_id)
            for key in ("route", "narration_ru", "action_before_capture", "expected_result", "capture_privacy_notes"):
                if not isinstance(segment.get(key), str) or not segment[key].strip():
                    fail(f"{shot_id}.{key} must be a non-empty string")
            controls = segment.get("required_visible_controls")
            if not isinstance(controls, list) or not controls or not all(isinstance(item, str) and item.strip() for item in controls):
                fail(f"{shot_id}.required_visible_controls must be a non-empty string list")
    return manifest


def segments_for(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for chapter in manifest["chapters"]:
        for segment in chapter["segments"]:
            item = dict(segment)
            item["chapter_id"] = chapter["id"]
            item["chapter_title_ru"] = chapter["title_ru"]
            result.append(item)
    return result


def load_tts_receipt(audio: Path) -> dict[str, Any]:
    path = audio / "tts-receipt.json"
    if not path.is_file():
        fail(f"TTS receipt not found: {path}")
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"TTS receipt is not valid JSON: {exc}")
    if not isinstance(receipt, dict):
        fail("TTS receipt root must be an object")
    clips = receipt.get("clips")
    if not isinstance(clips, list):
        fail("TTS receipt has no clips array")
    return receipt


def verify_audio(manifest: dict[str, Any], audio: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    receipt = load_tts_receipt(audio)
    config_sha = receipt.get("config_sha256")
    if not isinstance(config_sha, str) or len(config_sha) != 64:
        fail("TTS receipt has no valid config_sha256")
    manifest_sha = receipt.get("manifest_sha256")
    if manifest_sha != sha256_text(canonical_json(manifest)):
        fail("TTS receipt manifest hash does not match the current manifest")
    by_shot: dict[str, dict[str, Any]] = {}
    for clip in receipt["clips"]:
        if not isinstance(clip, dict):
            continue
        shot_id = clip.get("shot_id")
        if isinstance(shot_id, str):
            by_shot[shot_id] = clip
    clips: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for segment in segments_for(manifest):
        shot_id = segment["shot_id"]
        clip = by_shot.get(shot_id)
        if not clip:
            missing.append(shot_id)
            continue
        if clip.get("text") != segment["narration_ru"]:
            fail(f"TTS receipt text mismatch for {shot_id}")
        if clip.get("text_sha256") != sha256_text(segment["narration_ru"]):
            fail(f"TTS receipt text hash mismatch for {shot_id}")
        wav_value = clip.get("wav_path")
        if not isinstance(wav_value, str) or not wav_value.strip():
            fail(f"TTS receipt has no WAV path for {shot_id}")
        audio_root = audio.resolve()
        wav = (audio / f"{shot_id}.wav").resolve()
        if not wav.is_relative_to(audio_root):
            fail(f"WAV path escapes audio directory for {shot_id}: {wav}")
        if not wav.is_file():
            fail(f"WAV missing for {shot_id}: {wav}")
        actual_sha = sha256_file(wav)
        if clip.get("sha256") != actual_sha:
            fail(f"WAV hash mismatch for {shot_id}")
        if not clip.get("ready"):
            fail(f"WAV is not marked ready in the receipt for {shot_id}")
        clips[shot_id] = {**clip, "wav_path": str(wav), "actual_sha256": actual_sha, "actual_size_bytes": wav.stat().st_size}
    if missing:
        fail(f"missing TTS clips: {missing}")
    return receipt, clips


def ffprobe_json(path: Path) -> dict[str, Any]:
    if not FFPROBE:
        fail("ffprobe not found in PATH")
    result = subprocess.run(
        [FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        fail(f"ffprobe failed for {path}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def screenshot_map(screens: Path, manifest: dict[str, Any]) -> dict[str, Path]:
    if not screens.is_dir():
        fail(f"screens directory not found: {screens}")
    mapping: dict[str, Path] = {}
    for segment in segments_for(manifest):
        shot_id = segment["shot_id"]
        candidate = screens / f"{shot_id}.png"
        if not candidate.is_file():
            fail(f"screenshot missing: {candidate}")
        if not PNG_RE.match(candidate.name):
            fail(f"screenshot filename is not lowercase PNG: {candidate}")
        if candidate.stat().st_size <= 0:
            fail(f"screenshot is empty: {candidate}")
        mapping[shot_id] = candidate
    return mapping


def canonical_public_dir() -> Path:
    script = Path(__file__).resolve()
    for candidate in (script.parent, *script.parents):
        public = candidate / "apps" / "web" / "public"
        if public.is_dir():
            return public.resolve()
    return (script.parent / "apps" / "web" / "public").resolve()


def check_output(output: Path, public_dir: Path | None, resume: bool) -> None:
    resolved = output.resolve()
    protected = {canonical_public_dir()}
    if public_dir is not None:
        protected.add(public_dir.resolve())
    for public in protected:
        if resolved == public:
            fail("output must not be the public directory")
        if resolved.is_relative_to(public):
            fail("output must not be inside the public directory")
        if public.is_relative_to(resolved):
            fail("output must not contain the public directory")
    if resolved.exists() and not resolved.is_dir():
        fail(f"output path exists but is not a directory: {resolved}")
    if resolved.is_dir() and any(resolved.iterdir()) and not resume:
        fail(f"output directory is not empty; pass exact verified --resume or choose a new output: {resolved}")


def srt_time(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, rem = divmod(milliseconds, 3600 * 1000)
    minutes, rem = divmod(rem, 60 * 1000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def vtt_time(seconds: float) -> str:
    return srt_time(seconds).replace(",", ".")


def wrap_cues(text: str, max_chars: int = 80, max_lines: int = 2) -> list[str]:
    words = text.split()
    lines: list[str] = []
    for word in words:
        candidate = f"{lines[-1]} {word}".strip() if lines else word
        if len(candidate) <= max_chars:
            if lines:
                lines[-1] = candidate
            else:
                lines.append(candidate)
        else:
            lines.append(word)
    cues: list[str] = []
    for offset in range(0, len(lines), max_lines):
        cues.append("\n".join(lines[offset:offset + max_lines]))
    return cues or [text]


def cue_entries(segments: list[dict[str, Any]], clips: dict[str, dict[str, Any]], start_seconds: float, paused: bool = False) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    cursor = start_seconds
    for segment in segments:
        clip = clips[segment["shot_id"]]
        duration = float(clip["duration_seconds"])
        cue_texts = wrap_cues(segment["narration_ru"])
        weights = [max(1, len(cue.split())) for cue in cue_texts]
        total_weight = sum(weights)
        cue_start = cursor
        for cue_index, cue_text in enumerate(cue_texts):
            cue_duration = duration * weights[cue_index] / total_weight
            cue_end = cue_start + cue_duration
            entries.append({
                "index": len(entries) + 1,
                "shot_id": segment["shot_id"],
                "chapter_id": segment["chapter_id"],
                "text": cue_text,
                "start": cue_start,
                "end": cue_end,
                "duration": cue_duration,
                "source_text_sha256": sha256_text(segment["narration_ru"]),
            })
            cue_start = cue_end
        cursor = cue_start
    return entries


def write_srt(entries: list[dict[str, Any]], path: Path) -> None:
    lines: list[str] = []
    for entry in entries:
        lines.append(str(entry["index"]))
        lines.append(f"{srt_time(entry['start'])} --> {srt_time(entry['end'])}")
        lines.append(entry["text"])
        lines.append("")
    atomic_write_text(path, "\n".join(lines))


def write_vtt(entries: list[dict[str, Any]], path: Path) -> None:
    lines: list[str] = ["WEBVTT", ""]
    for entry in entries:
        lines.append(str(entry["index"]))
        lines.append(f"{vtt_time(entry['start'])} --> {vtt_time(entry['end'])}")
        lines.append(entry["text"])
        lines.append("")
    atomic_write_text(path, "\n".join(lines))


def ffmpeg_concat(segments: list[dict[str, Any]], screens: dict[str, Path], clips: dict[str, dict[str, Any]], chapter_mp4: Path) -> None:
    if not FFMPEG:
        fail("ffmpeg not found in PATH")
    with tempfile.TemporaryDirectory(prefix="kamilya-guide-", dir=chapter_mp4.parent) as tmp_dir:
        tmp = Path(tmp_dir)
        concat_path = tmp / "concat.txt"
        concat_lines: list[str] = []
        for index, segment in enumerate(segments):
            shot_id = segment["shot_id"]
            screen = screens[shot_id]
            wav = Path(clips[shot_id]["wav_path"])
            clip_mp4 = tmp / f"{index:03d}-{shot_id}.mp4"
            duration = float(clips[shot_id]["duration_seconds"])
            cmd = [
                FFMPEG,
                "-y",
                "-loop", "1",
                "-framerate", "30",
                "-i", str(screen),
                "-i", str(wav),
                "-t", f"{duration:.3f}",
                "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=white",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-r", "30",
                "-c:a", "aac",
                "-b:a", "128k",
                "-shortest",
                str(clip_mp4),
            ]
            run_ffmpeg(cmd, f"render clip {shot_id}")
            concat_lines.append(f"file '{clip_mp4.name}'")
        atomic_write_text(concat_path, "\n".join(concat_lines) + "\n")
        result = subprocess.run(
            [
                FFMPEG,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_path),
                "-c", "copy",
                "-movflags", "+faststart",
                "-f", "mp4",
                str(chapter_mp4),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            fail(f"ffmpeg concat failed for {chapter_mp4}: {result.stderr.strip()}")


def run_ffmpeg(cmd: list[str], label: str) -> None:
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        fail(f"ffmpeg failed for {label}: {result.stderr.strip()}")


def poster(chapter_mp4: Path, screens: dict[str, Path], first_shot: str, path: Path) -> None:
    if not FFMPEG:
        fail("ffmpeg not found in PATH")
    result = subprocess.run(
        [FFMPEG, "-y", "-ss", "0.5", "-i", str(chapter_mp4), "-frames:v", "1", "-q:v", "3", str(path)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        fail(f"ffmpeg poster failed for {chapter_mp4}: {result.stderr.strip()}")


def media_metadata(path: Path) -> dict[str, Any]:
    info = ffprobe_json(path)
    streams = info.get("streams") or []
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if not video or not audio:
        fail(f"rendered file has no video/audio stream: {path}")
    duration = float(info.get("format", {}).get("duration") or 0)
    if duration <= 0:
        fail(f"rendered file has no duration: {path}")
    return {
        "duration_seconds": round(duration, 3),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "pix_fmt": video.get("pix_fmt"),
        "sample_rate": int(audio.get("sample_rate") or 0),
        "channels": int(audio.get("channels") or 0),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def html_escape(value: str) -> str:
    return html.escape(value, quote=True)


def csp_hash(value: str) -> str:
    return "sha256-" + base64.b64encode(hashlib.sha256(value.encode("utf-8")).digest()).decode("ascii")


def short_revision(value: str) -> str:
    value = value.strip()
    return value[:12] if re.fullmatch(r"[0-9a-fA-F]{40}", value) else value


def segment_starts(chapter_segments: list[dict[str, Any]], clips: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    cursor = 0.0
    result: list[dict[str, Any]] = []
    for index, segment in enumerate(chapter_segments, 1):
        duration = float(clips[segment["shot_id"]]["duration_seconds"])
        result.append({"index": index, "segment": segment, "start": cursor, "duration": duration})
        cursor += duration
    return result


def encoded_step_starts(chapter_mp4: Path, chapter_segments: list[dict[str, Any]], clips: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    nominal_starts = segment_starts(chapter_segments, clips)
    if not nominal_starts:
        return []
    if FFPROBE is None:
        fail("ffprobe is not available")
    probe = subprocess.run(
        [
            FFPROBE,
            "-v", "error",
            "-select_streams", "v:0",
            "-skip_frame", "nokey",
            "-show_entries", "frame=best_effort_timestamp_time,pts_time",
            "-of", "json",
            str(chapter_mp4),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        fail(f"ffprobe failed for {chapter_mp4}: {probe.stderr.strip()}")
    try:
        payload = json.loads(probe.stdout)
    except json.JSONDecodeError as exc:
        fail(f"ffprobe returned invalid JSON for {chapter_mp4}: {exc}")
    frames = payload.get("frames", [])
    keyframes: list[float] = []
    for frame in frames:
        raw = frame.get("best_effort_timestamp_time", frame.get("pts_time"))
        if raw is None:
            fail(f"ffprobe keyframe timestamp missing in {chapter_mp4}")
        try:
            timestamp = float(raw)
        except (TypeError, ValueError):
            fail(f"ffprobe keyframe timestamp is not numeric in {chapter_mp4}")
        if not math.isfinite(timestamp):
            fail(f"ffprobe keyframe timestamp is not finite in {chapter_mp4}")
        keyframes.append(timestamp)
    if not keyframes:
        fail(f"ffprobe found no keyframes in {chapter_mp4}")
    if any(right < left for left, right in zip(keyframes, keyframes[1:])):
        fail(f"ffprobe keyframes are not ordered in {chapter_mp4}")

    tolerance = (len(chapter_segments) / 30.0) + 0.05
    result: list[dict[str, Any]] = []
    used: set[float] = set()
    previous: float | None = None
    for item in nominal_starts:
        if item["index"] == 1:
            start = 0.0
        else:
            nominal = float(item["start"])
            candidates = [
                timestamp
                for timestamp in keyframes
                if timestamp not in used
                and nominal <= timestamp <= nominal + tolerance
            ]
            if len(candidates) != 1:
                fail(
                    f"segment {item['index']} in {chapter_mp4} has {len(candidates)} "
                    f"keyframe candidates in [{nominal:.6f}, {nominal + tolerance:.6f}]"
                )
            chosen = candidates[0]
            start = math.ceil(chosen * 1000.0) / 1000.0
            if previous is not None and start <= previous:
                fail(f"segment {item['index']} in {chapter_mp4} has nonmonotonic start {start:.3f}")
            used.add(chosen)
        result.append({**item, "start": start})
        previous = start
    return result


def media_href(name: str) -> str:
    return f"{MEDIA_FOLDER}/{name}"


def load_capture_marks(screens_dir: Path, screens: dict[str, Path], manifest: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    marks_by_shot: dict[str, list[dict[str, Any]]] = {}
    for segment in segments_for(manifest):
        shot_id = segment["shot_id"]
        receipt_path = next(
            (
                candidate
                for candidate in (screens_dir / f"{shot_id}.capture.json", screens_dir / f"{shot_id}.png.capture.json")
                if candidate.is_file()
            ),
            None,
        )
        if receipt_path is None:
            continue
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            fail(f"invalid capture receipt JSON: {receipt_path}")
        if not isinstance(receipt, dict):
            fail(f"capture receipt is not an object: {receipt_path}")
        if receipt.get("shot_id") != shot_id:
            fail(f"capture receipt shot_id mismatch: {receipt_path}")
        if receipt.get("visible_controls_verified") is not True:
            marks_by_shot[shot_id] = []
            continue
        png_sha256 = receipt.get("png_sha256")
        if png_sha256 and png_sha256 != sha256_file(screens[shot_id]):
            fail(f"capture receipt PNG hash mismatch: {receipt_path}")
        png_width, png_height = png_dimensions(screens[shot_id])
        viewport = receipt.get("viewport")
        if not isinstance(viewport, dict):
            fail(f"capture receipt has no viewport: {receipt_path}")
        viewport_width = float(viewport.get("width") or 0)
        viewport_height = float(viewport.get("height") or 0)
        if viewport_width <= 0 or viewport_height <= 0:
            fail(f"capture receipt has invalid viewport: {receipt_path}")
        scale_x = png_width / viewport_width
        scale_y = png_height / viewport_height
        controls = receipt.get("verified_controls")
        if not isinstance(controls, list):
            marks_by_shot[shot_id] = []
            continue
        shot_marks: list[dict[str, Any]] = []
        for control in controls:
            if not isinstance(control, dict):
                continue
            box = control.get("boundingBox")
            if not isinstance(box, dict):
                continue
            x = float(box.get("x") or 0)
            y = float(box.get("y") or 0)
            width = float(box.get("width") or 0)
            height = float(box.get("height") or 0)
            if width <= 0 or height <= 0:
                continue
            x_px = max(0.0, min(float(png_width), x * scale_x))
            y_px = max(0.0, min(float(png_height), y * scale_y))
            width_px = max(0.0, min(float(png_width) - x_px, width * scale_x))
            height_px = max(0.0, min(float(png_height) - y_px, height * scale_y))
            shot_marks.append({
                "rect": [x_px, y_px, width_px, height_px],
                "label": str(control.get("name") or control.get("selector") or "Проверенный элемент"),
            })
        marks_by_shot[shot_id] = shot_marks
    return marks_by_shot


def render_index(output: Path, manifest: dict[str, Any], chapters: list[dict[str, Any]], source_revision: str) -> None:
    cards: list[str] = []
    for chapter in chapters:
        chapter_id = chapter["id"]
        starts = encoded_step_starts(Path(chapter["media"]), chapter["segments"], chapter["clip_durations"])
        buttons = "".join(
            f'<button type="button" data-video="{html_escape(chapter_id)}" data-seek="{item["start"]:.3f}">'
            f'Шаг {item["index"]} · {item["start"]:.1f} с</button>'
            for item in starts
        )
        cards.append(
            f"<article class=\"chapter\" id=\"chapter-{html_escape(chapter_id)}\">"
            f"<h2>{html_escape(chapter['title_ru'])}</h2>"
            f"<video id=\"video-{html_escape(chapter_id)}\" class=\"player\" controls playsinline preload=\"metadata\" poster=\"{html_escape(media_href(chapter_id + '.jpg'))}\" width=\"1920\" height=\"1080\">"
            f"<source src=\"{html_escape(media_href(chapter_id + '.mp4'))}\" type=\"video/mp4\" />"
            f"<track kind=\"captions\" src=\"{html_escape(media_href(chapter_id + '.vtt'))}\" srclang=\"ru\" label=\"Русские субтитры\" default />"
            "</video>"
            f"<p><a href=\"{html_escape(media_href(chapter_id + '.mp4'))}\" download>Скачать MP4</a> · "
            f"<a href=\"{html_escape(media_href(chapter_id + '.vtt'))}\" download>Скачать VTT</a> · "
            f"<a href=\"{html_escape(media_href(chapter_id + '.srt'))}\" download>Скачать SRT</a></p>"
            f"<div class=\"steps\" aria-label=\"Шаги главы\">{buttons}</div>"
            "</article>"
        )
    nav = "".join(
        f"<li><a href=\"#chapter-{html_escape(chapter['id'])}\">{html_escape(chapter['title_ru'])}</a></li>"
        for chapter in chapters
    )
    style = """body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:0;background:#f7f7f7;color:#1a1a1a}main{max-width:1000px;margin:0 auto;padding:24px 16px 48px}h1{font-size:clamp(1.6rem,4vw,2.4rem);line-height:1.2}.notice{border-left:4px solid #b45309;background:#fff7ed;padding:12px 16px}nav ul{display:flex;flex-wrap:wrap;gap:8px 16px;padding-left:20px}.chapter{margin:32px 0;background:#fff;border:1px solid #ddd;padding:16px}.player{display:block;width:100%;max-width:100%;height:auto;background:#000}.steps{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.steps button{font:inherit;background:#eaf5fa;border:1px solid #97b4c3;border-radius:8px;padding:8px 10px;cursor:pointer}.steps button:focus-visible,a:focus-visible{outline:3px solid #a86400;outline-offset:3px}.meta{color:#555;font-size:.95rem}a{color:#0b57d0}"""
    script = """(()=>{const videos=[...document.querySelectorAll('video')];const seek=button=>{const video=document.getElementById(`video-${button.dataset.video}`);videos.forEach(item=>{if(item!==video)item.pause();});video.pause();video.currentTime=Number(button.dataset.seek);video.scrollIntoView({block:'nearest'});};document.querySelectorAll('button[data-seek]').forEach(button=>button.addEventListener('click',()=>seek(button)));videos.forEach(video=>video.addEventListener('play',()=>{videos.forEach(item=>{if(item!==video)item.pause();});}));})();"""
    csp = (
        "default-src 'none'; img-src 'self'; media-src 'self'; "
        f"style-src '{csp_hash(style)}'; script-src '{csp_hash(script)}'; "
        "connect-src 'none'; base-uri 'none'; form-action 'none'; object-src 'none'"
    )
    page = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="referrer" content="no-referrer" />
<meta http-equiv="Content-Security-Policy" content="{csp}" />
<title>{html_escape(manifest['title_ru'])}</title>
<style>{style}</style>
</head>
<body>
<main>
<h1>{html_escape(manifest['title_ru'])}</h1>
<p class="notice">{html_escape(manifest['recording_disclosure_ru'])}</p>
<p class="meta">Мужской синтетический голос Qwen3-TTS · Дата записи: {html_escape(chapters[0]['recorded_date'])} · Версия источника: {html_escape(short_revision(source_revision))}</p>
<nav aria-label="Содержание"><ul>{nav}</ul></nav>
{''.join(cards)}
<section id="08-results" class="chapter">
<h2>Результаты теста</h2>
<p>Бланк результата отдельного теста и скачивание PDF доступны после завершения теста. Настройку бланка выполняет администратор; методист проверяет три отдельных текста: вопрос, пояснение и итоговый результат.</p>
<p>Скачать результат теста · Скачать PDF</p>
</section><footer><p><a href="methodologist-text.html">Текстовая версия с иллюстрациями</a></p></footer>
</main>
<script>{script}</script>
</body>
</html>
"""
    atomic_write_text(output / "index.html", page)


def render_text(
    output: Path,
    manifest: dict[str, Any],
    chapters: list[dict[str, Any]],
    source_revision: str,
    screens: dict[str, Path],
    marks_by_shot: dict[str, list[dict[str, Any]]] | None = None,
) -> None:
    style = """body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:960px;margin:0 auto;padding:24px;line-height:1.6;color:#1a1a1a;background:#fff}button,input{font:inherit}button,a,input{outline-offset:4px}a{color:#0b57d0}.notice{border-left:4px solid #b45309;background:#fff7ed;padding:12px 16px}.meta{color:#555}.flow{background:#fff;border:1px solid #ddd;border-radius:12px;padding:24px;margin:24px 0}.image-frame{position:relative;margin:18px 0}.image-frame img{display:block;max-width:100%;height:auto;border:1px solid #ddd}.overlay{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}.overlay rect{fill:transparent;stroke:#b52d1e;stroke-width:2.5}.overlay g.active rect{fill:rgba(181,45,30,.12)}.overlay circle{fill:#b52d1e;stroke:white;stroke-width:2}.overlay text{fill:white;font:bold 17px Arial,sans-serif}.legend{list-style:none;padding:0}.legend li{margin:10px 0}.legend-button{width:100%;text-align:left;background:#eaf5fa;border:1px solid #97b4c3;border-radius:8px;padding:10px;cursor:pointer}.legend-button[aria-pressed="true"]{background:#fff0d6;border-color:#a86400}.number{display:inline-block;min-width:1.5em;font-weight:bold}.zoom-button{border:0;background:none;color:#0b57d0;padding:4px 0;text-decoration:underline;cursor:pointer}.progress-label{font-size:.95rem;color:#555}progress{display:block;width:100%;height:10px;margin:10px 0;accent-color:#075e74}.reset{border:0;background:none;color:#555;padding:3px 0;text-decoration:underline;cursor:pointer}.check{display:block;margin:16px 0;padding:10px;border:1px solid #ddd;border-radius:8px}.zoom{position:fixed;inset:0;background:rgba(16,24,32,.92);z-index:10;padding:16px;overflow:auto}.zoom[hidden]{display:none}.zoom-toolbar{display:flex;gap:12px;align-items:center;color:#fff;margin-bottom:12px}.zoom-content{max-height:calc(100vh - 52px);overflow:auto}.zoom-content .image-frame{width:max-content}.zoom-content img{display:block;max-width:none;width:auto;height:auto;background:#fff}.zoom-note{color:#e8eef2;font-size:.95rem}.nav a.done{font-weight:700}"""
    script = """(()=>{const checks=[...document.querySelectorAll('[data-complete]')];const progress=document.getElementById('pilot-progress');const status=document.getElementById('pilot-status');const zoom=document.getElementById('zoom');const zoomContent=document.getElementById('zoom-content');let previousFocus=null;const update=()=>{const n=checks.filter(el=>el.checked).length;progress.value=n;progress.textContent=`${n} из ${checks.length}`;status.textContent=`Готово ${n} из ${checks.length} этапов`;checks.forEach(el=>{const link=document.querySelector(`.nav a[href="#${el.dataset.complete}"]`);if(link)link.classList.toggle('done',el.checked);});};checks.forEach(el=>el.addEventListener('change',update));document.getElementById('reset-progress').addEventListener('click',()=>{checks.forEach(el=>{el.checked=false;});update();});document.querySelectorAll('[data-highlight]').forEach(button=>button.addEventListener('click',()=>{const spot=button.dataset.highlight;const screen=button.closest('.flow');const was=button.getAttribute('aria-pressed')==='true';screen.querySelectorAll('[data-highlight]').forEach(el=>el.setAttribute('aria-pressed','false'));screen.querySelectorAll('.overlay g').forEach(el=>el.classList.remove('active'));if(!was){button.setAttribute('aria-pressed','true');screen.querySelector(`[data-spot="${spot}"]`)?.classList.add('active');}}));const closeZoom=()=>{zoom.hidden=true;document.body.classList.remove('zoom-open');zoomContent.replaceChildren();if(previousFocus)previousFocus.focus();};document.querySelectorAll('[data-zoom]').forEach(button=>button.addEventListener('click',()=>{const frame=document.querySelector(`[data-image="${button.dataset.zoom}"]`);previousFocus=button;zoomContent.replaceChildren(frame.cloneNode(true));zoom.hidden=false;document.body.classList.add('zoom-open');document.getElementById('close-zoom').focus();}));document.getElementById('close-zoom').addEventListener('click',closeZoom);document.addEventListener('keydown',event=>{if(zoom.hidden)return;if(event.key==='Escape'){event.preventDefault();closeZoom();}if(event.key==='Tab'){event.preventDefault();document.getElementById('close-zoom').focus();}});document.getElementById('download-guide').addEventListener('click',()=>{const copy=document.documentElement.cloneNode(true);copy.querySelector('#zoom').hidden=true;copy.querySelector('#zoom-content').replaceChildren();copy.querySelector('body').classList.remove('zoom-open');const url=URL.createObjectURL(new Blob(['<!doctype html>'+copy.outerHTML],{type:'text/html;charset=utf-8'}));const link=document.createElement('a');link.href=url;link.download='Kamilya_Инструкция_методиста.html';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});update();})();"""
    parts: list[str] = []
    parts.append("<!doctype html>")
    parts.append('<html lang="ru">')
    csp = (
        "default-src 'none'; img-src data:; "
        f"style-src '{csp_hash(style)}'; script-src '{csp_hash(script)}'; "
        "connect-src 'none'; base-uri 'none'; form-action 'none'; object-src 'none'"
    )
    parts.append(f'<head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" /><meta name="referrer" content="no-referrer" /><meta http-equiv="Content-Security-Policy" content="{csp}" />')
    parts.append(f"<title>{html_escape(manifest['title_ru'])}</title>")
    parts.append(f"<style>{style}</style>")
    parts.append("</head><body>")
    parts.append('<div class="shell"><aside aria-label="Навигация по инструкции"><div class="brand">Kamilya LMS</div><div class="meta">Инструкция методиста</div><nav class="nav">')
    for chapter in chapters:
        parts.append(f'<a href="#{html_escape(chapter["id"])}">{html_escape(chapter["title_ru"])}</a>')
    parts.append('</nav>')
    parts.append('<label class="progress-label" for="pilot-progress" id="pilot-status">Готово 0 из 8 этапов</label>')
    parts.append('<progress id="pilot-progress" max="8" value="0">0 из 8</progress>')
    parts.append('<button class="reset" id="reset-progress" type="button">Сбросить мои отметки</button>')
    parts.append('<p class="meta">Отметки остаются только в открытой инструкции и сбрасываются после перезагрузки.</p>')
    parts.append('<button class="reset" id="download-guide" type="button">Скачать HTML для работы без интернета</button>')
    parts.append('</aside><main>')
    parts.append(f"<h1>{html_escape(manifest['title_ru'])}</h1>")
    parts.append(f'<p class="notice">{html_escape(manifest["recording_disclosure_ru"])}</p>')
    parts.append(f'<p class="meta">Мужской синтетический голос Qwen3-TTS · Дата записи: {html_escape(chapters[0]["recorded_date"])} · Версия источника: {html_escape(short_revision(source_revision))}</p>')
    step_number = 0
    for chapter in chapters:
        parts.append(f'<section class="flow" id="{html_escape(chapter["id"])}">')
        parts.append(f'<div class="flow-head"><h2>{html_escape(chapter["title_ru"])}</h2></div>')
        for segment in chapter["segments"]:
            step_number += 1
            shot_id = segment["shot_id"]
            shot_path = screens[shot_id]
            shot_data = base64.b64encode(shot_path.read_bytes()).decode("ascii")
            png_width, png_height = png_dimensions(shot_path)
            marks: list[dict[str, Any]] = []
            if marks_by_shot is not None and shot_id in marks_by_shot:
                marks = marks_by_shot[shot_id]
            else:
                raw_marks = segment.get("marks")
                if isinstance(raw_marks, list):
                    for idx, mark in enumerate(raw_marks):
                        if not isinstance(mark, list) or len(mark) != 4:
                            continue
                        control = segment["required_visible_controls"][min(idx, len(segment["required_visible_controls"]) - 1)]
                        x, y, w, h = (float(value) for value in mark)
                        marks.append({
                            "rect": [
                                x / 100.0 * png_width,
                                y / 100.0 * png_height,
                                w / 100.0 * png_width,
                                h / 100.0 * png_height,
                            ],
                            "label": control,
                        })
            overlay_parts: list[str] = []
            if marks:
                overlay_parts.append(f'<svg class="overlay" viewBox="0 0 {png_width} {png_height}" aria-hidden="true">')
                for idx, mark in enumerate(marks, 1):
                    x, y, w, h = mark["rect"]
                    cx, cy = max(17.0, x - 4.0), max(18.0, y - 8.0)
                    overlay_parts.append(f'<g data-spot="{html_escape(shot_id)}-{idx}"><rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" rx="5"/><circle cx="{cx:.2f}" cy="{cy:.2f}" r="15"/><text x="{cx:.2f}" y="{cy + 5:.2f}" text-anchor="middle">{idx}</text></g>')
                overlay_parts.append('</svg>')
            parts.append(f'<article id="{html_escape(shot_id)}">')
            parts.append(f"<h3>Шаг {step_number}</h3>")
            parts.append(f"<p>{html_escape(segment['narration_ru'])}</p>")
            parts.append(f"<p class=\"meta\">Что проверить: {html_escape(', '.join(segment['required_visible_controls']))}</p>")
            parts.append(f'<figure><div class="image-frame" data-image="{html_escape(shot_id)}"><img src="data:image/png;base64,{shot_data}" alt="Экран: {html_escape(segment["expected_result"])}" loading="lazy" />{"".join(overlay_parts)}</div><button type="button" class="zoom-button" data-zoom="{html_escape(shot_id)}">Увеличить скриншот</button><figcaption>{html_escape(segment["expected_result"])}</figcaption></figure>')
            for idx, mark in enumerate(marks, 1):
                parts.append(f'<button type="button" class="legend-button" data-highlight="{html_escape(shot_id)}-{idx}" aria-pressed="false"><span class="number">{idx}</span> {html_escape(mark["label"])}</button>')
            parts.append("</article>")
        if chapter["id"] == "04-tests":
            parts.append('<p id="quiz-approval-guidance">Если тест отмечен как «Требует проверки», после проверки вопросов, ключей и пояснений одобрите каждый тест кнопкой «Одобрить после проверки» до одобрения курса. Сохранение вопроса не одобряет тест или курс. Курс одобряется кнопкой «Одобрить курс».</p>')
        parts.append(f'<label class="check"><input type="checkbox" data-complete="{html_escape(chapter["id"])}" /><span>Проверено: {html_escape(chapter["title_ru"])}</span></label>')
        if chapter["id"] == "08-results":
            parts.append('<section>')
            parts.append('<p id="quiz-result-form-guidance">Бланк результата отдельного теста и скачивание PDF доступны после завершения теста. Настройку бланка выполняет администратор; методист проверяет три отдельных текста: вопрос, пояснение и итоговый результат.</p>')
            parts.append('<p>Скачать результат теста · Скачать PDF</p>')
            parts.append('<p id="course-completion-guidance">Слушатель нажимает «Завершить курс» только после прохождения уроков и обязательных тестов. Запись о завершении в журнале и сертификат отличаются от подписанного экземпляра. Методист не может завершить курс за сотрудника.</p>')
            parts.append('</section>')
        parts.append("</section>")
    parts.append("</main></div>")
    parts.append('<div class="zoom" id="zoom" role="dialog" aria-modal="true" aria-labelledby="zoom-title" hidden><div class="zoom-toolbar"><span id="zoom-title">Скриншот с отметками</span><button id="close-zoom" type="button">Закрыть · Esc</button></div><div class="zoom-content" id="zoom-content"></div><p class="zoom-note">На телефоне прокрутите большой снимок по горизонтали. Закройте его, чтобы вернуться к пояснениям.</p></div>')
    parts.append(f"<script>{script}</script>")
    parts.append("</body></html>")
    atomic_write_text(output / "text.html", "\n".join(parts))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render methodologist walkthrough video")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--screens", required=True, type=Path)
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--public-dir", type=Path, default=None)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)

    if not FFMPEG or not FFPROBE:
        fail("ffmpeg and ffprobe must be available in PATH")
    manifest = load_manifest(args.manifest)
    if not args.source_revision.strip():
        fail("--source-revision must not be empty")
    output = args.output.resolve()
    check_output(output, args.public_dir, args.resume)
    output.mkdir(parents=True, exist_ok=True)
    media_dir = output / MEDIA_FOLDER
    media_dir.mkdir(parents=True, exist_ok=True)
    screens = screenshot_map(args.screens.resolve(), manifest)
    marks_by_shot = load_capture_marks(args.screens.resolve(), screens, manifest)
    receipt, clips = verify_audio(manifest, args.audio.resolve())

    segments = segments_for(manifest)
    chapters: list[dict[str, Any]] = []
    recorded_date = time.strftime("%Y-%m-%d", time.gmtime())
    cursor = 0.0
    for chapter in manifest["chapters"]:
        chapter_segments = [segments[i] for i in range(len(segments)) if segments[i]["chapter_id"] == chapter["id"]]
        chapter_id = chapter["id"]
        chapter_mp4 = media_dir / f"{chapter_id}.mp4"
        chapter_jpg = media_dir / f"{chapter_id}.jpg"
        chapter_srt = media_dir / f"{chapter_id}.srt"
        chapter_vtt = media_dir / f"{chapter_id}.vtt"
        chapter_clips = {segment["shot_id"]: clips[segment["shot_id"]] for segment in chapter_segments}
        chapter_cues = cue_entries(chapter_segments, chapter_clips, 0.0)
        write_srt(chapter_cues, chapter_srt)
        write_vtt(chapter_cues, chapter_vtt)
        render_key = sha256_text(canonical_json({
            "segments": [
                {
                    "shot_id": segment["shot_id"],
                    "narration_sha256": sha256_text(segment["narration_ru"]),
                    "screen_sha256": sha256_file(screens[segment["shot_id"]]),
                    "audio_sha256": clips[segment["shot_id"]]["actual_sha256"],
                    "audio_duration": clips[segment["shot_id"]]["duration_seconds"],
                }
                for segment in chapter_segments
            ],
            "renderer": "ffmpeg_concat_v1",
            "paused": True,
        }))
        qa_hint = output / f".{chapter_id}.render-key.json"
        prior_hint: dict[str, Any] = {}
        if qa_hint.is_file():
            try:
                loaded_hint = json.loads(qa_hint.read_text(encoding="utf-8"))
                if isinstance(loaded_hint, dict):
                    prior_hint = loaded_hint
            except json.JSONDecodeError:
                prior_hint = {}
        reuse = (
            args.resume
            and chapter_mp4.is_file()
            and prior_hint.get("render_key") == render_key
            and prior_hint.get("sha256") == sha256_file(chapter_mp4)
        )
        if not reuse:
            staging_mp4 = media_dir / f".{chapter_id}.mp4.tmp"
            try:
                ffmpeg_concat(chapter_segments, screens, chapter_clips, staging_mp4)
                os.replace(staging_mp4, chapter_mp4)
            finally:
                if staging_mp4.exists():
                    staging_mp4.unlink()
        poster(chapter_mp4, screens, chapter_segments[0]["shot_id"], chapter_jpg)
        media = media_metadata(chapter_mp4)
        atomic_write_json(qa_hint, {"render_key": render_key, "duration_seconds": media["duration_seconds"], "sha256": media["sha256"]})
        if media["video_codec"] != "h264" or media["pix_fmt"] != "yuv420p":
            fail(f"rendered video is not h264/yuv420p: {chapter_mp4}")
        if media["audio_codec"] != "aac":
            fail(f"rendered audio is not AAC: {chapter_mp4}")
        if media["width"] != 1920 or media["height"] != 1080:
            fail(f"rendered video is not 1920x1080: {chapter_mp4}")
        for segment in chapter_segments:
            shot_png = screens[segment["shot_id"]]
            if segment["shot_id"] not in clips:
                fail(f"no clip for {segment['shot_id']}")
        chapters.append({
            "id": chapter_id,
            "title_ru": chapter["title_ru"],
            "segments": chapter_segments,
            "clip_durations": {segment["shot_id"]: {"duration_seconds": clips[segment["shot_id"]]["duration_seconds"]} for segment in chapter_segments},
            "media": str(chapter_mp4),
            "poster": str(chapter_jpg),
            "srt": str(chapter_srt),
            "vtt": str(chapter_vtt),
            "duration_seconds": media["duration_seconds"],
            "sha256": media["sha256"],
            "size_bytes": media["size_bytes"],
            "video_codec": media["video_codec"],
            "audio_codec": media["audio_codec"],
            "pix_fmt": media["pix_fmt"],
            "recorded_date": recorded_date,
            "cue_count": len(chapter_cues),
        })
        cursor += media["duration_seconds"] + 0.2

    assets: list[dict[str, Any]] = []
    videos: list[dict[str, Any]] = []
    for chapter in chapters:
        for suffix in (".mp4", ".jpg", ".srt", ".vtt"):
            asset_path = media_dir / f"{chapter['id']}{suffix}"
            assets.append({
                "name": asset_path.name,
                "bytes": asset_path.stat().st_size,
                "sha256": sha256_file(asset_path),
            })
        videos.append({
            "id": chapter["id"],
            "steps": len(chapter["segments"]),
            "duration_seconds": chapter["duration_seconds"],
            "sha256": chapter["sha256"],
        })
    media_manifest = {
        "schema_version": 1,
        "media_folder": MEDIA_FOLDER,
        "source_revision": args.source_revision,
        "source_manifest_sha256": sha256_file(args.manifest.resolve()),
        "videos": videos,
        "assets": assets,
    }
    atomic_write_json(media_dir / "manifest.json", media_manifest)
    for asset in assets:
        atomic_write_bytes(output / asset["name"], (media_dir / asset["name"]).read_bytes())
    render_index(output, manifest, chapters, args.source_revision)
    render_text(output, manifest, chapters, args.source_revision, screens, marks_by_shot)

    qa = {
        "schema_version": 1,
        "status": "UNREVIEWED",
        "source_revision": args.source_revision,
        "manifest_sha256": sha256_text(canonical_json(manifest)),
        "audio_receipt_config_sha256": receipt.get("config_sha256"),
        "chapter_count": len(chapters),
        "segment_count": len(segments),
        "media_folder": MEDIA_FOLDER,
        "media_manifest_sha256": sha256_file(media_dir / "manifest.json"),
        "verified_highlight_count": sum(len(marks) for marks in marks_by_shot.values()),
        "capture_receipt_count": len(marks_by_shot),
        "chapters": chapters,
        "text_html_sha256": sha256_file(output / "text.html"),
        "index_html_sha256": sha256_file(output / "index.html"),
        "all_shots_source_bound": True,
        "all_clips_source_bound": True,
        "renderer_is_approval": False,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    atomic_write_json(output / "qa.json", qa)
    print(json.dumps({"status": qa["status"], "chapters": len(chapters), "segments": len(segments), "output": str(output)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
