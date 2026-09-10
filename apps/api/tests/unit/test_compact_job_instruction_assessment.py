import json
from types import SimpleNamespace

import pytest

from app.modules.ai.assessment import generate_lesson_assessment
from app.modules.ai.writer_schema import LessonContent


@pytest.mark.asyncio
async def test_compact_assessment_requests_only_three_mcq_questions():
    duties = [
        ("кассир", "Кассир", "наличные средства", "принимает", ["проверяет", "хранит", "пересчитывает"]),
        ("кладовщик", "Кладовщик", "товарные накладные", "проверяет", ["составляет", "выдаёт", "копирует"]),
        ("бухгалтер", "Бухгалтер", "платёжные документы", "сверяет", ["печатает", "выдаёт", "архивирует"]),
    ]

    class _LLM:
        messages = None

        async def ainvoke(self, messages, config=None, response_format=None):
            self.messages = messages
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "mcq": [
                            {
                                "question": f"Какие обязанности выполняет {subject}?",
                                "options": [
                                    {
                                        "text": f"{name} {action} {object_text}",
                                        "is_correct": option_index == 0,
                                    }
                                    for option_index, action in enumerate([correct, *alternatives])
                                ],
                                "explanation": f"Инструкция устанавливает, что {subject} {correct} {object_text}.",
                                "source_quote_id": f"E{index:02d}",
                            }
                            for index, (subject, name, object_text, correct, alternatives) in enumerate(duties, start=1)
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
            content=" ".join(
                f"Инструкция устанавливает, что {subject} {correct} {object_text}."
                for subject, _, object_text, correct, _ in duties
            ),
        ),
        compact=True,
    )

    assert len(result.mcq) == 3
    assert result.true_false == []
    assert result.matching == []
    assert "Exactly 3 single choice questions" in llm.messages[1]["content"]
    assert '"maxItems": 0' in llm.messages[1]["content"]
