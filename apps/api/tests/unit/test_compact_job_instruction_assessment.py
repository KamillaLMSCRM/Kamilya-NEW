import json
from types import SimpleNamespace

import pytest

from app.modules.ai.assessment import generate_lesson_assessment
from app.modules.ai.writer_schema import LessonContent


@pytest.mark.asyncio
async def test_compact_assessment_requests_only_three_mcq_questions():
    class _LLM:
        messages = None

        async def ainvoke(self, messages, config=None, response_format=None):
            self.messages = messages
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "mcq": [
                            {
                                "question": f"Какие обязанности выполняет кассир? {index}",
                                "options": [
                                    {
                                        "text": "Кассир принимает наличные средства",
                                        "is_correct": True,
                                    },
                                    {
                                        "text": "Кассир проверяет наличные средства",
                                        "is_correct": False,
                                    },
                                    {
                                        "text": "Кассир хранит наличные средства",
                                        "is_correct": False,
                                    },
                                    {
                                        "text": "Кассир пересчитывает наличные средства",
                                        "is_correct": False,
                                    },
                                ],
                                "explanation": (
                                    "Должностная инструкция устанавливает обязанности "
                                    "кассира по приёму наличных средств."
                                ),
                                "source_quote_id": "E01",
                            }
                            for index in range(1, 4)
                        ],
                        "true_false": [],
                        "matching": [],
                    },
                    ensure_ascii=False,
                )
            )

    llm = _LLM()
    result = await generate_lesson_assessment(
        llm,
        LessonContent(
            title="Должностные обязанности",
            objectives=["Знать обязанности"],
            content=(
                "Кассир принимает наличные средства и выполняет "
                "перечисленные обязанности."
            ),
        ),
        compact=True,
    )

    assert len(result.mcq) == 3
    assert result.true_false == []
    assert result.matching == []
    assert "Exactly 3 single choice questions" in llm.messages[1]["content"]
    assert '"maxItems": 0' in llm.messages[1]["content"]
