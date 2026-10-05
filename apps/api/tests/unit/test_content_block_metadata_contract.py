"""Compatible ORM JSONB binding and unchanged optional-string response contract."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.lessons.models import ContentBlock
from app.modules.lessons.schemas import ContentBlockCreate, ContentBlockResponse


def test_metadata_column_matches_existing_jsonb_schema():
    column_type = ContentBlock.__table__.c.metadata.type
    assert isinstance(column_type, postgresql.JSONB)
    encode = column_type.bind_processor(postgresql.dialect())
    assert encode(None) is None
    assert json.loads(encode("plain metadata")) == "plain metadata"
    assert json.loads(encode({"section": "synthetic"})) == {"section": "synthetic"}


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("exact text", "exact text"),
        ({"b": 2, "a": 1}, '{"a":1,"b":2}'),
        ([1, "two"], '[1,"two"]'),
        (True, "true"),
    ],
)
def test_response_reads_orm_metadata_without_declarative_collision(value, expected):
    row = SimpleNamespace(
        id=uuid4(),
        lesson_id=uuid4(),
        block_type="text",
        content="synthetic",
        order_index=0,
        created_at=datetime.now(UTC),
        metadata_=value,
        metadata="declarative sentinel",
    )
    result = ContentBlockResponse.model_validate(row)
    assert result.metadata == expected
    assert result.model_dump()["metadata"] == expected
    assert "metadata_" not in result.model_dump()


def test_public_response_dict_and_create_optional_string_are_unchanged():
    values = dict(
        id=uuid4(),
        lesson_id=uuid4(),
        block_type="text",
        order_index=0,
        created_at=datetime.now(UTC),
        metadata="public text",
    )
    assert ContentBlockResponse.model_validate(values).metadata == "public text"
    assert (
        ContentBlockCreate(lesson_id=values["lesson_id"], block_type="text", metadata="raw string").metadata
        == "raw string"
    )
    with pytest.raises(ValueError):
        ContentBlockCreate(lesson_id=values["lesson_id"], block_type="text", metadata={"not": "new API"})
