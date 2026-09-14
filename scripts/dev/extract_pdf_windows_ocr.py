"""Extract a scanned PDF locally with the Windows OCR runtime.

This helper is deliberately outside the production application.  It never
uploads the source and writes only a local JSON transcript plus rendered PNGs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import time
from pathlib import Path

from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapDecoder
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage import FileAccessMode, StorageFile


async def _ocr_image(path: Path, language: str) -> str:
    storage_file = await StorageFile.get_file_from_path_async(str(path.resolve()))
    stream = await storage_file.open_async(FileAccessMode.READ)
    try:
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        engine = OcrEngine.try_create_from_language(Language(language))
        if engine is None:
            raise RuntimeError(f"Windows OCR language is unavailable: {language}")
        result = await engine.recognize_async(bitmap)
        # Preserve visual lines: the evidence adapter needs section headings and
        # numbered clauses, while ``result.text`` flattens the whole page.
        return "\n".join(line.text for line in result.lines)
    finally:
        stream.close()


def _render(pdf: Path, pages_dir: Path, dpi: int, *, reuse_rendered: bool) -> list[Path]:
    existing = sorted(pages_dir.glob("page-*.png"))
    if reuse_rendered and existing:
        return existing
    executable = shutil.which("pdftoppm")
    if not executable:
        raise RuntimeError("pdftoppm is required for local PDF rendering")
    pages_dir.mkdir(parents=True, exist_ok=True)
    prefix = pages_dir / "page"
    subprocess.run(
        [executable, "-r", str(dpi), "-png", str(pdf), str(prefix)],
        check=True,
        capture_output=True,
        text=True,
    )
    return sorted(pages_dir.glob("page-*.png"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pages-dir", type=Path, required=True)
    parser.add_argument("--dpi", type=int, default=180)
    parser.add_argument("--language", default="ru")
    parser.add_argument("--reuse-rendered", action="store_true")
    args = parser.parse_args()

    started = time.perf_counter()
    pages = _render(
        args.pdf,
        args.pages_dir,
        args.dpi,
        reuse_rendered=args.reuse_rendered,
    )
    render_seconds = time.perf_counter() - started
    if not pages:
        raise RuntimeError("PDF rendering produced no pages")

    extracted: list[str] = []
    page_timings: list[float] = []
    for page in pages:
        page_started = time.perf_counter()
        extracted.append(asyncio.run(_ocr_image(page, args.language)))
        page_timings.append(time.perf_counter() - page_started)

    payload = {
        "source": str(args.pdf.resolve()),
        "page_count": len(pages),
        "render_seconds": render_seconds,
        "ocr_seconds": sum(page_timings),
        "page_seconds": page_timings,
        "pages": extracted,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in payload.items() if key != "pages"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
