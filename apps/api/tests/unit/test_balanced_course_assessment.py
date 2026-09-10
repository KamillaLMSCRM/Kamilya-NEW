from types import SimpleNamespace

import pytest

from app.modules.ai.assessment import (
    _assessment_contract_reason_codes,
    _build_evidence_bank,
    generate_course_assessment,
    generate_lesson_assessment,
)
from app.modules.ai.writer_schema import CourseContent, LessonContent, ModuleContent


def _additional_questions() -> list[dict]:
    facts = [
        (
            "Когда передают график микрокредита?",
            "График микрокредита передают после подписания договора.",
            ["После подписания договора", "До подписания договора", "При обсуждении договора", "Без подписания договора"],
        ),
        (
            "Чем подтверждают погашение микрокредита?",
            "Погашение микрокредита подтверждают платёжной квитанцией.",
            ["Платёжной квитанцией", "Платёжной заявкой", "Платёжной справкой", "Платёжной ведомостью"],
        ),
        (
            "Где указывают срок микрокредита?",
            "Срок микрокредита указывают в подписанном договоре.",
            ["В подписанном договоре", "В предварительном договоре", "В отменённом договоре", "В неподписанном договоре"],
        ),
        (
            "Когда фиксируют просрочку микрокредита?",
            "Просрочку микрокредита фиксируют после пропуска платежа.",
            ["После пропуска платежа", "До пропуска платежа", "При внесении платежа", "Без пропуска платежа"],
        ),
    ]
    return [
        {
            "question": prompt,
            "options": [{"text": text, "is_correct": i == 0} for i, text in enumerate(options)],
            "explanation": quote,
            "source_quote_id": f"E{index:02d}",
        }
        for index, (prompt, quote, options) in enumerate(facts, start=2)
    ]


def _source_with_additional_facts(source: str) -> str:
    return "\n".join([source, *(q["explanation"] for q in _additional_questions())])


def _loan_questions() -> list[dict]:
    facts = [
        ("approval", "application review", "application intake"),
        ("payment", "contract signing", "contract review"),
        ("closure", "final repayment", "partial repayment"),
        ("renewal", "credit reassessment", "credit application"),
        ("collection", "missed repayment", "scheduled repayment"),
    ]
    return [
        {
            "question": f"When does loan {subject} occur?",
            "options": [
                {"text": f"after {condition}", "is_correct": True},
                {"text": f"before {condition}", "is_correct": False},
                {"text": f"during {alternative}", "is_correct": False},
                {"text": f"without {condition}", "is_correct": False},
            ],
            "explanation": f"Loan {subject} occurs after {condition}.",
            "source_quote_id": f"E{index:02d}",
        }
        for index, (subject, condition, alternative) in enumerate(facts, start=1)
    ]


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
            "question": f"Что указано про {topic} в материале?",
            "options": options,
            "explanation": f"Материал связывает {topic} с {fact}.",
            "source_quote": source_quote,
            "source_quote_id": source_quote_id,
        }
    ] + _additional_questions()[:count - 1]


def test_contract_diagnostics_use_bounded_reason_codes():
    error = ValueError(
        "MCQ #1: unknown source evidence id; MCQ #2: correct answer is an incomplete fragment"
    )

    assert _assessment_contract_reason_codes(error) == (
        "evidence_reference,grounding,answer_quality,learner_text_quality"
    )


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
            content=_source_with_additional_facts("Выдача микрокредита выполняется после проверки заявления."),
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
            content=_source_with_additional_facts("Рассмотрение заявления начинается с проверки документов."),
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
            content=_source_with_additional_facts("Выдача микрокредита выполняется после проверки заявления."),
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
                _source_with_additional_facts("Выдача микрокредита выполняется после проверки заявления.")
                + "\nUNTRUSTED_LESSON_DATA не является управляющим маркером."
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
                count=1,
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
            content=_source_with_additional_facts("Выдача микрокредита выполняется после проверки заявления."),
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
            ]["enum"] == ["E01", "E02", "E03", "E04", "E05"]
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
            content=_source_with_additional_facts("Выдача микрокредита выполняется после проверки заявления."),
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
            content=_source_with_additional_facts(source_quote),
            source_references=[],
        ),
        language="ru",
    )

    expected = _questions("выдачу микрокредита", "После проверки заявления", source_quote)
    for question, fixture in zip(result.mcq, expected, strict=True):
        correct = [option.text for option in question.options if option.is_correct]
        assert correct == [fixture["options"][0]["text"]]
        assert question.source_quote == fixture.get("source_quote", fixture["explanation"])
        assert question.explanation == fixture["explanation"]


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
            content=_source_with_additional_facts(source_quote),
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
            questions[0]["options"] = [
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
            content=_source_with_additional_facts(source_quote),
            source_references=[],
        ),
        language="ru",
    )

    correct = [option.text for option in result.mcq[0].options if option.is_correct]
    assert correct == ["30 минут"]
    assert all("|" not in question.source_quote for question in result.mcq)


