from types import SimpleNamespace

import pytest

from app.modules.ai.assessment import _build_evidence_bank, generate_lesson_assessment
from app.modules.ai.writer_schema import LessonContent


def _questions(
    topic: str,
    fact: str,
    source_quote: str,
    count: int = 5,
    source_quote_id: str = "E01",
) -> list[dict]:
    fact_words = fact.split()
    distractors = [
        " ".join([*fact_words[:-1], replacement])
        for replacement in ("договора", "анкеты", "отчёта")
    ]
    options = [
        {"text": fact, "is_correct": True},
        *[
            {"text": distractor, "is_correct": False}
            for distractor in distractors
        ],
    ]
    return [
        {
            "question": f"Что указано про {topic} в материале? Вопрос {index}",
            "options": options,
            "explanation": f"Материал связывает {topic} с {fact}.",
            "source_quote": source_quote,
            "source_quote_id": source_quote_id,
        }
        for index in range(1, count + 1)
    ]


@pytest.mark.asyncio
async def test_standard_assessment_requests_five_mcq_questions_only():
    class FakeLLM:
        async def ainvoke(self, messages, config=None, response_format=None):
            prompt = messages[-1]["content"]
            assert "Exactly 5 single choice questions" in prompt
            assert "Do not add true/false or matching questions" in prompt
            assert "ALLOWED_EVIDENCE_BANK" in prompt
            assert '"source_quote_id"' in prompt
            assert '"E01"' in prompt
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

        async def ainvoke(self, messages, config=None, response_format=None):
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
            assert '"source_quote_id"' in retry_prompt
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
async def test_standard_assessment_repairs_structurally_valid_off_source_questions():
    class FakeLLM:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
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
    assert "REST" not in result.mcq[0].question
    assert "HTTP" not in result.mcq[0].explanation


@pytest.mark.asyncio
async def test_standard_assessment_keeps_source_title_and_marks_untrusted_boundary():
    class FakeLLM:
        async def ainvoke(self, messages, config=None, response_format=None):
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

        async def ainvoke(self, messages, config=None, response_format=None):
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

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            questions = _questions(
                "секретный порядок",
                "архивным приложением",
                "Секретный порядок определяется архивным приложением.",
                source_quote_id="E99",
            )
            return SimpleNamespace(
                content=(
                    '{"mcq": '
                    + __import__("json").dumps(questions, ensure_ascii=False)
                    + ', "true_false": [], "matching": []}'
                )
            )

    llm = FakeLLM()
    with pytest.raises(ValueError, match="unknown source evidence id"):
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


@pytest.mark.asyncio
async def test_standard_assessment_resolves_authoritative_quote_from_evidence_id():
    class FakeLLM:
        async def ainvoke(self, messages, config=None, response_format=None):
            questions = _questions(
                "выдачу микрокредита",
                "проверки заявления",
                "Модель попыталась подменить цитату.",
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

    assert result.mcq[0].source_quote == (
        "Выдача микрокредита выполняется после проверки заявления."
    )


@pytest.mark.asyncio
async def test_standard_assessment_requests_provider_structured_output():
    class FakeLLM:
        async def ainvoke(self, messages, config=None, response_format=None):
            assert response_format is not None
            assert response_format["type"] == "json_schema"
            schema = response_format["json_schema"]["schema"]
            assert schema["properties"]["mcq"]["minItems"] == 5
            assert schema["properties"]["mcq"]["maxItems"] == 5
            assert schema["properties"]["mcq"]["items"]["properties"][
                "source_quote_id"
            ]["enum"] == ["E01"]
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


@pytest.mark.asyncio
async def test_standard_assessment_keeps_concise_answer_and_server_owned_quote():
    source_quote = "Выдача микрокредита выполняется после проверки заявления."

    class FakeLLM:
        async def ainvoke(self, messages, config=None, response_format=None):
            questions = _questions(
                "выдачу микрокредита",
                "После проверки заявления",
                source_quote,
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
            content=source_quote,
            source_references=[],
        ),
        language="ru",
    )

    for question in result.mcq:
        correct = [option.text for option in question.options if option.is_correct]
        assert correct == ["После проверки заявления"]
        assert question.source_quote == source_quote
        assert question.explanation == (
            "Материал связывает выдачу микрокредита с После проверки заявления."
        )


@pytest.mark.asyncio
async def test_standard_assessment_repairs_unanchored_question_from_evidence():
    source_quote = "Выдача микрокредита выполняется после проверки заявления."

    class FakeLLM:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            questions = _questions(
                "операцию" if self.calls == 1 else "выдачу микрокредита",
                "После проверки заявления",
                source_quote,
            )
            if self.calls == 1:
                for question in questions:
                    question["question"] = "Каков порядок действий?"
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
            content=source_quote,
            source_references=[],
        ),
        language="ru",
    )

    assert llm.calls == 2
    assert all("микрокредит" in question.question.lower() for question in result.mcq)


