"""Shared parsing for source-preserving Markdown tables."""

import re

_MARKDOWN_TABLE_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")


def markdown_table_cells(line: str) -> list[str]:
    """Return cells only for a complete pipe-delimited Markdown row."""

    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def markdown_tables(text: str) -> list[tuple[list[str], list[tuple[list[str], str]]]]:
    """Return bounded Markdown tables while preserving each exact body row.

    Spreadsheet conversion may place an empty line between every Markdown row.
    Those empty lines are layout only. A following header/separator pair starts
    a new table rather than becoming data in the current one.
    """

    lines = text.splitlines()
    tables: list[tuple[list[str], list[tuple[list[str], str]]]] = []
    index = 0
    while index + 1 < len(lines):
        headers = markdown_table_cells(lines[index])
        separator_index = index + 1
        while separator_index < len(lines) and not lines[separator_index].strip():
            separator_index += 1
        separator = (
            markdown_table_cells(lines[separator_index])
            if separator_index < len(lines)
            else []
        )
        if (
            len(headers) >= 2
            and len(separator) == len(headers)
            and all(_MARKDOWN_TABLE_SEPARATOR_CELL_RE.fullmatch(cell) for cell in separator)
        ):
            rows: list[tuple[list[str], str]] = []
            cursor = separator_index + 1
            while cursor < len(lines):
                while cursor < len(lines) and not lines[cursor].strip():
                    cursor += 1
                if cursor >= len(lines):
                    break
                cells = markdown_table_cells(lines[cursor])
                if len(cells) != len(headers):
                    break
                following = cursor + 1
                while following < len(lines) and not lines[following].strip():
                    following += 1
                following_cells = (
                    markdown_table_cells(lines[following]) if following < len(lines) else []
                )
                if len(following_cells) == len(headers) and all(
                    _MARKDOWN_TABLE_SEPARATOR_CELL_RE.fullmatch(cell)
                    for cell in following_cells
                ):
                    break
                rows.append((cells, lines[cursor].strip()))
                cursor += 1
            if rows:
                tables.append((headers, rows))
            index = cursor
            continue
        index += 1
    return tables
