import json

import pytest

from app.modules.ai.ingestion import DocumentChunker


def test_chunker_splits_one_oversized_paragraph_without_dropping_text() -> None:
    paragraph = "".join(chr(ord("a") + index % 26) for index in range(137))

    chunks = DocumentChunker(chunk_size=31, chunk_overlap=0).chunk_markdown(
        paragraph, "doc-1", "source.md"
    )

    assert len(chunks) > 1
    assert all(len(chunk["text"]) <= 31 for chunk in chunks)
    assert "".join(chunk["text"] for chunk in chunks) == paragraph


def test_chunker_splits_oversized_table_rows_and_keeps_row_order_and_headings() -> None:
    oversized_cell = "x" * 83
    markdown = "# Inventory\n\n| Item | Details |\n| --- | --- |\n| Sofa | " + oversized_cell + " |\n| Chair | In stock |"

    chunks = DocumentChunker(chunk_size=40, chunk_overlap=0).chunk_markdown(
        markdown, "doc-2", "inventory.md"
    )

    combined = "".join(chunk["text"] for chunk in chunks)
    assert len(chunks) > 1
    assert all(len(chunk["text"]) <= 40 for chunk in chunks)
    assert oversized_cell in combined
    assert combined.index("Sofa") < combined.index(oversized_cell) < combined.index("Chair")
    assert all(json.loads(chunk["metadata"]["headings"]) == ["Inventory"] for chunk in chunks)


@pytest.mark.parametrize(
    "markdown, expected_text",
    [
        ("x" * 5000, "x" * 5000),
        (
            "| Cell |\n| --- |\n| " + "x" * 5000 + " |\n| Tail |",
            "| Tail |",
        ),
    ],
)
def test_chunker_default_overlap_makes_progress_for_oversized_source(
    markdown: str, expected_text: str
) -> None:
    chunks = DocumentChunker().chunk_markdown(markdown, "doc-default", "source.md")

    assert len(chunks) > 1
    assert all(0 < len(chunk["text"]) <= 1000 for chunk in chunks)
    assert expected_text in "".join(chunk["text"] for chunk in chunks)


def test_chunker_keeps_short_paragraph_output_compatible() -> None:
    markdown = "# Inventory\n\nFirst paragraph.\n\nSecond paragraph."

    chunks = DocumentChunker(chunk_size=1000, chunk_overlap=200).chunk_markdown(
        markdown, "doc-3", "inventory.md"
    )

    assert chunks == [
        {
            "text": markdown,
            "metadata": {
                "doc_id": "doc-3",
                "doc_name": "inventory.md",
                "headings": '["Inventory"]',
            },
        }
    ]


@pytest.mark.parametrize(
    ("chunk_size", "chunk_overlap"),
    [(0, 0), (-1, 0), (10, -1), (10, 10), (10, 11)],
)
def test_chunker_rejects_non_progressing_sizes(chunk_size: int, chunk_overlap: int) -> None:
    with pytest.raises(ValueError):
        DocumentChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
