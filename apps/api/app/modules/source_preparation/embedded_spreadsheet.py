"""Read literal worksheet text from a validated embedded XLSX package."""

from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

from app.modules.ai.ingestion import (
    MAX_XLSX_COLUMNS_PER_ROW,
    MAX_XLSX_RENDERED_CHARS,
    MAX_XLSX_ROWS_PER_SHEET,
    MAX_XLSX_VISIBLE_SHEETS,
    MAX_XLSX_VISITED_CELLS,
    spreadsheet_cell_text,
)


def embedded_spreadsheet_tables(stream: BytesIO) -> list[tuple[str, str]]:
    """Preserve visible cells and refuse workbooks whose meaning needs an Excel runtime."""
    from lxml import etree  # type: ignore[import-untyped]
    from openpyxl import load_workbook  # type: ignore[import-untyped]
    from openpyxl.utils.cell import coordinate_to_tuple  # type: ignore[import-untyped]

    failure = "native_source_unsupported_visual"
    try:
        with ZipFile(stream) as package:
            names = package.namelist()
            if len(names) != len(set(names)):
                raise ValueError(failure)
            for name in names:
                lower = name.lower()
                if (lower.startswith(("xl/drawings/", "xl/charts/", "xl/embeddings/", "xl/externallinks/",
                                      "xl/pivottables/", "xl/querytables/", "xl/ctrlprops/"))
                        or lower in {"xl/vbaproject.bin", "xl/connections.xml"}):
                    raise ValueError(failure)
                worksheet = lower.startswith("xl/worksheets/") and lower.endswith(".xml")
                relationship = lower.endswith(".rels")
                if not worksheet and not relationship:
                    continue
                with package.open(name) as xml:
                    for _, node in etree.iterparse(xml, events=("end",), resolve_entities=False, no_network=True):
                        tag = etree.QName(node).localname
                        if relationship and node.get("TargetMode") == "External":
                            raise ValueError(failure)
                        if worksheet and tag in {"row", "col"} and node.get("hidden") in {"1", "true"}:
                            raise ValueError(failure)
                        if worksheet and tag == "row" and int(node.get("r", "0")) > MAX_XLSX_ROWS_PER_SHEET:
                            raise ValueError(failure)
                        if worksheet and tag == "c":
                            row, column = coordinate_to_tuple(node.get("r"))
                            if row > MAX_XLSX_ROWS_PER_SHEET or column > MAX_XLSX_COLUMNS_PER_ROW:
                                raise ValueError(failure)
                        node.clear()
                        while node.getprevious() is not None:
                            del node.getparent()[0]

        workbook = load_workbook(stream, read_only=True, data_only=False, keep_links=False)
        tables = []
        visited = rendered = 0
        try:
            worksheets = [sheet for sheet in workbook.worksheets if sheet.sheet_state == "visible"]
            if not worksheets or len(worksheets) > MAX_XLSX_VISIBLE_SHEETS:
                raise ValueError(failure)
            for sheet in worksheets:
                sheet.reset_dimensions()
                rows = []
                for row_index, cells in enumerate(sheet.iter_rows(), start=1):
                    if row_index > MAX_XLSX_ROWS_PER_SHEET:
                        raise ValueError(failure)
                    if any(cell.data_type in {"e", "f"} for cell in cells):
                        raise ValueError(failure)
                    visited += len(cells)
                    if visited > MAX_XLSX_VISITED_CELLS:
                        raise ValueError(failure)
                    row = []
                    for cell in cells:
                        value = spreadsheet_cell_text(cell.value)
                        rendered += len(value)
                        if rendered > MAX_XLSX_RENDERED_CHARS:
                            raise ValueError(failure)
                        row.append(value)
                    if any(row):
                        rows.append(row)
                if not rows:
                    continue
                width = max(map(len, rows))
                # Bound the padded representation before building it.
                rendered += len(rows) * (width * 3 + 3) + width * 6
                if rendered > MAX_XLSX_RENDERED_CHARS:
                    raise ValueError(failure)
                lines = ["| " + " | ".join(row + [""] * (width - len(row))) + " |" for row in rows]
                lines.insert(1, "| " + " | ".join(["---"] * width) + " |")
                tables.append((sheet.title, "\n".join(lines)))
        finally:
            workbook.close()
        if not tables:
            raise ValueError(failure)
        return tables
    except Exception as exc:
        if isinstance(exc, ValueError) and exc.args == (failure,):
            raise
        raise ValueError(failure) from exc