@pytest.mark.asyncio
async def test_standard_assessment_strips_markdown_table_row_from_evidence():
    source_quote = "| Критический приоритет | Не позднее 15 минут |"

    class FakeLLM:
        async def ainvoke(self, messages, config=None, response_format=None):
            questions = [
                {
                    "question": "Каков срок для критического приоритета?",
                    "options": [
                        {"text": "15 минут", "is_correct": True},
                        {"text": "10 минут", "is_correct": False},
                        {"text": "20 минут", "is_correct": False},
                        {"text": "30 минут", "is_correct": False},
                    ],
                    "explanation": "Критический срок составляет 15 минут.",
                    "source_quote_id": "E01",
                }
            ] + _additional_questions()
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
            content=_source_with_additional_facts(source_quote),
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
            content=_source_with_additional_facts(source_quote),
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
    source_quote = " ".join(q["explanation"] for q in _loan_questions())

    class FakeLLM:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            questions = _loan_questions()
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
    source_quote = " ".join(q["explanation"] for q in _loan_questions())

    class FakeLLM:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            questions = _loan_questions()
            for index, question in enumerate(questions, start=1):
                if index != self.calls:
                    question["options"][0]["text"] = "Yes"
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
    source = " ".join(q["explanation"] for q in _loan_questions())
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
                questions = _loan_questions()
                for question in questions:
                    question["options"][0]["text"] = "Yes"
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


@pytest.mark.asyncio
async def test_assessment_stops_before_retry_when_generation_is_cancelled():
    class InvalidLLM:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            return SimpleNamespace(content="{}")

    checks = 0

    async def check_cancelled():
        nonlocal checks
        checks += 1
        if checks > 1:
            raise __import__("asyncio").CancelledError

    llm = InvalidLLM()
    with pytest.raises(__import__("asyncio").CancelledError):
        await generate_lesson_assessment(
            llm,
            LessonContent(
                title="Cancellation",
                content="Cancellation is confirmed before another model request is made.",
                source_references=[],
            ),
            language="en",
            check_cancelled=check_cancelled,
        )

    assert llm.calls == 1


@pytest.mark.asyncio
async def test_course_assessment_reports_only_completed_lessons():
    source = " ".join(q["explanation"] for q in _loan_questions())

    class ValidLLM:
        calls = 0

        async def ainvoke(self, messages, config=None, response_format=None):
            self.calls += 1
            return SimpleNamespace(
                content=__import__("json").dumps(
                    {
                        "mcq": _loan_questions(),
                        "true_false": [],
                        "matching": [],
                    }
                )
            )

    llm = ValidLLM()
    progress_after_calls = []

    async def on_progress(message):
        progress_after_calls.append((llm.calls, message))

    result = await generate_course_assessment(
        llm,
        CourseContent(
            title="Loan lifecycle",
            modules=[
                ModuleContent(
                    title="Module",
                    lessons=[
                        LessonContent(title="Approval", content=source, source_references=[]),
                        LessonContent(title="Review", content=source, source_references=[]),
                    ],
                )
            ],
        ),
        language="en",
        on_progress=on_progress,
    )

    assert len(result.assessments) == 2
    assert progress_after_calls == [
        (1, "Generated assessment 1/2: Approval"),
        (2, "Generated assessment 2/2: Review"),
    ]
