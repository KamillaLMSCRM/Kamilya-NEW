"""Recover ruled PDF tables from the same blob, never from guessed text columns.

The lightweight remote converter can retain every word while losing row/column
relationships. Geometry proves those relationships; an exact text cross-check
then permits replacement of that table only. Ambiguous recovery fails closed.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

MAX_PAGES = 64
MAX_OPERANDS_PER_PAGE = 60_000
MAX_TABLE_CELLS = 4_096
TOLERANCE = 0.5


class PDFTableLayoutError(ValueError):
    """The source has a ruled table whose relationships cannot be verified."""


def _point(x: float, y: float, matrix: list[float]) -> tuple[float, float]:
    return (x * matrix[0] + y * matrix[2] + matrix[4],
            x * matrix[1] + y * matrix[3] + matrix[5])


def _quantize(value: float) -> float:
    return round(value / TOLERANCE) * TOLERANCE


def _page_tables(page: Any) -> list[list[list[str]]]:
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    pending: list[tuple[tuple[float, float], tuple[float, float]]] = []
    texts: list[tuple[float, float, str]] = []
    cursor: tuple[float, float] | None = None
    operands = 0

    def operand(op: bytes, args: list[Any], cm: list[float], _tm: list[float]) -> None:
        nonlocal cursor, operands
        operands += 1
        if operands > MAX_OPERANDS_PER_PAGE:
            raise PDFTableLayoutError('pdf_layout_operand_limit')
        if op == b'm':
            cursor = _point(float(args[0]), float(args[1]), cm)
        elif op == b'l' and cursor is not None:
            end = _point(float(args[0]), float(args[1]), cm)
            pending.append((cursor, end))
            cursor = end
        elif op == b're':
            x, y, width, height = map(float, args)
            corners = [_point(x, y, cm), _point(x + width, y, cm),
                       _point(x + width, y + height, cm), _point(x, y + height, cm)]
            pending.extend(zip(corners, [*corners[1:], corners[0]], strict=True))
        elif op in (b'S', b's', b'B', b'B*', b'b', b'b*'):
            segments.extend(pending)
            pending.clear()
            cursor = None
        elif op in (b'n', b'f', b'F', b'f*'):
            pending.clear()
            cursor = None

    def text(value: str, cm: list[float], tm: list[float], _font: Any, _size: float) -> None:
        value = ' '.join(value.split())
        if value:
            x, y = _point(float(tm[4]), float(tm[5]), cm)
            texts.append((x, y, value))

    page.extract_text(visitor_operand_before=operand, visitor_text=text)
    horizontal: dict[tuple[float, float], set[float]] = defaultdict(set)
    vertical: dict[tuple[float, float], set[float]] = defaultdict(set)
    for start, end in segments:
        x1, y1, x2, y2 = map(_quantize, (*start, *end))
        if y1 == y2 and abs(x2 - x1) > 8:
            horizontal[(min(x1, x2), max(x1, x2))].add(y1)
        if x1 == x2 and abs(y2 - y1) > 8:
            vertical[(min(y1, y2), max(y1, y2))].add(x1)
    tables: list[tuple[float, float, list[list[str]]]] = []
    if len(horizontal) > 256 or len(vertical) > 256:
        raise PDFTableLayoutError('pdf_layout_grid_limit')
    for (left, right), y_values in horizontal.items():
        if len(y_values) < 3:
            continue
        for (bottom, top), x_values in vertical.items():
            ys = sorted((y for y in y_values if bottom <= y <= top), reverse=True)
            xs = sorted(x for x in x_values if left <= x <= right)
            if (len(ys) < 3 or ys[0] != top or ys[-1] != bottom or
                    len(xs) < 3 or xs[0] != left or xs[-1] != right):
                continue
            cell_count = (len(xs) - 1) * (len(ys) - 1)
            if cell_count > MAX_TABLE_CELLS:
                raise PDFTableLayoutError('pdf_layout_cell_limit')
            cells: list[list[list[tuple[float, float, str]]]] = [
                [[] for _ in xs[:-1]] for _ in ys[:-1]
            ]
            for x, y, value in texts:
                if not left < x < right or not bottom < y < top:
                    continue
                row = next((i for i in range(len(ys) - 1) if ys[i+1] < y < ys[i]), None)
                col = next((i for i in range(len(xs) - 1) if xs[i] < x < xs[i+1]), None)
                if row is None or col is None:
                    raise PDFTableLayoutError('pdf_layout_text_on_cell_boundary')
                cells[row][col].append((y, x, value))
            rows = [
                [' '.join(item[2] for item in sorted(cell, key=lambda item: (-item[0], item[1])))
                 for cell in row]
                for row in cells
            ]
            if not all(rows[0]) or not any(any(row) for row in rows[1:]):
                raise PDFTableLayoutError('pdf_layout_missing_header_or_rows')
            tables.append((top, left, rows))
    return [rows for _top, _left, rows in sorted(tables, key=lambda item: (-item[0], item[1]))]


def preserve_pdf_tables(path: str | Path, markdown: str) -> tuple[str, int]:
    """Replace unique verified flattened tables; retain all surrounding prose.

    This is not an alternate converter or OCR fallback. It only cross-checks
    the remote text against ruled cell coordinates in the original PDF bytes.
    """
    from pypdf import PdfReader

    from app.modules.ai.source_tables import markdown_tables

    try:
        reader = PdfReader(str(path), strict=False)
    except Exception as exc:
        raise PDFTableLayoutError('pdf_layout_source_unreadable') from exc
    if len(reader.pages) > MAX_PAGES:
        raise PDFTableLayoutError('pdf_layout_page_limit')
    recovered = 0
    existing = [(headers, [cells for cells, _raw in rows])
                for headers, rows in markdown_tables(markdown)]
    for page in reader.pages:
        try:
            tables = _page_tables(page)
        except PDFTableLayoutError:
            raise
        except Exception as exc:
            raise PDFTableLayoutError('pdf_layout_geometry_unreadable') from exc
        for rows in tables:
            if any('|' in cell or '\\' in cell for row in rows for cell in row):
                raise PDFTableLayoutError('pdf_layout_unsupported_cell_delimiter')
            if (rows[0], rows[1:]) in existing:
                # Consume only a table present in the original converted text.
                # A repaired occurrence cannot prove another identical source
                # table was also retained by the converter.
                existing.remove((rows[0], rows[1:]))
                continue
            words = [word for row in rows for cell in row for word in cell.split()]
            if not words:
                raise PDFTableLayoutError('pdf_layout_empty_table')
            pattern = re.compile(r'(?<!\S)' + r'\s+'.join(map(re.escape, words)) + r'(?!\S)')
            matches = list(pattern.finditer(markdown))
            if len(matches) != 1:
                raise PDFTableLayoutError('pdf_layout_text_crosscheck_ambiguous')
            def line(row: list[str]) -> str:
                return '| ' + ' | '.join(row) + ' |'
            table = '\n'.join([line(rows[0]), line(['---'] * len(rows[0])), *map(line, rows[1:])])
            match = matches[0]
            markdown = markdown[:match.start()] + '\n\n' + table + '\n\n' + markdown[match.end():]
            recovered += 1
    return markdown, recovered
