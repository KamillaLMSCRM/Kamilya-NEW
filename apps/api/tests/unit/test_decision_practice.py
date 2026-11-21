from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.lessons.decision_practice import BLOCK_TYPE, DecisionPractice, published_practices
from app.modules.lessons.decision_practice_router import PracticeEdit, save_editor


def example():
    first, left, right = [str(uuid4()) for _ in range(3)]
    return {
        "title": {"ru": "Приём смены", "kk": "Ауысымды қабылдау"},
        "steps": [
            {"id": first, "text": {"ru": "Что делаете?", "kk": "Не істейсіз?"}, "choices": [
                {"label": {"ru": "Проверить", "kk": "Тексеру"}, "target": left},
                {"label": {"ru": "Подписать", "kk": "Қол қою"}, "target": right},
            ]},
            {"id": left, "text": {"ru": "Записи сверены", "kk": "Жазбалар салыстырылды"}, "choices": []},
            {"id": right, "text": {"ru": "Ошибка не замечена", "kk": "Қате байқалмады"}, "choices": []},
        ],
    }


def test_requires_valid_branches_and_complete_translations():
    valid = example()
    assert DecisionPractice.model_validate(valid).steps
    missing, loop, unreachable, untranslated = [deepcopy(valid) for _ in range(4)]
    missing["steps"][0]["choices"][0]["target"] = str(uuid4())
    loop["steps"][1]["choices"] = [
        {"target": loop["steps"][0]["id"], "label": {"ru": "Назад", "kk": "Артқа"}},
    ]
    unreachable["steps"].append({**unreachable["steps"][1], "id": str(uuid4())})
    untranslated["steps"][1]["text"]["kk"] = ""
    for payload, reason in [(missing, "unknown_destination"), (loop, "loop_in_practice"),
                            (unreachable, "unreachable_step"), (untranslated, "string_too_short")]:
        with pytest.raises(ValidationError, match=reason):
            DecisionPractice.model_validate(payload)


def test_only_valid_single_practice_in_the_frozen_lesson_is_projected():
    original = DecisionPractice.model_validate(example())
    block = {"block_type": BLOCK_TYPE, "content": original.model_dump_json()}
    snapshot = {"modules": [{"lessons": [
        {"id": "frozen", "content_blocks": [block]},
        {"id": "ambiguous", "content_blocks": [block, block]},
        {"id": "old", "content_blocks": [{**block, "content": "{}"}]},
        {"id": "ordinary"},
    ]}]}
    editions = dict(published_practices(snapshot))
    assert list(editions) == ["frozen"]
    assert editions["frozen"].practice == original
    assert len(editions["frozen"].revision) == 64


@pytest.mark.asyncio
async def test_concurrent_draft_change_rejects_stale_save():
    original = DecisionPractice.model_validate(example()).model_dump_json()
    block = SimpleNamespace(content=original)
    scope = "app.modules.lessons.decision_practice_router."
    with patch(scope + "_draft_block", return_value=(SimpleNamespace(id=uuid4()), block)) as fetch, \
         patch(scope + "touch_course") as touch:
        with pytest.raises(HTTPException) as error:
            await save_editor(uuid4(), uuid4(), PracticeEdit(revision=None, practice=None), AsyncMock(), None)
    assert error.value.status_code == 409
    assert fetch.call_args.kwargs["lock"]
    touch.assert_not_called()
    assert block.content == original
