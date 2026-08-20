"""Bounded file-format adapters for the pure workbook analyzer."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import openpyxl
import xlrd

from .analysis import LoadedStaffSheet

MAX_ANALYSIS_ROWS = 10_000
MAX_ANALYSIS_COLUMNS = 256


class WorkbookAnalysisLimitError(ValueError):
    pass


def _bounded_rows(rows, *, sheet_name: str) -> tuple[tuple[object, ...], ...]:
    result: list[tuple[object, ...]] = []
    for index, row in enumerate(rows, start=1):
        if index > MAX_ANALYSIS_ROWS:
            raise WorkbookAnalysisLimitError(f"sheet {sheet_name!r} exceeds {MAX_ANALYSIS_ROWS} analysis rows")
        values = tuple(row)
        if len(values) > MAX_ANALYSIS_COLUMNS:
            raise WorkbookAnalysisLimitError(f"sheet {sheet_name!r} exceeds {MAX_ANALYSIS_COLUMNS} columns")
        result.append(values)
    return tuple(result)


def _decode_csv(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Не удалось определить кодировку CSV-файла.")


def load_staff_workbook(content: bytes, filename: str) -> tuple[LoadedStaffSheet, ...]:
    suffix = Path(filename).suffix.casefold()
    if suffix == ".csv":
        text = _decode_csv(content)
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = _bounded_rows(csv.reader(io.StringIO(text), dialect=dialect), sheet_name="CSV")
        return (LoadedStaffSheet(name="CSV", rows=rows),)
    if suffix == ".xlsx":
        workbook = openpyxl.load_workbook(
            io.BytesIO(content),
            read_only=False,
            data_only=True,
            keep_links=False,
        )
        return tuple(
            LoadedStaffSheet(
                name=sheet.title,
                rows=_bounded_rows(sheet.iter_rows(values_only=True), sheet_name=sheet.title),
                merged_ranges=tuple(str(value) for value in sheet.merged_cells.ranges),
            )
            for sheet in workbook.worksheets
        )
    if suffix == ".xls":
        book = xlrd.open_workbook(file_contents=content, on_demand=True)
        try:
            return tuple(
                LoadedStaffSheet(
                    name=sheet.name,
                    rows=_bounded_rows(
                        (tuple(sheet.cell_value(row, col) for col in range(sheet.ncols)) for row in range(sheet.nrows)),
                        sheet_name=sheet.name,
                    ),
                )
                for sheet in (book.sheet_by_index(index) for index in range(book.nsheets))
            )
        finally:
            book.release_resources()
    raise ValueError("Поддерживаются только файлы .xls, .xlsx и .csv.")
