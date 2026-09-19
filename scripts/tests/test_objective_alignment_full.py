"""Offline preflight tests for the bounded full-source harness."""

from __future__ import annotations

import asyncio
from argparse import Namespace
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.dev.objective_alignment import full  # noqa: E402


def _args(tmp_path: Path, *, source: Path, converter_json: Path | None = None) -> Namespace:
    return Namespace(
        source=source,
        converter_json=converter_json,
        env_file=tmp_path / "local.env",
        output_dir=tmp_path / "output",
        repeats=1,
    )


def _assert_preflight_before_env(monkeypatch: pytest.MonkeyPatch, args: Namespace, message: str) -> None:
    def fail_if_loaded(_env_file: Path) -> None:
        raise AssertionError("_load_env must not run before input preflight")

    monkeypatch.setattr(full, "_load_env", fail_if_loaded)
    with pytest.raises(ValueError, match=message):
        asyncio.run(full.main(args))


def test_existing_output_dir_is_refused_before_load_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "existing-output"
    output_dir.mkdir()
    source = tmp_path / "source.xlsx"
    source.write_bytes(b"minimal xlsx fixture")
    args = _args(tmp_path, source=source)
    args.output_dir = output_dir

    _assert_preflight_before_env(monkeypatch, args, "New output directory required")


def test_unsupported_source_suffix_is_refused_before_load_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.docx"
    source.write_bytes(b"minimal unsupported fixture")
    args = _args(tmp_path, source=source)

    _assert_preflight_before_env(monkeypatch, args, "An existing XLSX/PDF source file is required")


def test_pdf_without_captured_conversion_is_refused_before_load_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"minimal pdf fixture")
    args = _args(tmp_path, source=source)

    _assert_preflight_before_env(
        monkeypatch,
        args,
        "PDF requires an existing local production converter capture",
    )


def test_pdf_capture_must_be_a_file_before_load_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"minimal pdf fixture")
    converter_dir = tmp_path / "converter-capture"
    converter_dir.mkdir()
    args = _args(
        tmp_path,
        source=source,
        converter_json=converter_dir,
    )

    _assert_preflight_before_env(monkeypatch, args, "PDF requires an existing local production converter capture")
