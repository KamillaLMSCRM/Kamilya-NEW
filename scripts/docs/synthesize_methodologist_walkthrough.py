#!/usr/bin/env python3
"""Synthesize the Russian methodologist walkthrough narration from the manifest.

This is an offline, CPU-only CLI. It never starts a web listener, never downloads
weights implicitly, and imports qwen_tts only after argument parsing so --help
works on a workstation without the TTS environment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
CHAPTERS = 8
ID_RE = __import__("re").compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
SHOT_RE = __import__("re").compile(r"^[a-z0-9][a-z0-9-]{2,95}$")
MANIFEST_REQUIRED = {"schema_version", "title_ru", "recording_disclosure_ru", "chapters"}
SEGMENT_REQUIRED = {
    "shot_id",
    "route",
    "required_visible_controls",
    "action_before_capture",
    "narration_ru",
    "expected_result",
    "capture_privacy_notes",
}
RECEIPT_NAME = "tts-receipt.json"


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


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"manifest not found: {path}")
    except json.JSONDecodeError as exc:
        fail(f"manifest is not valid JSON: {exc}")
    if not isinstance(manifest, dict):
        fail("manifest root must be an object")
    missing = MANIFEST_REQUIRED - set(manifest)
    if missing:
        fail(f"manifest missing keys: {sorted(missing)}")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        fail(f"unsupported manifest schema_version: {manifest.get('schema_version')!r}")
    if not isinstance(manifest.get("title_ru"), str) or not manifest["title_ru"].strip():
        fail("title_ru must be a non-empty string")
    if not isinstance(manifest.get("recording_disclosure_ru"), str) or not manifest["recording_disclosure_ru"].strip():
        fail("recording_disclosure_ru must be a non-empty string")
    chapters = manifest.get("chapters")
    if not isinstance(chapters, list) or len(chapters) != CHAPTERS:
        fail(f"manifest must contain exactly {CHAPTERS} chapters")
    seen_chapters: set[str] = set()
    seen_shots: set[str] = set()
    total_segments = 0
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
            missing = SEGMENT_REQUIRED - set(segment)
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
            total_segments += 1
    if total_segments < CHAPTERS:
        fail("manifest has fewer segments than chapters")
    return manifest


def segment_list(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for chapter in manifest["chapters"]:
        for segment in chapter["segments"]:
            item = dict(segment)
            item["chapter_id"] = chapter["id"]
            item["chapter_title_ru"] = chapter["title_ru"]
            result.append(item)
    return result


def package_version(name: str) -> str | None:
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:
        return None


def model_fingerprint(path: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    total = 0
    for item in sorted((candidate for candidate in path.rglob("*") if candidate.is_file()), key=lambda candidate: candidate.relative_to(path).as_posix()):
        rel = item.relative_to(path).as_posix()
        size = item.stat().st_size
        file_sha = sha256_file(item)
        total += size
        files.append({"path": rel, "size_bytes": size, "sha256": file_sha})
        digest.update(rel.encode("utf-8") + b"\0" + str(size).encode("ascii") + b"\0" + file_sha.encode("ascii") + b"\n")
    return {"sha256": digest.hexdigest(), "file_count": len(files), "size_bytes": total, "files": files}


def synthesis_config(args: argparse.Namespace, manifest: dict[str, Any]) -> dict[str, Any]:
    model = args.model.resolve()
    reference_audio = args.reference_audio.resolve()
    reference_text = args.reference_text.strip()
    if not model.is_dir():
        fail(f"model directory not found: {model}")
    if not reference_audio.is_file():
        fail(f"reference audio not found: {reference_audio}")
    if not reference_text:
        fail("reference text must not be empty")
    fingerprint = model_fingerprint(model)
    return {
        "schema_version": 1,
        "engine": "qwen-tts",
        "device": "cpu",
        "dtype": "float32",
        "attn_implementation": "sdpa",
        "threads": 4,
        "language": "Russian",
        "non_streaming_mode": True,
        "do_sample": False,
        "max_new_tokens": int(args.max_new_tokens),
        "model_path": str(model),
        "model_sha256": fingerprint["sha256"],
        "model_file_count": fingerprint["file_count"],
        "model_size_bytes": fingerprint["size_bytes"],
        "model_files": fingerprint["files"],
        "reference_audio_path": str(reference_audio),
        "reference_audio_sha256": sha256_file(reference_audio),
        "reference_text": reference_text,
        "reference_text_sha256": sha256_text(reference_text),
        "qwen_tts_package_version": package_version("qwen-tts"),
        "soundfile_package_version": package_version("soundfile"),
        "torch_package_version": package_version("torch"),
    }


def receipt_key(config: dict[str, Any], segment: dict[str, Any]) -> dict[str, Any]:
    return {
        "config_sha256": sha256_text(canonical_json(config)),
        "text_sha256": sha256_text(segment["narration_ru"]),
        "text": segment["narration_ru"],
        "shot_id": segment["shot_id"],
        "chapter_id": segment["chapter_id"],
    }


def read_receipt(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def validate_wav(path: Path) -> dict[str, Any]:
    import wave
    import struct

    try:
        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            frame_rate = wav.getframerate()
            frames = wav.getnframes()
            if channels < 1 or sample_width not in (1, 2, 3, 4) or frame_rate <= 0 or frames <= 0:
                fail(f"invalid WAV header: {path}")
            duration = frames / float(frame_rate)
            raw = wav.readframes(frames)
            if not raw:
                fail(f"empty WAV audio: {path}")
            if sample_width == 1:
                values = [byte - 128 for byte in raw]
            elif sample_width == 2:
                values = list(struct.unpack("<%dh" % (len(raw) // 2), raw))
            elif sample_width == 3:
                values = [int.from_bytes(raw[offset:offset + 3], "little", signed=True) for offset in range(0, len(raw) - 2, 3)]
            else:
                values = list(struct.unpack("<%di" % (len(raw) // 4), raw))
            if not values:
                fail(f"WAV has no decodable samples: {path}")
            if not all(math.isfinite(value) for value in values):
                fail(f"WAV contains non-finite PCM values: {path}")
            abs_values = [abs(value) for value in values]
            peak = max(abs_values)
            if peak == 0:
                fail(f"WAV is entirely silent: {path}")
            threshold = max(1, peak // 100)
            active = sum(1 for value in abs_values if value > threshold)
            active_ratio = active / len(abs_values)
            if active_ratio < 0.01:
                fail(f"WAV has too little speech activity: {path}")
            if duration < 0.3:
                fail(f"WAV duration is implausibly short: {path}")
            rms = math.sqrt(sum(value * value for value in values) / len(values))
            full_scale = float(2 ** (sample_width * 8 - 1) - 1)
    except wave.Error as exc:
        fail(f"cannot read WAV {path}: {exc}")
    return {
        "channels": channels,
        "sample_width_bytes": sample_width,
        "sample_rate": frame_rate,
        "frames": frames,
        "duration_seconds": round(duration, 3),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "peak_amplitude": peak,
        "peak_ratio": round(peak / full_scale, 6),
        "rms_amplitude": round(rms, 3),
        "rms_ratio": round(rms / full_scale, 6),
        "active_sample_ratio": round(active_ratio, 6),
        "finite_pcm_measured": True,
        "speech_activity_measured": True,
        "silence_measured_by_active_ratio": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synthesize methodologist walkthrough narration")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--reference-audio", required=True, type=Path)
    parser.add_argument("--reference-text", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--resume", action="store_true", help="reuse WAVs with exact matching receipts")
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    manifest_sha = sha256_text(canonical_json(manifest))
    config = synthesis_config(args, manifest)
    segments = segment_list(manifest)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    receipt_path = output / RECEIPT_NAME
    existing_receipt = read_receipt(receipt_path)
    if existing_receipt is not None and existing_receipt.get("config_sha256") != sha256_text(canonical_json(config)):
        if args.resume:
            print("NOTE: immutable synthesis configuration changed; existing receipt will be replaced and WAVs regenerated.", file=sys.stderr)
        existing_receipt = None

    try:
        import torch  # noqa: F401
        import soundfile as sf
        from qwen_tts import Qwen3TTSModel
    except Exception as exc:
        fail(f"TTS imports failed (run inside the Qwen environment): {exc}")

    import torch

    torch.set_num_threads(4)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass

    print("STAGE loading model", flush=True)
    started = time.monotonic()
    model = Qwen3TTSModel.from_pretrained(
        str(args.model.resolve()),
        device_map="cpu",
        dtype=torch.float32,
        attn_implementation="sdpa",
    )
    loaded = time.monotonic()
    print(f"STAGE model loaded in {loaded - started:.2f}s", flush=True)

    reference_text = args.reference_text.strip()
    voice = model.create_voice_clone_prompt(
        ref_audio=str(args.reference_audio.resolve()),
        ref_text=reference_text,
        x_vector_only_mode=False,
    )
    print("STAGE voice ready", flush=True)

    clips: list[dict[str, Any]] = []
    completed_by_shot: dict[str, dict[str, Any]] = {}
    if args.resume and existing_receipt is not None:
        for prior in existing_receipt.get("clips", []):
            if isinstance(prior, dict) and isinstance(prior.get("shot_id"), str):
                completed_by_shot[prior["shot_id"]] = prior

    def persist_completed() -> None:
        partial = {
            "schema_version": 1,
            "status": "IN_PROGRESS",
            "config": config,
            "config_sha256": sha256_text(canonical_json(config)),
            "manifest_sha256": manifest_sha,
            "clip_count": len(clips),
            "clips": clips,
            "gpu_used": False,
            "network_used": False,
            "listener_started": False,
        }
        atomic_write_json(receipt_path, partial)

    for index, segment in enumerate(segments):
        shot_id = segment["shot_id"]
        wav_path = output / f"{shot_id}.wav"
        key = receipt_key(config, segment)
        reused = False
        if args.resume and wav_path.is_file():
            prior = completed_by_shot.get(shot_id)
            if prior and prior.get("config_sha256") == key["config_sha256"] and prior.get("text_sha256") == key["text_sha256"] and prior.get("sha256") == sha256_file(wav_path):
                reused = True
                clip = dict(prior)
                print(f"REUSE {shot_id}", flush=True)
        if not reused:
            print(f"SYNTH {index + 1}/{len(segments)} {shot_id}", flush=True)
            clip_started = time.monotonic()
            wavs, sample_rate = model.generate_voice_clone(
                text=segment["narration_ru"],
                language="Russian",
                voice_clone_prompt=voice,
                non_streaming_mode=True,
                max_new_tokens=int(args.max_new_tokens),
                do_sample=False,
            )
            if not wavs or len(wavs[0]) == 0:
                fail(f"empty synthesis result for {shot_id}")
            tmp = output / f".{shot_id}.wav.tmp"
            sf.write(str(tmp), wavs[0], sample_rate, format="WAV")
            os.replace(tmp, wav_path)
            info = validate_wav(wav_path)
            clip = {
                **key,
                "wav_path": str(wav_path),
                "sha256": info["sha256"],
                "size_bytes": info["size_bytes"],
                "duration_seconds": info["duration_seconds"],
                "sample_rate": info["sample_rate"],
                "channels": info["channels"],
                "sample_width_bytes": info["sample_width_bytes"],
                "frames": info["frames"],
                "peak_amplitude": info["peak_amplitude"],
                "active_sample_ratio": info["active_sample_ratio"],
                "synthesis_seconds": round(time.monotonic() - clip_started, 3),
                "ready": True,
            }
            print(f"READY {shot_id} {clip['duration_seconds']:.2f}s", flush=True)
        clips.append(clip)
        persist_completed()

    result = {
        "schema_version": 1,
        "status": "SYNTHESIZED_FOR_REVIEW",
        "config": config,
        "config_sha256": sha256_text(canonical_json(config)),
        "manifest_sha256": manifest_sha,
        "clip_count": len(clips),
        "clips": clips,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "load_seconds": round(loaded - started, 3),
        "gpu_used": False,
        "network_used": False,
        "listener_started": False,
    }
    atomic_write_json(receipt_path, result)
    atomic_write_json(output / "synthesis-result.json", result)
    print(json.dumps({"status": result["status"], "clip_count": result["clip_count"], "receipt": str(receipt_path)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
