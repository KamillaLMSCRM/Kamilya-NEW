"""Isolated, public-corpus STT benchmark; no LMS credentials or business effects."""

from __future__ import annotations

import argparse
import csv
from contextlib import contextmanager
import hashlib
import io
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import re
import statistics
import tarfile
import time
import unicodedata
import wave
from urllib.parse import urlparse
from urllib.request import urlopen


MODEL = "Systran/faster-whisper-small"
MODELS = {"small": MODEL, "large-v3": "Systran/faster-whisper-large-v3"}
DATASET = "google/fleurs"
CONFIGS = {"ru": "ru_ru", "kk": "kk_kz"}
MAX_DOWNLOAD = 8 * 1024 * 1024
LANGUAGE_POLICY = "reference-language-hint-for-RU-KK;automatic-for-splice"
DECODE_PARAMETERS = dict(
    beam_size=5, condition_on_previous_text=False, vad_filter=False
)


@contextmanager
def deadline(seconds: int):
    """Linux CLI watchdog; never silently run unbounded on another platform."""
    import signal

    if not hasattr(signal, "SIGALRM"):
        raise RuntimeError("Benchmark requires a Linux timeout watchdog")

    def expired(signum, frame):
        raise TimeoutError("Pilot execution deadline exceeded")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def public_get(url: str, limit: int = MAX_DOWNLOAD) -> bytes:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.hostname
        not in {"huggingface.co", "datasets-server.huggingface.co", "pypi.org"}
    ):
        raise ValueError("Unexpected public source")
    with urlopen(url, timeout=45) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Public source exceeds size limit")
    return data


def metadata(model_name: str = "small") -> dict:
    result = {}
    for name in ("faster-whisper", "ctranslate2"):
        data = json.loads(public_get(f"https://pypi.org/pypi/{name}/json"))
        result[name] = data["info"]["version"]
    model_id = MODELS[model_name]
    model = json.loads(public_get(f"https://huggingface.co/api/models/{model_id}"))
    dataset = json.loads(public_get(f"https://huggingface.co/api/datasets/{DATASET}"))
    result.update(
        model=model_id,
        model_revision=model["sha"],
        model_license=model.get("cardData", {}).get("license"),
        dataset=DATASET,
        dataset_revision=dataset["sha"],
        dataset_license=dataset.get("cardData", {}).get("license"),
    )
    return result


def normalize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).casefold().replace("ё", "е")
    return re.findall(r"\w+", text, flags=re.UNICODE)


def edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for i, word in enumerate(reference, 1):
        current = [i]
        for j, other in enumerate(hypothesis, 1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (word != other),
                )
            )
        previous = current
    return previous[-1]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def select_clips(tsv: str, count: int) -> list[dict]:
    """First distinct test sentences lasting 15–30 s, chosen before inference."""
    records, seen = [], set()
    for row in csv.reader(io.StringIO(tsv), delimiter="\t"):
        if len(row) != 7 or not re.fullmatch(r"\d+\.wav", row[1]):
            raise ValueError("Unexpected FLEURS metadata")
        samples = int(row[5])
        key = tuple(normalize(row[2]))
        if not key or key in seen or not 15 * 16000 <= samples <= 30 * 16000:
            continue
        seen.add(key)
        records.append(
            dict(
                sample_id=row[0],
                source_file=row[1],
                reference=row[2],
                num_samples=samples,
            )
        )
        if len(records) == count:
            return records
    raise ValueError("Not enough eligible FLEURS clips")


def selected_audio(archive: Path, selected: list[dict]) -> dict[str, bytes]:
    """Read only selected WAV bytes; never extract archive paths to disk."""
    wanted = {f"test/{row['source_file']}": row["source_file"] for row in selected}
    found = {}
    with tarfile.open(archive, "r:gz") as source:
        for member in source:
            if member.name not in wanted:
                continue
            name = wanted[member.name]
            if (
                name in found
                or not member.isfile()
                or not 0 < member.size <= MAX_DOWNLOAD
            ):
                raise ValueError("Unexpected corpus member")
            stream = source.extractfile(member)
            if stream is None:
                raise ValueError("Missing corpus member")
            with stream:
                data = stream.read(MAX_DOWNLOAD + 1)
            if len(data) != member.size:
                raise ValueError("Corpus size mismatch")
            found[name] = data
    if set(found) != set(wanted.values()):
        raise ValueError("Incomplete corpus archive")
    return found