def test_evidence_bank_excludes_incomplete_colon_introductions():
    bank = _build_evidence_bank(
        "Курс считается завершённым при двух обязательных условиях:\n"
        "Первое условие — завершение всех уроков.\n"
        "Второе условие — успешная сдача теста."
    )

    assert "Курс считается завершённым при двух обязательных условиях:" not in bank.values()
    assert "Первое условие — завершение всех уроков." in bank.values()


@pytest.mark.asyncio
async def test_standard_assessment_renders_markdown_evidence_as_plain_answer():
    source_quote = "*   **Временное окно:** Сотруднику предоставляется **30 минут** на тест."

    class FakeLLM:
        async def ainvoke(self, messages, config=None, response_format=None):
            questions = _questions(
                "временное окно",
                "30 минут",
                source_quote,
            )
            for question in questions:
                question["options"] = [
                    {"text": "30 минут", "is_correct": True},
                    {"text": "20 минут", "is_correct": False},
                    {"text": "40 минут", "is_correct": False},
                    {"text": "60 минут", "is_correct": False},
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
            title="Временное окно",
            content=source_quote,
            source_references=[],
        ),
        language="ru",
    )

    for question in result.mcq:
        correct = [option.text for option in question.options if option.is_correct]
        assert correct == ["30 минут"]
        assert "|" not in question.source_quote


@pytest.mark.asyncio
async def test_standard_assessment_strips_markdown_table_row_from_evidence():
    source_quote = "| Критический приоритет | Не позднее 15 минут |"

    class FakeLLM:
        async def ainvoke(self, messages, config=None, response_format=None):
            questions = [
                {
                    "question": f"Каков срок для критического приоритета? {index}",
                    "options": [
                        {"text": "15 минут", "is_correct": True},
                        {"text": "10 минут", "is_correct": False},
                        {"text": "20 минут", "is_correct": False},
                        {"text": "30 минут", "is_correct": False},
                    ],
                    "explanation": "Критический срок составляет 15 минут.",
                    "source_quote_id": "E01",
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
            title="Срок критического обращения",
            content=source_quote,
            source_references=[],
        ),
        language="ru",
    )

    assert all("|" not in question.source_quote for question in result.mcq)
    assert result.mcq[0].source_quote == (
        "Критический приоритет — Не позднее 15 минут"
    )


@pytest.mark.asyncio
async def test_standard_assessment_retries_answer_length_tell():
    source_quote = (
        "Обращение критического приоритета необходимо зарегистрировать "
        "и передать ответственному специалисту не позднее пятнадцати минут."
    )

    class FakeLLM:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            questions = _questions(
                "критический приоритет",
                "пятнадцати минут",
                source_quote,
            )
            if self.calls == 1:
                for question in questions:
                    question["options"] = [
                        {"text": source_quote, "is_correct": True},
                        {"text": "Позже", "is_correct": False},
                        {"text": "Завтра", "is_correct": False},
                        {"text": "Никогда", "is_correct": False},
                    ]
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
            title="Срок критического обращения",
            content=source_quote,
            source_references=[],
        ),
        language="ru",
    )

    assert llm.calls == 2
    assert all(
        max(len(option.text) for option in question.options)
        < len(source_quote)
        for question in result.mcq
    )


@pytest.mark.asyncio
async def test_standard_assessment_keeps_valid_questions_after_retries_exhausted():
    source_quote = "Loan approval occurs after application review."

    class FakeLLM:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            questions = [
                {
                    "question": f"When does loan approval occur? Case {index}",
                    "options": [
                        {"text": "after application review", "is_correct": True},
                        {"text": "before application review", "is_correct": False},
                        {"text": "during application intake", "is_correct": False},
                        {"text": "without application review", "is_correct": False},
                    ],
                    "explanation": source_quote,
                    "source_quote_id": "E01",
                }
                for index in range(1, 6)
            ]
            questions[-1]["options"][0]["text"] = "Yes"
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
            title="Loan approval rules",
            content=source_quote,
            source_references=[],
        ),
        language="en",
    )

    assert llm.calls == 5
    assert len(result.mcq) == 4
    assert all(
        option.text != "Yes"
        for question in result.mcq
        for option in question.options
        if option.is_correct
    )


@pytest.mark.asyncio
async def test_standard_assessment_accumulates_distinct_valid_questions_across_retries():
    source_quote = "Loan approval occurs after application review."

    class FakeLLM:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            questions = []
            for index in range(1, 6):
                correct_text = (
                    "after application review"
                    if index == self.calls
                    else "Yes"
                )
                questions.append(
                    {
                        "question": f"When does loan approval occur? Case {index}",
                        "options": [
                            {"text": correct_text, "is_correct": True},
                            {"text": "before application review", "is_correct": False},
                            {"text": "during application intake", "is_correct": False},
                            {"text": "without application review", "is_correct": False},
                        ],
                        "explanation": source_quote,
                        "source_quote_id": "E01",
                    }
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
            title="Loan approval rules",
            content=source_quote,
            source_references=[],
        ),
        language="en",
    )

    assert llm.calls == 5
    assert len(result.mcq) == 5
    assert len({question.question for question in result.mcq}) == 5


