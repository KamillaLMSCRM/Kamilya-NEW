from types import SimpleNamespace

import pytest

from app.modules.ai.assessment import generate_lesson_assessment
from app.modules.ai.writer_schema import LessonContent


@pytest.mark.asyncio
async def test_standard_assessment_requests_five_mcq_questions_only():
    class FakeLLM:
        async def ainvoke(self, messages):
            prompt = messages[-1]["content"]
            assert "Exactly 5 single choice questions" in prompt
            assert "Do not add true/false or matching questions" in prompt
            options = [
                {"text": "Верный ответ", "is_correct": True},
                {"text": "Неверный ответ 1", "is_correct": False},
                {"text": "Неверный ответ 2", "is_correct": False},
                {"text": "Неверный ответ 3", "is_correct": False},
            ]
            questions = [
                {
                    "question": f"Вопрос {index}",
                    "options": options,
                    "explanation": "Объяснение",
                }
                for index in range(1, 6)
            ]
            return SimpleNamespace(
                content=(
                    '{"mcq": '
                    + __import__("json").dumps(questions, ensure_ascii=False)
                    + ', "true_false": [], "matching": []}'
                )
            )

    result = await generate_lesson_assessment(
        FakeLLM(),
        LessonContent(
            title="Правила выдачи микрокредита",
            content="Содержание урока",
            source_references=[],
        ),
        language="ru",
    )

    assert len(result.mcq) == 5
    assert result.true_false == []
    assert result.matching == []
