"""Mixed supported workflows need exact source coverage, not family exclusivity."""

from app.modules.ai.evidence_engine.assessment_axes import (
    derive_assessment_axes,
    has_partial_unatomized_source_contract,
    materialize_assessment,
)
from app.modules.ai.evidence_engine.models import AuthoredAssessment, LessonDraft, SourceFact

REJECTION = (
    "Если контролер не согласовывает операцию, то в карточке проставляется отметка об отказе. "
    "В этом случае составляется Акт несоответствия с расчетом допустимого значения. "
    "С специалиста, выдавшего документ, берется объяснительная и обязательство. "
    "Акты несоответствия предоставляются в отдел контроля, на основании которых "
    "несогласованные документы вносятся в Стоп-лист."
)
HANDOVER = (
    "Сменный специалист во время приема-передачи пункта (если операция не согласована контролером) "
    "обязан визуально проверить соответствие объекта выданной сумме. "
    "В случае своего согласия поставить свою подпись в карточке."
)


def _fixture(value: str):
    fact = SourceFact("mixed", "Категория", "Порядок", value,
                      "doc_id=synthetic;table=1;row=2;column=2")
    lesson = LessonDraft("mixed", "", "", "", "", (fact.fact_id,), (), 1)
    return lesson, fact


def test_rejection_family_does_not_hide_other_actually_assessed_handover_steps() -> None:
    lesson, fact = _fixture(REJECTION + " " + HANDOVER)
    axes = derive_assessment_axes(lesson, [fact], block_id="mixed")
    assert len(axes) == 7
    signature = next(axis for axis in axes if axis.correct_value == "поставить свою подпись в карточке")
    assert "во время приема-передачи пункта" in signature.required_prompt
    assert "если операция не согласована контролером" in signature.required_prompt
    assert not has_partial_unatomized_source_contract(fact)


def test_unknown_prefix_or_suffix_of_mixed_known_steps_remains_partial() -> None:
    for value in (
        "При получении запроса проверяется дополнительное неизвестное условие. " + REJECTION + " " + HANDOVER,
        REJECTION + " " + HANDOVER + " Порог дополнительной проверки составляет 37 единиц.",
    ):
        _lesson, fact = _fixture(value)
        assert has_partial_unatomized_source_contract(fact)


def test_one_sentence_family_does_not_suppress_a_different_sibling_condition() -> None:
    first = "Эксперт не вправе продлевать действие договора, если обязательное согласование отсутствует."
    second = ("Если к моменту проверки обязательство полностью исполнено и выданное имущество "
              "возвращено владельцу, то отметка о согласовании не проставляется.")
    lesson, fact = _fixture(first + " " + second)
    axes = derive_assessment_axes(lesson, [fact], block_id="families")
    assert len(axes) == 2
    assert {axis.correct_value.rstrip(".") for axis in axes} == {
        "не вправе продлевать действие договора",
        "отметка о согласовании не проставляется",
    }
    assert any("полностью исполнено и выданное имущество возвращено владельцу" in axis.required_prompt for axis in axes)
    assert not has_partial_unatomized_source_contract(fact)


def test_deadline_target_does_not_consume_an_independent_same_sentence_action() -> None:
    phone = ("Решение о выполнении операций по данной категории требует предварительного "
             "согласования по телефону, а в дальнейшем в соответствии с п.2.")
    deadline = ("Проверку ответственный специалист производит в первый рабочий день с момента "
                "выдачи операции, а сотрудник архивирует отчет.")
    lesson, fact = _fixture(phone + " " + deadline)
    axes = derive_assessment_axes(lesson, [fact], block_id="deadline-sibling")
    assert any(axis.correct_value == "в первый рабочий день с момента выдачи операции" for axis in axes)
    assert not any("архивирует отчет" in axis.correct_value for axis in axes)
    assert has_partial_unatomized_source_contract(fact)


def test_location_context_does_not_claim_an_independent_header_action() -> None:
    phone = ("Решение о выдаче операции по данной категории требует предварительного "
             "согласования по телефону, а в дальнейшем в соответствии с п.2.")
    branches = ("Контролер проводит регистрацию заявки и проверку по правилам: "
                "- при расположении пункта в пределах города - проверка проводится во время оперативной проверки. "
                "- при расположении пункта вне города - проверка проводится во время комплексной проверки.")
    lesson, fact = _fixture(phone + " " + branches)
    axes = derive_assessment_axes(lesson, [fact], block_id="location-sibling")
    assert not any("регистрацию заявки" in axis.correct_value for axis in axes)
    assert has_partial_unatomized_source_contract(fact)


def test_handover_family_does_not_suppress_an_independent_deadline_sentence() -> None:
    report = "Отдельный отчет специалист обязан представить в первый рабочий день с момента проверки."
    lesson, fact = _fixture(HANDOVER + " " + report)
    axes = derive_assessment_axes(lesson, [fact], block_id="handover-deadline")
    assert any(axis.correct_value == "в первый рабочий день с момента проверки" for axis in axes)


def test_ambiguous_coordinated_deadline_origin_never_becomes_a_numeric_key() -> None:
    phone = ("Решение о выполнении особо значимых документально подтвержденных операций по данной категории "
             "требует предварительного согласования по телефону, а в дальнейшем в соответствии с п.2.")
    deadline = ("Проверку ответственный региональный специалист производит в первый рабочий день "
                "с момента выдачи операции и архивирует отчет.")
    lesson, fact = _fixture(phone + " " + deadline)
    axes = derive_assessment_axes(lesson, [fact], block_id="deadline-origin")
    assert not any("архивирует отчет" in axis.correct_value for axis in axes)
    assert has_partial_unatomized_source_contract(fact)


