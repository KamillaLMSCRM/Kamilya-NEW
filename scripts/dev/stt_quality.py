"""Bounded offline decoder-policy experiment on the existing licensed pilot corpus."""

from __future__ import annotations

import argparse
from importlib.metadata import version
import json
import math
from pathlib import Path
import time

from stt_pilot import (
    CONFIGS,
    DECODE_PARAMETERS,
    aggregate_rows,
    deadline,
    edit_distance,
    file_sha256,
    normalize,
    validate_decoded_duration,
    validate_manifest,
    validate_model,
)

PROFILES = {
    "hinted-baseline": dict(DECODE_PARAMETERS),
    "auto-segment-30s": dict(DECODE_PARAMETERS, multilingual=True, chunk_length=30),
    "auto-segment-15s": dict(DECODE_PARAMETERS, multilingual=True, chunk_length=15),
}
STATUS = "EXPLORATORY_DECODER_POLICY_NOT_PRODUCT_ACCEPTANCE"
RUNTIME = {
    "faster-whisper": "1.2.1",
    "ctranslate2": "4.8.2",
    "av": "16.0.1",
    "huggingface-hub": "1.33.0",
}


def metric_groups(rows: list[dict]) -> dict:
    groups = aggregate_rows(rows)
    if set(groups) - {*CONFIGS, "mixed-splice"}:
        raise ValueError("Unexpected metric language")
    artificial = groups.pop("mixed-splice", None)
    return dict(
        languages=groups,
        artificial_splice=None
        if artificial is None
        else dict(
            kind="ARTIFICIAL_SPLICE_DIAGNOSTIC_ONLY",
            acceptance_eligible=False,
            metrics=artificial,
        ),
    )


def typed_report(report: dict) -> dict:
    """Audit the preserved first-run format without overwriting its raw evidence."""
    if "metric_schema" in report:
        return report
    if report["languages"] != aggregate_rows(report["clips"]):
        raise ValueError("Legacy raw aggregates mismatch")
    return dict(report, metric_schema=2, **metric_groups(report["clips"]))


def decode_policy(profile: str, language: str) -> dict:
    """Policy uses only profile/input language label, never reference words."""
    if profile not in PROFILES or language not in {*CONFIGS, "mixed-splice"}:
        raise ValueError("Unknown bounded decoder policy")
    hint = language if profile == "hinted-baseline" and language in CONFIGS else None
    return dict(PROFILES[profile], language=hint, task="transcribe")


def load_inputs(root: Path) -> tuple[dict, dict]:
    manifest = root / "smoke" / "manifest.json"
    if manifest.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("Oversized manifest")
    corpus = json.loads(manifest.read_text(encoding="utf-8"))
    validate_manifest(root, corpus)
    source = json.loads(
        (root / "models/large-v3/pilot-source.json").read_text(encoding="utf-8")
    )
    validate_model("large-v3", source, root / "models/large-v3")
    if source["dataset_revision"] != corpus["source"]["dataset_revision"]:
        raise ValueError("Model/corpus revision mismatch")
    return corpus, source


def verify_report(root: Path, report: dict, corpus: dict, source: dict) -> None:
    profile = report["profile"]
    if (
        profile not in PROFILES
        or report["status"] != STATUS
        or report["metric_schema"] != 2
        or report["model_name"] != "large-v3"
        or report["runtime_versions"] != RUNTIME
        or report["decode_parameters"] != PROFILES[profile]
        or report["source"] != source
        or report["corpus_manifest_sha256"] != file_sha256(root / "smoke/manifest.json")
        or report["input_sha256"]
        != {clip["file"]: clip["audio_sha256"] for clip in corpus["clips"]}
        or report["device"] != "cpu"
        or report["compute_type"] != "int8"
        or report["cpu_threads"] != 4
        or report["concurrency"] != 1
        or report["natural_mixed_verified"] is not False
        or report["command_fields_verified"] is not False
        or len(report["clips"]) != len(corpus["clips"])
    ):
        raise ValueError("Decoder experiment binding mismatch")
    for row, clip in zip(report["clips"], corpus["clips"], strict=True):
        if (
            row["file"] != clip["file"]
            or row["language"] != clip["language"]
            or row["reference"] != clip["reference"]
            or row["effective_policy"] != decode_policy(profile, clip["language"])
        ):
            raise ValueError("Decoder row binding mismatch")
        validate_decoded_duration(clip, row["duration_seconds"])
        reference, hypothesis = (
            normalize(clip["reference"]),
            normalize(row["transcript"]),
        )
        latency = row["latency_seconds"]
        if (
            row["reference_words"] != len(reference)
            or row["errors"] != edit_distance(reference, hypothesis)
            or not math.isfinite(latency)
            or latency <= 0
            or not math.isclose(
                row["real_time_factor"], latency / row["duration_seconds"], rel_tol=1e-9
            )
        ):
            raise ValueError("Decoder metric mismatch")
    if {
        "languages": report["languages"],
        "artificial_splice": report["artificial_splice"],
    } != metric_groups(report["clips"]):
        raise ValueError("Decoder aggregates mismatch")


