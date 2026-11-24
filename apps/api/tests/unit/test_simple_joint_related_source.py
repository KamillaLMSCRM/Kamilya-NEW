from app.modules.ai.v3.simple_joint_related_source import related_source_blocks


def test_companion_prose_is_literal_owned_and_bounded():
    rule = (
        "The employee checks the supervisor approval before issuing a kit above the temporary limit."
    )
    exception = (
        "If the employee checks the supervisor approval before issuing a kit above the temporary limit, "
        "a prior authorization number may be used when the supervisor is absent."
    )

    def block(ref, document, value, **origin):
        return {"id": ref, "document_id": document, "segments": [{"text": value, **origin}]}

    main = block("SRC3", "procedure", rule)
    companion = block("SRC12", "procedure", exception)
    duplicate = block("SRC15", "procedure", rule)
    other = block("SRC35", "other", exception)
    catalog = block("SRC45", "procedure", f"| 102-104 | {exception} |")
    asset = block("SRC46", "procedure", exception, asset_id="illustration")
    too_long = block("SRC88", "procedure", exception + "\n" + "paragraph " * 2200)
    blocks = [main, companion, duplicate, other, catalog, asset, too_long]
    assert related_source_blocks(blocks, {"SRC3"}) == [companion]
    assert related_source_blocks(blocks, {"SRC3", "SRC12"}) == []
    assert related_source_blocks(blocks, set()) == []
