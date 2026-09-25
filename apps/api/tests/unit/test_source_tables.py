from app.modules.ai.source_tables import markdown_tables


def test_markdown_tables_preserve_rows_separated_by_layout_blanks() -> None:
    source = """| Collection | Material |

|---|---|

| Chicago | MDF |

| Phoenix | Wood |

## Next section
"""

    assert markdown_tables(source) == [
        (
            ["Collection", "Material"],
            [
                (["Chicago", "MDF"], "| Chicago | MDF |"),
                (["Phoenix", "Wood"], "| Phoenix | Wood |"),
            ],
        )
    ]