def test_predicative_parenthetical_is_not_silently_covered_as_nominal_scope() -> None:
    phone = ("Решение о выдаче операции по данной категории требует предварительного "
             "согласования по телефону, а в дальнейшем в соответствии с п.2.")
    for body in (
        "Проверку (а сотрудник архивирует отчет) ответственный специалист производит "
        "в первый рабочий день с момента выдачи операции.",
        "Проверку (а сотрудник регистрирует заявку) Контролер проводит: "
        "- при расположении пункта в пределах города - проверка проводится во время оперативной проверки. "
        "- при расположении пункта вне города - проверка проводится во время комплексной проверки.",
    ):
        lesson, fact = _fixture(phone + " " + body)
        axes = derive_assessment_axes(lesson, [fact], block_id="parenthetical-predicate")
        assert not any("сотрудник архивирует" in axis.correct_value or "сотрудник регистрирует" in axis.correct_value for axis in axes)
        assert has_partial_unatomized_source_contract(fact)


def test_preliminary_decision_question_is_distinct_from_later_full_approval() -> None:
    value = ("Если выдача производится после 18:00 часов, в выходные или праздничные дни, "
             "то решение о выдаче операции должно быть предварительно согласовано по телефону. "
             "Согласование операции контролер производит в первый рабочий день с момента выдачи операции.")
    lesson, fact = _fixture(value)
    axes = derive_assessment_axes(lesson, [fact], block_id="two-stage")
    decision = next(axis for axis in axes if "предварительно" in axis.correct_value)
    assert "предварительно согласовать решение" in decision.required_prompt
    assert "характеристике" not in decision.required_prompt
    assert "после 18:00 часов, в выходные или праздничные дни" in decision.required_prompt


def test_modal_parenthetical_is_not_erased_from_deadline_or_location_coverage() -> None:
    phone = ("Решение о выдаче операции по данной категории требует предварительного "
             "согласования по телефону, а в дальнейшем в соответствии с п.2.")
    for modal in ("нужно", "требуется", "необходимо", "следует", "надо"):
        for body in (
            f"Проверку (сотруднику {modal} убрать документы) ответственный специалист производит "
            "в первый рабочий день с момента выдачи операции.",
            f"Проверку (сотруднику {modal} убрать документы) Контролер проводит: "
            "- при расположении пункта в пределах города - проверка проводится во время оперативной проверки. "
            "- при расположении пункта вне города - проверка проводится во время комплексной проверки.",
        ):
            _lesson, fact = _fixture(phone + " " + body)
            assert has_partial_unatomized_source_contract(fact), (modal, body)


def test_job_title_noun_is_not_a_modal_action() -> None:
    lesson, fact = _fixture(
        "По окончании рабочего дня должность специалиста указывается в журнале "
        "в соответствии с графиком."
    )
    axes = derive_assessment_axes(lesson, [fact], block_id="job-title")
    assert len(axes) == 1
    assert not any(axis.correct_value.startswith("должность") for axis in axes)


def test_nominal_head_does_not_hide_past_or_passive_parenthetical_clause() -> None:
    phone = ("Решение о выдаче операции по данной категории требует предварительного "
             "согласования по телефону, а в дальнейшем в соответствии с п.2.")
    for context in ("проверка: сотрудник убрал документы",
                    "проверка завершена сотрудником, документы убраны",
                    "проверка сотрудником выполнена"):
        for body in (
            f"Проверку ({context}) ответственный специалист производит "
            "в первый рабочий день с момента выдачи операции.",
            f"Проверку ({context}) Контролер проводит: "
            "- при расположении пункта в пределах города - проверка проводится во время оперативной проверки. "
            "- при расположении пункта вне города - проверка проводится во время комплексной проверки.",
        ):
            _lesson, fact = _fixture(phone + " " + body)
            assert has_partial_unatomized_source_contract(fact), context


def test_a_real_later_deadline_is_not_a_wrong_option_for_an_unqualified_recording_task() -> None:
    lesson, fact = _fixture(
        "Если контролер согласовывает операцию, то согласовавшее лицо подписывает карточку, "
        "а также проставляет отметку в программе учета. "
        "Если выдача производится в выходные, решение должно быть предварительно согласовано по телефону. "
        "Согласование операций и запись в программе учета производят в первый рабочий день."
    )
    axes = derive_assessment_axes(lesson, [fact], block_id="ambiguous-later-step")
    recording = next(axis for axis in axes if axis.correct_value == "проставляет отметку в программе учета")
    ambiguous = AuthoredAssessment(recording.axis_id, recording.required_prompt, (
        "Проставляет отметку в программе учета в первый рабочий день.",
        "Проставляет отметку только в карточке, без записи в программе учета.",
    ))
    assert materialize_assessment(recording, ambiguous) is None
    valid = AuthoredAssessment(recording.axis_id, recording.required_prompt, (
        "Проставляет отметку о несогласовании в программе учета.",
        "Проставляет отметку только в карточке, без записи в программе учета.",
    ))
    assert materialize_assessment(recording, valid) is not None
