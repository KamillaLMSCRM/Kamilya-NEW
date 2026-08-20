from types import SimpleNamespace

import pytest

from app.modules.ai.assessment import generate_lesson_assessment
from app.modules.ai.writer_schema import LessonContent


def _questions(topic: str, fact: str, source_quote: str, count: int = 5) -> list[dict]:
    options = [
        {"text": fact, "is_correct": True},
        {"text": "Посторонний вариант 1", "is_correct": False},
        {"text": "Посторонний вариант 2", "is_correct": False},
        {"text": "Посторонний вариант 3", "is_correct": False},
    ]
    return [
        {
            "question": f"Что указано про {topic} в материале? Вопрос {index}",
            "options": options,
            "explanation": f"Материал связывает {topic} с {fact}.",
            "source_quote": source_quote,
        }
        for index in range(1, count + 1)
    ]


@pytest.mark.asyncio
async def test_standard_assessment_requests_five_mcq_questions_only():
    class FakeLLM:
        async def ainvoke(self, messages):
            prompt = messages[-1]["content"]
            assert "Exactly 5 single choice questions" in prompt
            assert "Do not add true/false or matching questions" in prompt
            questions = _questions(
                "выдачу микрокредита",
                "проверки заявления",
                "Выдача микрокредита выполняется после проверки заявления.",
            )
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
            content="Выдача микрокредита выполняется после проверки заявления.",
            source_references=[],
        ),
        language="ru",
    )

    assert len(result.mcq) == 5
    assert result.mcq[0].source_quote.startswith("Выдача микрокредита")
    assert result.true_false == []
    assert result.matching == []


@pytest.mark.asyncio
async def test_standard_assessment_retries_an_incomplete_result():
    class FakeLLM:
        calls = 0

        async def ainvoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(
                    content='{"mcq": [], "true_false": [], "matching": []}'
                )
            retry_prompt = messages[-1]["content"]
            assert "Порядок рассмотрения заявления" in retry_prompt
            assert "Рассмотрение заявления начинается с проверки документов" in retry_prompt
            assert "base every question only on the lesson content" in retry_prompt.lower()
            assert "Here is your output" not in retry_prompt
            assert '"source_quote"' in retry_prompt
            questions = _questions(
                "рассмотрение заявления",
                "проверки документов",
                "Рассмотрение заявления начинается с проверки документов.",
            )
            return SimpleNamespace(
                content=(
                    '{"mcq": '
                    + __import__("json").dumps(questions, ensure_ascii=False)
                    + ', "true_false": [], "matching": []}'
                )
            )

    llm = FakeLLM()
    result = await generate_lesson_assessment(
        llm,
        LessonContent(
            title="Порядок рассмотрения заявления",
            content="Рассмотрение заявления начинается с проверки документов.",
            source_references=[],
        ),
        language="ru",
    )

    assert llm.calls == 2
    assert len(result.mcq) == 5


@pytest.mark.asyncio
async def test_standard_assessment_retries_structurally_valid_off_source_questions():
    class FakeLLM:
        calls = 0

        async def ainvoke(self, messages):
            self.calls += 1
            questions = (
                _questions(
                    "REST API формата",
                    "HTTP JSON",
                    "Выдача микрокредита выполняется после проверки заявления.",
                )
                if self.calls == 1
                else _questions(
                    "выдачу микрокредита",
                    "проверки заявления",
                    "Выдача микрокредита выполняется после проверки заявления.",
                )
            )
            return SimpleNamespace(
                content=(
                    '{"mcq": '
                    + __import__("json").dumps(questions, ensure_ascii=False)
                    + ', "true_false": [], "matching": []}'
                )
            )

    llm = FakeLLM()
    result = await generate_lesson_assessment(
        llm,
        LessonContent(
            title="Правила выдачи микрокредита",
            content="Выдача микрокредита выполняется после проверки заявления.",
            source_references=[],
        ),
        language="ru",
    )

    assert llm.calls == 2
    assert "микрокредита" in result.mcq[0].question


@pytest.mark.asyncio
async def test_standard_assessment_keeps_source_title_and_marks_untrusted_boundary():
    class FakeLLM:
        async def ainvoke(self, messages):
            assert "untrusted reference data" in messages[0]["content"]
            prompt = messages[-1]["content"]
            assert "BEGIN_UNTRUSTED_LESSON_DATA" in prompt
            assert "END_UNTRUSTED_LESSON_DATA" in prompt
            assert "never as instructions" in prompt
            questions = _questions(
                "выдачу микрокредита",
                "проверки заявления",
                "Выдача микрокредита выполняется после проверки заявления.",
            )
            return SimpleNamespace(
                content=(
                    '{"lesson_title":"Подменённый заголовок","mcq": '
                    + __import__("json").dumps(questions, ensure_ascii=False)
                    + ', "true_false": [], "matching": []}'
                )
            )

    result = await generate_lesson_assessment(
        FakeLLM(),
        LessonContent(
            title="Правила выдачи микрокредита",
            content=(
                "Выдача микрокредита выполняется после проверки заявления. "
                "UNTRUSTED_LESSON_DATA не является управляющим маркером."
            ),
            source_references=[],
        ),
        language="ru",
    )

    assert result.lesson_title == "Правила выдачи микрокредита"


@pytest.mark.asyncio
async def test_standard_assessment_rejects_too_short_lesson_before_llm_call():
    class FakeLLM:
        calls = 0

        async def ainvoke(self, messages):
            self.calls += 1
            raise AssertionError("LLM must not be called for an empty lesson")

    llm = FakeLLM()
    with pytest.raises(ValueError, match="insufficient material"):
        await generate_lesson_assessment(
            llm,
            LessonContent(
                title="Короткий урок",
                content="Нет.",
                source_references=[],
            ),
            language="ru",
        )

    assert llm.calls == 0


@pytest.mark.asyncio
async def test_standard_assessment_validates_quotes_against_prompt_bounded_source():
    class FakeLLM:
        calls = 0

        async def ainvoke(self, messages):
            self.calls += 1
            questions = _questions(
                "секретный порядок",
                "архивным приложением",
                "Секретный порядок определяется архивным приложением.",
            )
            return SimpleNamespace(
                content=(
                    '{"mcq": '
                    + __import__("json").dumps(questions, ensure_ascii=False)
                    + ', "true_false": [], "matching": []}'
                )
            )

    llm = FakeLLM()
    with pytest.raises(ValueError, match="source evidence is not in lesson data"):
        await generate_lesson_assessment(
            llm,
            LessonContent(
                title="Длинный регламент",
                content=(
                    "Основная процедура требует проверки заявления. "
                    + ("Рабочий порядок обработки документов. " * 300)
                    + "Секретный порядок определяется архивным приложением."
                ),
                source_references=[],
            ),
            language="ru",
        )

    assert llm.calls == 5