@pytest.mark.asyncio
async def test_standard_assessment_recovers_with_individual_evidence_questions():
    source = (
        "Loan approval occurs after application review. "
        "Loan payment occurs after contract signing. "
        "Loan closure occurs after final repayment."
    )
    evidence = {
        "E01": ("approval", "application review", "application intake"),
        "E02": ("payment", "contract signing", "contract review"),
        "E03": ("closure", "final repayment", "partial repayment"),
    }

    class FakeLLM:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            if self.calls <= 5:
                questions = [
                    {
                        "question": f"When does loan approval occur? Case {index}",
                        "options": [
                            {"text": "Yes", "is_correct": True},
                            {"text": "before application review", "is_correct": False},
                            {"text": "during application intake", "is_correct": False},
                            {"text": "without application review", "is_correct": False},
                        ],
                        "explanation": source,
                        "source_quote_id": "E01",
                    }
                    for index in range(1, 6)
                ]
            else:
                schema = response_format["json_schema"]["schema"]
                evidence_id = schema["properties"]["mcq"]["items"]["properties"][
                    "source_quote_id"
                ]["enum"][0]
                subject, correct_suffix, alternative = evidence[evidence_id]
                questions = [
                    {
                        "question": f"When does loan {subject} occur?",
                        "options": [
                            {"text": f"after {correct_suffix}", "is_correct": True},
                            {"text": f"before {correct_suffix}", "is_correct": False},
                            {"text": f"during {alternative}", "is_correct": False},
                            {"text": f"without {correct_suffix}", "is_correct": False},
                        ],
                        "explanation": f"Loan {subject} occurs after {correct_suffix}.",
                        "source_quote_id": evidence_id,
                    }
                ]
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
            title="Loan lifecycle",
            content=source,
            source_references=[],
        ),
        language="en",
    )

    assert llm.calls == 8
    assert len(result.mcq) == 3
    assert {question.question for question in result.mcq} == {
        "When does loan approval occur?",
        "When does loan payment occur?",
        "When does loan closure occur?",
    }


@pytest.mark.asyncio
async def test_focused_assessment_retries_rejected_evidence_candidate():
    source = (
        "Loan approval occurs after application review. "
        "Loan payment occurs after contract signing. "
        "Loan closure occurs after final repayment."
    )
    evidence = {
        "E01": ("approval", "application review", "application intake"),
        "E02": ("payment", "contract signing", "contract review"),
        "E03": ("closure", "final repayment", "partial repayment"),
    }

    class FakeLLM:
        calls = 0
        focused_calls: dict[str, int] = {}

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            if self.calls <= 5:
                questions = [
                    {
                        "question": "When does loan approval occur?",
                        "options": [
                            {"text": "Yes", "is_correct": True},
                            {"text": "before review", "is_correct": False},
                            {"text": "during intake", "is_correct": False},
                            {"text": "without review", "is_correct": False},
                        ],
                        "explanation": source,
                        "source_quote_id": "E01",
                    }
                ]
            else:
                schema = response_format["json_schema"]["schema"]
                evidence_id = schema["properties"]["mcq"]["items"]["properties"][
                    "source_quote_id"
                ]["enum"][0]
                self.focused_calls[evidence_id] = self.focused_calls.get(evidence_id, 0) + 1
                subject, correct_suffix, alternative = evidence[evidence_id]
                if self.focused_calls[evidence_id] == 1:
                    options = [
                        {
                            "text": f"loan {subject} occurs after {correct_suffix} today",
                            "is_correct": True,
                        },
                        {"text": "never", "is_correct": False},
                        {"text": "elsewhere", "is_correct": False},
                        {"text": "unknown", "is_correct": False},
                    ]
                else:
                    options = [
                        {"text": f"after {correct_suffix} loan {subject} occurs", "is_correct": True},
                        {"text": f"before {correct_suffix} loan {subject} occurs", "is_correct": False},
                        {"text": f"during {alternative} loan {subject} occurs", "is_correct": False},
                        {"text": f"without {correct_suffix} loan {subject} occurs", "is_correct": False},
                    ]
                questions = [
                    {
                        "question": f"When does loan {subject} occur?",
                        "options": options,
                        "explanation": f"Loan {subject} occurs after {correct_suffix}.",
                        "source_quote_id": evidence_id,
                    }
                ]
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
            title="Loan lifecycle",
            content=source,
            source_references=[],
        ),
        language="en",
    )

    assert llm.calls == 11
    assert len(result.mcq) == 3
    assert llm.focused_calls == {"E01": 2, "E02": 2, "E03": 2}
