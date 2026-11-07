"""Pure, bounded native extraction of source text and raster placements."""

from __future__ import annotations

import hashlib
import io
import json
import warnings
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

from PIL import Image, UnidentifiedImageError

from app.modules.documents.archive_preflight import preflight_ooxml


@dataclass(frozen=True, slots=True)
class NativeAsset:
    asset_id: str
    sha256: str
    mime_type: str
    data: bytes
    width: int
    height: int
    locator: dict[str, Any]


@dataclass(frozen=True, slots=True)
class NativeBlock:
    block_id: str
    kind: str
    text: str
    asset_ids: tuple[str, ...]
    page: int | None
    locator: dict[str, Any]


@dataclass(frozen=True, slots=True)
class NativeSource:
    blocks: tuple[NativeBlock, ...]
    assets: tuple[NativeAsset, ...]
    page_count: int | None
    warnings: tuple[str, ...]


def _identity(document_sha: str, kind: str, locator: dict[str, Any], digest: str = "") -> str:
    encoded = json.dumps([document_sha, kind, locator, digest], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def extract_native_source(blob: bytes, filename: str, document_sha256: str, *,
                          max_image_bytes: int, max_image_pixels: int) -> NativeSource | None:
    suffix = PurePath(filename).suffix.lower()
    if suffix not in (".docx", ".pdf"):
        return None
    if hashlib.sha256(blob).hexdigest() != document_sha256:
        raise ValueError("native_source_sha256_mismatch")
    if max_image_bytes <= 0 or max_image_pixels <= 0:
        raise ValueError("native_source_invalid_limits")
    blocks: list[NativeBlock] = []
    assets: list[NativeAsset] = []
    seen_assets: set[str] = set()

    def add_block(kind: str, text: str, ids: tuple[str, ...], page: int | None,
                  locator: dict[str, Any]) -> None:
        blocks.append(NativeBlock("block-" + _identity(document_sha256, kind, locator)[:24],
                                  kind, text, ids, page, locator))

    def add_asset(data: bytes, locator: dict[str, Any]) -> str:
        if not data or len(data) > max_image_bytes:
            raise ValueError("native_image_byte_limit")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    width, height = image.size
                    if width <= 0 or height <= 0 or width * height > max_image_pixels:
                        raise ValueError("native_image_pixel_limit")
                    image_format = image.format
                    image.verify()
                with Image.open(io.BytesIO(data)) as image:
                    image.load()
                    if image_format not in ("PNG", "JPEG"):
                        output = io.BytesIO()
                        image.convert("RGBA" if "A" in image.getbands() else "RGB").save(output, format="PNG")
                        data = output.getvalue()
                        if len(data) > max_image_bytes:
                            raise ValueError("native_image_byte_limit")
                        image_format = "PNG"
        except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombWarning,
                Image.DecompressionBombError) as exc:
            raise ValueError("native_image_invalid") from exc
        digest = hashlib.sha256(data).hexdigest()
        asset_id = "asset-" + digest
        if asset_id not in seen_assets:
            assets.append(NativeAsset(asset_id, digest, {"PNG": "image/png", "JPEG": "image/jpeg"}[image_format],
                                      data, width, height, locator))
            seen_assets.add(asset_id)
        return asset_id

    if suffix == ".docx":
        from docx import Document
        from docx.oxml.ns import qn
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        stream = io.BytesIO(blob)
        preflight_ooxml(stream, ".docx")
        document = Document(stream)
        # Reject external image targets, including unused relationships; never follow them.
        for rel in document.part.rels.values():
            if rel.is_external and rel.reltype.endswith("/image"):
                raise ValueError("native_image_external_relationship")

        def paragraph(p: Paragraph, location: dict[str, Any], kind: str, *,
                      table_ids: list[str] | None = None) -> str:
            text_parts: list[str] = []
            fragment = 0
            image_index = 0

            def flush() -> None:
                nonlocal fragment
                text = "".join(text_parts)
                text_parts.clear()
                if text:
                    add_block(kind, text, (), None, {**location, "fragment": fragment})
                    fragment += 1

            for node in p._p.iter():
                if node.tag == qn("w:drawing") and not any(child.tag == qn("a:blip") for child in node.iter()):
                    raise ValueError("native_source_unsupported_visual")
                if node.tag == qn("w:t"):
                    text_parts.append(node.text or "")
                elif node.tag == qn("w:tab"):
                    text_parts.append("\t")
                elif node.tag in (qn("w:br"), qn("w:cr")):
                    text_parts.append("\n")
                elif node.tag == qn("a:blip"):
                    if table_ids is None:
                        flush()
                    rid = node.get(qn("r:embed"))
                    if node.get(qn("r:link")) or not rid:
                        raise ValueError("native_image_external_or_missing_relationship")
                    rel = document.part.rels.get(rid)
                    if rel is None or rel.is_external or not rel.reltype.endswith("/image"):
                        raise ValueError("native_image_invalid_relationship")
                    locator = {**location, "image": image_index, "relationship": rid,
                               "member": str(rel.target_part.partname).lstrip("/")}
                    image_index += 1
                    asset_id = add_asset(rel.target_part.blob, locator)
                    if table_ids is not None:
                        text_parts.append("{{" + asset_id + "}}")
                        table_ids.append(asset_id)
                    else:
                        add_block("image", "", (asset_id,), None, locator)
                elif node.tag in (qn("w:pict"), qn("w:object")):
                    raise ValueError("native_source_unsupported_visual")
            if table_ids is not None:
                return "".join(text_parts)
            flush()
            return ""

        def walk(items: Any, path: dict[str, Any]) -> None:
            for index, item in enumerate(items):
                location = {**path, "index": index}
                if isinstance(item, Paragraph):
                    style = (item.style.name or "") if item.style else ""
                    kind = "heading" if style.lower().startswith("heading") else ("table" if "table" in path else "text")
                    paragraph(item, {**location, "style": style}, kind)
                elif isinstance(item, Table):
                    rows: list[list[str]] = []
                    table_ids: list[str] = []
                    for row_index, row in enumerate(item.rows):
                        cells: list[str] = []
                        for cell_index, cell in enumerate(row.cells):
                            cell_parts: list[str] = []
                            for paragraph_index, child in enumerate(cell.iter_inner_content()):
                                if not isinstance(child, Paragraph):
                                    raise ValueError("native_source_nested_table_unsupported")
                                cell_location = {"table": location, "row": row_index, "cell": cell_index,
                                                 "index": paragraph_index}
                                content = paragraph(child, cell_location, "table", table_ids=table_ids)
                                cell_parts.append(content)
                            cells.append("<br>".join(cell_parts).replace("\n", "<br>").replace("|", "\\|"))
                        rows.append(cells)
                    if rows:
                        width = max(len(row) for row in rows)
                        rows = [row + [""] * (width - len(row)) for row in rows]
                        lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
                        lines.extend("| " + " | ".join(row) + " |" for row in rows[1:])
                        add_block("table", "\n".join(lines), tuple(table_ids), None, location)

        walk(document.iter_inner_content(), {"member": "word/document.xml"})
        return NativeSource(tuple(blocks), tuple(assets), None, ())

    from pypdf import PdfReader
    from pypdf.generic import ContentStream

    reader = PdfReader(io.BytesIO(blob))
    for index, page in enumerate(reader.pages):
        page_number = index + 1
        # Native extraction cannot represent painted paths, shading, annotations,
        # or arbitrary form XObjects. Reject instead of silently losing them.
        try:
            if page.get("/Annots"):
                raise ValueError("source_preparation_unsupported_pdf_visual")
            content = page.get_contents()
            operations = ContentStream(content, reader).operations if content is not None else ()
            resources = page.get("/Resources")
            resources = resources.get_object() if resources is not None else {}
            objects = resources.get("/XObject")
            objects = objects.get_object() if objects is not None else {}
            for operands, operator in operations:
                if operator in {b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*", b"sh"}:
                    raise ValueError("source_preparation_unsupported_pdf_visual")
                if operator == b"Do":
                    if len(operands) != 1 or operands[0] not in objects:
                        raise ValueError("source_preparation_unsupported_pdf_visual")
                    obj = objects[operands[0]].get_object()
                    if obj.get("/Subtype") != "/Image":
                        raise ValueError("source_preparation_unsupported_pdf_visual")
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("source_preparation_unsupported_pdf_visual") from exc
        text = page.extract_text() or ""
        ids: list[str] = []
        for image_index, image in enumerate(page.images):
            locator = {"page": page_number, "image": image_index, "name": image.name}
            ids.append(add_asset(image.data, locator))
        # Image-only pages are page content for OCR, never automatic figures.
        add_block("page", text, tuple(ids) if not text.strip() else (), page_number, {"page": page_number})
        if text.strip():
            for image_index, asset_id in enumerate(ids):
                add_block("image", "", (asset_id,), page_number, {"page": page_number, "image": image_index})
    return NativeSource(tuple(blocks), tuple(assets), len(reader.pages),
                        ("pdf_figure_placement_is_page_level",) if any(b.kind == "image" for b in blocks) else ())