def benchmark(root: Path, profile: str) -> dict:
    import resource
    from faster_whisper import WhisperModel

    corpus, source = load_inputs(root)
    target = root / "quality" / f"decoder-{profile}.json"
    if target.exists():
        raise ValueError("Preserve earlier result; refusing to overwrite experiment")
    started = time.perf_counter()
    model = WhisperModel(
        str(root / "models/large-v3"),
        device="cpu",
        compute_type="int8",
        cpu_threads=4,
        num_workers=1,
        local_files_only=True,
    )
    load_seconds = time.perf_counter() - started
    rows = []
    for clip in corpus["clips"]:
        policy = decode_policy(profile, clip["language"])
        started = time.perf_counter()
        segments, info = model.transcribe(str(root / "smoke" / clip["file"]), **policy)
        validate_decoded_duration(clip, info.duration)
        text = " ".join(segment.text for segment in segments).strip()
        elapsed = time.perf_counter() - started
        reference = normalize(clip["reference"])
        rows.append(
            dict(
                file=clip["file"],
                language=clip["language"],
                reference=clip["reference"],
                transcript=text,
                duration_seconds=info.duration,
                latency_seconds=elapsed,
                real_time_factor=elapsed / info.duration,
                reference_words=len(reference),
                errors=edit_distance(reference, normalize(text)),
                detected_language=info.language,
                effective_policy=policy,
            )
        )
        print(
            json.dumps(
                dict(profile=profile, completed=len(rows), total=len(corpus["clips"]))
            ),
            flush=True,
        )
    result = dict(
        status=STATUS,
        metric_schema=2,
        profile=profile,
        model_name="large-v3",
        source=source,
        device="cpu",
        compute_type="int8",
        cpu_threads=4,
        concurrency=1,
        decode_parameters=PROFILES[profile],
        runtime_versions={
            name: version(name)
            for name in ("faster-whisper", "ctranslate2", "av", "huggingface-hub")
        },
        corpus_manifest_sha256=file_sha256(root / "smoke/manifest.json"),
        input_sha256={clip["file"]: clip["audio_sha256"] for clip in corpus["clips"]},
        model_load_seconds=load_seconds,
        first_clip_seconds=rows[0]["latency_seconds"],
        peak_process_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        natural_mixed_verified=False,
        command_fields_verified=False,
        clips=rows,
        **metric_groups(rows),
    )
    verify_report(root, result, corpus, source)
    target.parent.mkdir(exist_ok=True)
    target.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        key: value
        for key, value in result.items()
        if key not in {"clips", "source", "input_sha256"}
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["benchmark", "verify"])
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("/home/superuser/projects/kamilya-stt-pilot-20261003"),
    )
    parser.add_argument("--profile", choices=list(PROFILES), required=True)
    args = parser.parse_args()
    with deadline(600):
        if args.action == "benchmark":
            summary = benchmark(args.root, args.profile)
        else:
            corpus, source = load_inputs(args.root)
            file = args.root / "quality" / f"decoder-{args.profile}.json"
            raw = json.loads(file.read_text(encoding="utf-8"))
            report = typed_report(raw)
            verify_report(args.root, report, corpus, source)
            summary = dict(
                status="DECODER_BINDING_PASS",
                profile=args.profile,
                report_sha256=file_sha256(file),
                raw_metric_schema=raw.get("metric_schema", 1),
                metric_schema=2,
                **metric_groups(report["clips"]),
            )
            (args.root / "quality" / f"audit-{args.profile}.json").write_text(
                json.dumps(summary, indent=2), encoding="utf-8"
            )
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
