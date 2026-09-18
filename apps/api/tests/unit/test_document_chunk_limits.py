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


def test_chunker_keeps_sentence_like_ordinal_heading_as_body_text() -> None:
    list_item = "3. Не смешивать поставки до окончания приемки."
    markdown = "\n\n".join(
        [
            "# Политика склада",
            "## 10. Условия хранения и ротация",
            f"## {list_item}",
            "## 11. Общие требования.",
            "Требования применяются на всём складе.",
            "## ПОРЯДОК ПРИЕМКИ",
            "### Обязательная проверка",
            "Проверить маркировку каждой поставки.",
        ]
    )

    chunks = DocumentChunker(chunk_size=1000, chunk_overlap=0).chunk_markdown(
        markdown, "doc-policy", "warehouse-policy.md"
    )

    list_item_chunk = next(chunk for chunk in chunks if list_item in chunk["text"])
    assert list_item in list_item_chunk["text"]
    assert f"## {list_item}" not in list_item_chunk["text"]
    assert json.loads(list_item_chunk["metadata"]["headings"]) == [
        "Политика склада",
        "10. Условия хранения и ротация",
    ]
    numbered_heading_chunk = next(
        chunk for chunk in chunks if "Требования применяются" in chunk["text"]
    )
    assert json.loads(numbered_heading_chunk["metadata"]["headings"]) == [
        "Политика склада",
        "11. Общие требования.",
    ]
    legal_heading_chunk = next(chunk for chunk in chunks if "Обязательная проверка" in chunk["text"])
    assert json.loads(legal_heading_chunk["metadata"]["headings"]) == [
        "Политика склада",
        "ПОРЯДОК ПРИЕМКИ",
        "Обязательная проверка",
    ]


@pytest.mark.parametrize(
    "list_item",
    [
        "3) Сотрудник проверяет документы",
        "4) Check the label before unloading",
        "1. Нанести красную этикетку с причиной и ответственным.",
        "3. Закрыть системную операцию после подтверждения выдачи.",
        "2) находиться под поднятым грузом;",
    ],
)
def test_chunker_keeps_finite_verb_ordinal_items_as_body_without_punctuation(
    list_item: str,
) -> None:
    markdown = "\n\n".join(
        [
            "# Политика склада",
            "## 10. К условиям хранения",
            f"## {list_item}",
            "Требование применяется к каждой поставке.",
        ]
    )

    chunks = DocumentChunker(chunk_size=1000, chunk_overlap=0).chunk_markdown(
        markdown, "doc-policy", "warehouse-policy.md"
    )

    item_chunk = next(chunk for chunk in chunks if list_item in chunk["text"])
    assert f"## {list_item}" not in item_chunk["text"]
    assert json.loads(item_chunk["metadata"]["headings"]) == [
        "Политика склада",
        "10. К условиям хранения",
    ]
    assert "Требование применяется к каждой поставке." in item_chunk["text"]


def test_chunker_preserves_concise_preposition_heading_as_structure() -> None:
    markdown = "\n\n".join(
        [
            "# Политика склада",
            "## 10. К условиям хранения",
            "Описание правил хранения.",
        ]
    )

    chunks = DocumentChunker(chunk_size=1000, chunk_overlap=0).chunk_markdown(
        markdown, "doc-policy", "warehouse-policy.md"
    )

    content_chunk = next(chunk for chunk in chunks if "Описание правил хранения." in chunk["text"])
    assert json.loads(content_chunk["metadata"]["headings"]) == [
        "Политика склада",
        "10. К условиям хранения",
    ]


@pytest.mark.parametrize(
    ("chunk_size", "chunk_overlap"),
    [(0, 0), (-1, 0), (10, -1), (10, 10), (10, 11)],
)
def test_chunker_rejects_non_progressing_sizes(chunk_size: int, chunk_overlap: int) -> None:
    with pytest.raises(ValueError):
        DocumentChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