def prepare(root: Path, count: int, model_name: str = "small") -> None:
    from huggingface_hub import (
        get_hf_file_metadata,
        hf_hub_download,
        hf_hub_url,
        snapshot_download,
    )

    info = metadata(model_name)
    dataset_license = info["dataset_license"]
    if info["model_license"] != "mit" or dataset_license not in (
        "cc-by-4.0",
        ["cc-by-4.0"],
    ):
        raise ValueError("License verification failed")
    (root / "models").mkdir(exist_ok=True)
    (root / "smoke").mkdir(exist_ok=True)
    (root / "metadata.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    snapshot_download(
        info["model"],
        revision=info["model_revision"],
        local_dir=root / "models" / model_name,
        token=False,
        allow_patterns=[
            "model.bin",
            "config.json",
            "tokenizer.json",
            "vocabulary.*",
            "preprocessor_config.json",
            "README.md",
        ],
    )
    info["artifact_sha256"] = {
        file.name: file_sha256(file)
        for file in (root / "models" / model_name).iterdir()
        if file.is_file() and file.name != "pilot-source.json"
    }
    info["weights_sha256"] = info["artifact_sha256"]["model.bin"]
    (root / "models" / model_name / "pilot-source.json").write_text(
        json.dumps(info, indent=2), encoding="utf-8"
    )
    records = []
    for language, config in CONFIGS.items():
        revision = info["dataset_revision"]
        source = f"data/{config}/test.tsv"
        tsv = public_get(
            hf_hub_url(DATASET, source, repo_type="dataset", revision=revision)
        ).decode("utf-8")
        selected = select_clips(tsv, count)
        source = f"data/{config}/audio/test.tar.gz"
        url = hf_hub_url(DATASET, source, repo_type="dataset", revision=revision)
        file_info = get_hf_file_metadata(url, token=False)
        if file_info.size is None or not 0 < file_info.size <= 700 * 1024 * 1024:
            raise ValueError("Corpus archive exceeds size limit")
        downloaded = Path(
            hf_hub_download(
                DATASET, source, repo_type="dataset", revision=revision, token=False
            )
        )
        if downloaded.stat().st_size != file_info.size:
            raise ValueError("Corpus archive size mismatch")
        audio_files = selected_audio(downloaded, selected)
        for index, row in enumerate(selected):
            audio = audio_files[row["source_file"]]
            filename = f"{language}-{index}.wav"
            (root / "smoke" / filename).write_bytes(audio)
            records.append(
                dict(
                    file=filename,
                    language=language,
                    source_path=source,
                    archive_member=f"test/{row['source_file']}",
                    sample_id=row["sample_id"],
                    reference=row["reference"],
                    audio_sha256=hashlib.sha256(audio).hexdigest(),
                    num_samples=row["num_samples"],
                )
            )
    # Controlled splice of licensed human speech, not a natural code-switching test.
    import numpy as np
    from faster_whisper.audio import decode_audio

    pair = [
        next(row for row in records if row["language"] == language)
        for language in CONFIGS
    ]
    samples = np.concatenate(
        [decode_audio(str(root / "smoke" / row["file"])) for row in pair]
    )
    mixed_file = root / "smoke" / "mixed-splice.wav"
    with wave.open(str(mixed_file), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    records.append(
        dict(
            file=mixed_file.name,
            language="mixed-splice",
            reference=" ".join(row["reference"] for row in pair),
            audio_sha256=file_sha256(mixed_file),
            num_samples=len(samples),
            derived_from=[row["file"] for row in pair],
        )
    )
    (root / "smoke" / "manifest.json").write_text(
        json.dumps(
            dict(
                source=info,
                license="CC-BY-4.0",
                attribution="Google FLEURS",
                url="https://huggingface.co/datasets/google/fleurs",
                clips=records,
            ),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(dict(status="PREPARED", clips=len(records), **info)))


def validate_manifest(root: Path, corpus: dict) -> None:
    if corpus["source"]["dataset"] != DATASET or corpus["license"] != "CC-BY-4.0":
        raise ValueError("Unexpected corpus source")
    clips = corpus["clips"]
    if not 2 <= len(clips) <= 41:
        raise ValueError("Unexpected corpus count")
    seen, counts = set(), {"ru": 0, "kk": 0, "mixed-splice": 0}
    base = (root / "smoke").resolve()
    for clip in clips:
        name, language = clip["file"], clip["language"]
        if (
            not re.fullmatch(r"(?:ru|kk)-\d+\.wav|mixed-splice\.wav", name)
            or name in seen
        ):
            raise ValueError("Unexpected clip path")
        if language not in counts or (
            language != "mixed-splice" and not name.startswith(language + "-")
        ):
            raise ValueError("Unexpected clip language")
        if language == "mixed-splice" and name != "mixed-splice.wav":
            raise ValueError("Unexpected splice path")
        seen.add(name)
        counts[language] += 1
        if not normalize(clip["reference"]) or len(clip["reference"]) > 16000:
            raise ValueError("Unexpected reference text")
        duration = clip["num_samples"] / 16000
        if not (
            15 <= duration <= 30 if language != "mixed-splice" else 30 <= duration <= 60
        ):
            raise ValueError("Unexpected clip duration")
        file = base / name
        if file.resolve().parent != base or not 0 < file.stat().st_size <= MAX_DOWNLOAD:
            raise ValueError("Unexpected clip file size or location")
        if file_sha256(file) != clip["audio_sha256"]:
            raise ValueError("Corpus hash mismatch")
    if not 1 <= counts["ru"] == counts["kk"] <= 20 or counts["mixed-splice"] > 1:
        raise ValueError("Unexpected corpus language counts")


def validate_model(model_name: str, source: dict, model_dir: Path) -> None:
    if source["model"] != MODELS[model_name] or source["model_license"] != "mit":
        raise ValueError("Unexpected model identity")
    hashes = source["artifact_sha256"]
    if not {"model.bin", "config.json", "tokenizer.json"} <= set(hashes):
        raise ValueError("Incomplete model artifacts")
    for name, expected in hashes.items():
        if Path(name).name != name or file_sha256(model_dir / name) != expected:
            raise ValueError("Model artifact hash mismatch")


def validate_decoded_duration(clip: dict, duration: float) -> None:
    lower, upper = (30, 60) if clip["language"] == "mixed-splice" else (15, 30)
    if (
        not lower <= duration <= upper
        or abs(duration - clip["num_samples"] / 16000) > 0.01
    ):
        raise ValueError("Decoded clip duration differs from bounded corpus metadata")


def aggregate_rows(rows: list[dict]) -> dict:
    result = {}
    for language in sorted({row["language"] for row in rows}):
        subset = [row for row in rows if row["language"] == language]
        result[language] = dict(
            clips=len(subset),
            wer=sum(row["errors"] for row in subset)
            / sum(row["reference_words"] for row in subset),
            median_latency_seconds=statistics.median(
                row["latency_seconds"] for row in subset
            ),
            maximum_latency_seconds=max(row["latency_seconds"] for row in subset),
            mean_real_time_factor=statistics.mean(
                row["real_time_factor"] for row in subset
            ),
        )
    return result


def validate_report_policy(result: dict) -> None:
    if (
        result["status"] != "MEASURED_NOT_PRODUCT_ACCEPTANCE"
        or result["language_policy"] != LANGUAGE_POLICY
        or result["decode_parameters"] != DECODE_PARAMETERS
        or result["mixed_speech_verified"] is not False
        or result["command_fields_verified"] is not False
    ):
        raise ValueError("Unexpected benchmark policy or product claim")


def benchmark(root: Path, device: str, compute: str, model_name: str = "small") -> None:
    import ctranslate2
    import resource
    from faster_whisper import WhisperModel

    manifest = root / "smoke" / "manifest.json"
    if manifest.stat().st_size > MAX_DOWNLOAD:
        raise ValueError("Corpus manifest exceeds size limit")
    corpus = json.loads(manifest.read_text(encoding="utf-8"))
    validate_manifest(root, corpus)
    model_source = json.loads(
        (root / "models" / model_name / "pilot-source.json").read_text(encoding="utf-8")
    )
    validate_model(model_name, model_source, root / "models" / model_name)
    if model_source["dataset_revision"] != corpus["source"]["dataset_revision"]:
        raise ValueError("Model/corpus source revision mismatch")
    started = time.perf_counter()
    model = WhisperModel(
        str(root / "models" / model_name),
        device=device,
        compute_type=compute,
        cpu_threads=4,
        num_workers=1,
        local_files_only=True,
    )
    loaded = time.perf_counter() - started
    rows = []
    for clip in corpus["clips"]:
        file = root / "smoke" / clip["file"]
        start = time.perf_counter()
        language = clip["language"] if clip["language"] in CONFIGS else None
        segments, info = model.transcribe(
            str(file),
            language=language,
            task="transcribe",
            beam_size=5,
            condition_on_previous_text=False,
            vad_filter=False,
        )
        validate_decoded_duration(clip, info.duration)
        text = " ".join(segment.text for segment in segments).strip()
        elapsed = time.perf_counter() - start
        ref, hyp = normalize(clip["reference"]), normalize(text)
        rows.append(
            dict(
                file=clip["file"],
                language=clip["language"],
                duration_seconds=info.duration,
                latency_seconds=elapsed,
                real_time_factor=elapsed / max(info.duration, 0.001),
                reference_words=len(ref),
                errors=edit_distance(ref, hyp),
                detected_language=info.language,
                reference=clip["reference"],
                transcript=text,
            )
        )
    aggregate = aggregate_rows(rows)
    result = dict(
        status="MEASURED_NOT_PRODUCT_ACCEPTANCE",
        device=device,
        model_name=model_name,
        compute_type=compute,
        ctranslate2_version=ctranslate2.__version__,
        runtime_versions={
            name: version(name)
            for name in ("faster-whisper", "ctranslate2", "av", "huggingface-hub")
        },
        model_load_seconds=loaded,
        first_clip_seconds=rows[0]["latency_seconds"],
        peak_process_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        languages=aggregate,
        clips=rows,
        source=model_source,
        corpus_manifest_sha256=file_sha256(manifest),
        input_sha256={row["file"]: row["audio_sha256"] for row in corpus["clips"]},
        mixed_speech_verified=False,
        command_fields_verified=False,
        concurrency=1,
        cpu_threads=4,
        language_policy=LANGUAGE_POLICY,
        decode_parameters=DECODE_PARAMETERS,
    )
    (root / f"result-{model_name}-{device}-{compute}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    safe = {
        key: value for key, value in result.items() if key not in {"clips", "source"}
    }
    print(json.dumps(safe))


def verify_results(root: Path) -> None:
    """Audit saved measurements without repeating inference or copying weights."""
    manifest = root / "smoke" / "manifest.json"
    corpus = json.loads(manifest.read_text(encoding="utf-8"))
    validate_manifest(root, corpus)
    expected_inputs = {row["file"]: row["audio_sha256"] for row in corpus["clips"]}
    evidence = {}
    for model_name in MODELS:
        path = root / f"result-{model_name}-cpu-int8.json"
        result = json.loads(path.read_text(encoding="utf-8"))
        validate_report_policy(result)
        validate_model(model_name, result["source"], root / "models" / model_name)
        if (
            result["corpus_manifest_sha256"] != file_sha256(manifest)
            or result["input_sha256"] != expected_inputs
            or result["model_name"] != model_name
            or result["device"] != "cpu"
            or result["compute_type"] != "int8"
            or result["cpu_threads"] != 4
            or result["concurrency"] != 1
            or len(result["clips"]) != len(corpus["clips"])
        ):
            raise ValueError("Comparison binding mismatch")
        for measured, clip in zip(result["clips"], corpus["clips"], strict=True):
            if (
                measured["file"] != clip["file"]
                or measured["reference"] != clip["reference"]
                or measured["language"] != clip["language"]
            ):
                raise ValueError("Measured reference mismatch")
            validate_decoded_duration(clip, measured["duration_seconds"])
            latency, rtf = measured["latency_seconds"], measured["real_time_factor"]
            if (
                not math.isfinite(latency)
                or latency <= 0
                or not math.isclose(
                    rtf, latency / measured["duration_seconds"], rel_tol=1e-9
                )
            ):
                raise ValueError("Measured performance mismatch")
            ref, hyp = normalize(clip["reference"]), normalize(measured["transcript"])
            if measured["reference_words"] != len(ref) or measured[
                "errors"
            ] != edit_distance(ref, hyp):
                raise ValueError("Measured word-error mismatch")
        if result["languages"] != aggregate_rows(result["clips"]):
            raise ValueError("Measured aggregate mismatch")
        evidence[model_name] = dict(
            report_sha256=file_sha256(path),
            languages=result["languages"],
            model_revision=result["source"]["model_revision"],
            peak_process_rss_kib=result["peak_process_rss_kib"],
        )
    output = dict(
        status="COMPARISON_BINDING_PASS_NOT_PRODUCT_ACCEPTANCE",
        models=evidence,
        clips=len(corpus["clips"]),
        corpus_manifest_sha256=file_sha256(manifest),
        natural_mixed_verified=False,
        command_fields_verified=False,
    )
    (root / "comparison-verification.json").write_text(
        json.dumps(output, indent=2), encoding="utf-8"
    )
    print(json.dumps(output))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=["metadata", "prepare", "benchmark", "verify"]
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("/home/superuser/projects/kamilya-stt-pilot-20261003"),
    )
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--model", choices=list(MODELS), default="small")
    parser.add_argument(
        "--compute", choices=["int8", "float32", "float16"], default="int8"
    )
    args = parser.parse_args()
    # Do not inherit unrelated model-provider tokens for public artifact download.
    for name in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        os.environ.pop(name, None)
    if args.action == "metadata":
        print(json.dumps(metadata(args.model)))
    elif args.action == "prepare":
        if not 1 <= args.count <= 20:
            raise ValueError("Bounded pilot accepts 1..20 clips per language")
        with deadline(600):
            prepare(args.root, args.count, args.model)
    elif args.action == "benchmark":
        with deadline(600):
            benchmark(args.root, args.device, args.compute, args.model)
    else:
        verify_results(args.root)


if __name__ == "__main__":
    main()
