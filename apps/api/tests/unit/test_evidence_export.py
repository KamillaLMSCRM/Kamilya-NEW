from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import UTC, datetime

from pypdf import PdfReader

from app.modules.evidence_export import (
    AssignmentEvidence,
    AttemptEvidence,
    ConfirmationEvidence,
    CourseEvidence,
    EmployeeEvidence,
    GroupEvidenceInput,
    GroupRecordEvidence,
    IndividualEvidenceInput,
    ProcedureEvidence,
    TenantEvidence,
    build_group_evidence_package,
    build_individual_evidence_package,
    canonical_json_bytes,
    render_group_protocol_pdf,
    render_individual_act_pdf,
)

MOJIBAKE_MARKERS = ("\u0420\u0402", "\u0420\u0405", "\u0421\u0453")


def _individual() -> IndividualEvidenceInput:
    return IndividualEvidenceInput(
        tenant=TenantEvidence(id="tenant-1", name="ТОО Ломбард Сандык", slug="sandyq"),
        employee=EmployeeEvidence(
            id="employee-1",
            full_name="Әлия Ахметова",
            email="aliya@example.kz",
            personnel_number="EMP-007",
            department="Отдел микрокредитования",
            position="Эксперт-оценщик",
        ),
        procedure=ProcedureEvidence(
            type="knowledge_check",
            title="Проверка знаний правил предоставления микрокредитов",
            code="MICRO-2025",
            version="2.0",
            purpose="Подтвердить знание внутреннего порядка работы с заемщиком.",
        ),
        course=CourseEvidence(
            id="course-1",
            title="Правила предоставления микрокредитов",
            delivery_type="native",
            release_id="release-1",
            release_version=3,
            release_sha256="a" * 64,
        ),
        assignment=AssignmentEvidence(
            enrollment_id="enrollment-1",
            source="position",
            assigned_at=datetime(2026, 7, 31, 8, 0, tzinfo=UTC),
            group_or_rule="Эксперт-оценщик",
        ),
        attempts=[
            AttemptEvidence(
                id="attempt-1",
                quiz_id="quiz-1",
                started_at=datetime(2026, 7, 31, 9, 0, tzinfo=UTC),
                completed_at=datetime(2026, 7, 31, 9, 20, tzinfo=UTC),
                time_spent_seconds=1200,
                threshold_percent=80,
                score_percent=90,
                total_points=10,
                earned_points=9,
                passed=True,
                answers=[{"question_id": "q-1", "answer": "a", "is_correct": True}],
            )
        ],
        confirmation=ConfirmationEvidence(
            confirmed=True,
            method="otp",
            confirmed_at=datetime(2026, 7, 31, 9, 21, tzinfo=UTC),
            statement="Подтверждаю ознакомление с результатом.",
            actor="Әлия Ахметова",
            evidence_reference="event-1",
        ),
        generated_at=datetime(2026, 7, 31, 9, 22, tzinfo=UTC),
    )


def test_canonical_json_is_deterministic_and_preserves_cyrillic():
    first = {"z": "Әлия", "a": {"b": 2, "a": 1}}
    second = {"a": {"a": 1, "b": 2}, "z": "Әлия"}
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert "Әлия".encode() in canonical_json_bytes(first)


def test_individual_package_contains_hashable_zip_and_full_manifest():
    package = build_individual_evidence_package(_individual())
    with zipfile.ZipFile(io.BytesIO(package.zip_bytes)) as archive:
        names = archive.namelist()
        assert names == ["individual-act.pdf", "manifest.json", "manifest.sha256"]
        manifest_bytes = archive.read("manifest.json")
        assert hashlib.sha256(manifest_bytes).hexdigest() == package.manifest_sha256
        assert archive.read("manifest.sha256").decode().startswith(package.manifest_sha256)
        pdf_bytes = archive.read("individual-act.pdf")
        assert hashlib.sha256(pdf_bytes).hexdigest() == package.manifest["artifacts"][0]["sha256"]
        assert pdf_bytes.startswith(b"%PDF")
    assert package.manifest["employee"]["full_name"] == "Әлия Ахметова"
    assert package.manifest["attempts"][0]["answers"]


def test_same_input_produces_same_zip_bytes():
    first = build_individual_evidence_package(_individual())
    second = build_individual_evidence_package(_individual())
    assert first.manifest_bytes == second.manifest_bytes
    assert first.zip_bytes == second.zip_bytes


def test_public_package_minimizes_personal_data_and_omits_answers():
    package = build_individual_evidence_package(_individual(), public=True)
    employee = package.manifest["employee"]
    assert employee == {"display_name": "Сотрудник"}
    assert package.manifest["tenant"] == {"name": "ТОО Ломбард Сандык"}
    assert "enrollment_id" not in package.manifest["assignment"]
    assert "id" not in package.manifest["course"]
    assert "answers" not in package.manifest["attempts"][0]
    assert "email" not in package.manifest
    assert package.manifest["confirmation"]["method_note"] == "Одноразовый код (OTP), не ЭЦП."


def test_cyrillic_regression_has_normal_text_and_no_mojibake():
    package = build_individual_evidence_package(_individual(), public=True)
    with zipfile.ZipFile(io.BytesIO(package.zip_bytes)) as archive:
        manifest_text = archive.read("manifest.json").decode("utf-8")
        pdf_text = "\n".join(
            page.extract_text() or "" for page in PdfReader(io.BytesIO(archive.read("individual-act.pdf"))).pages
        )

    combined_text = f"{manifest_text}\n{pdf_text}"
    for expected in ("Акт результата обучения", "Сотрудник", "Одноразовый код"):
        assert expected in combined_text
    for marker in MOJIBAKE_MARKERS:
        assert marker not in combined_text


def test_long_text_and_cyrillic_render_as_pdf():
    data = _individual()
    data.procedure.purpose = "Очень длинное описание процедуры с кириллицей. " * 60
    pdf = render_individual_act_pdf(data)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1_000
    reader = PdfReader(io.BytesIO(pdf))
    assert "Акт результата обучения" in "\n".join(page.extract_text() or "" for page in reader.pages)


def test_individual_pdf_uses_human_labels_and_kazakhstan_dates():
    data = _individual()
    data.assignment.group_or_rule = "position"
    pdf = render_individual_act_pdf(data)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)

    for expected in (
        "Проверка знаний",
        "Встроенный курс Kamilya",
        "По должности",
        "Правило должности",
        "31.07.2026 13:00 (Алматы)",
        "детали включены в архив доказательств",
    ):
        assert expected in text
    for internal_value in ("knowledge_check", "native", "manifest.json", "2026-07-31T08:00"):
        assert internal_value not in text


def test_course_without_quiz_attempts_renders_as_pdf():
    data = _individual()
    data.procedure.type = "training"
    data.attempts = []

    pdf = render_individual_act_pdf(data)

    assert pdf.startswith(b"%PDF")
    text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)
    assert "Попытки не переданы в экспорт" in text


def test_group_protocol_pdf_is_readable():
    individual = _individual()
    group = GroupEvidenceInput(
        tenant=individual.tenant,
        procedure=individual.procedure,
        records=[GroupRecordEvidence(employee=individual.employee, attempts=individual.attempts)],
    )
    reader = PdfReader(io.BytesIO(render_group_protocol_pdf(group)))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Групповой протокол результатов" in text
    assert "Әлия Ахметова" in text
    for expected in ("Проверка знаний", "Сотрудник", "Статус", "Баллы", "Завершено", "Подтверждение", "Решение"):
        assert expected in text
    for internal_value in ("knowledge_check", "employee", "completed", "confirmation", "decision"):
        assert internal_value not in text


def test_answer_count_in_pdf_uses_correct_russian_form():
    data = _individual()
    data.attempts[0].answers = [{"question_id": str(index)} for index in range(5)]
    pdf = render_individual_act_pdf(data)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)
    assert "5 ответов; детали включены в архив доказательств" in text


def test_group_package_includes_only_optional_sections_that_are_passed():
    individual = _individual()
    group = GroupEvidenceInput(
        tenant=individual.tenant,
        procedure=individual.procedure,
        course=individual.course,
        records=[
            GroupRecordEvidence(
                employee=individual.employee,
                assignment=individual.assignment,
                attempts=individual.attempts,
                confirmation=individual.confirmation,
            )
        ],
    )
    package = build_group_evidence_package(group)
    assert "commission" not in package.manifest
    assert "decision" not in package.manifest
    assert package.manifest["records"][0]["employee"]["full_name"] == "Әлия Ахметова"


def test_public_group_package_omits_commission_and_decision():
    individual = _individual()
    group = GroupEvidenceInput(
        tenant=individual.tenant,
        procedure=individual.procedure,
        records=[GroupRecordEvidence(employee=individual.employee, attempts=individual.attempts)],
        commission={"members": ["Комиссия 1"], "basis": "Приказ"},
        decision={"outcome": "Допустить", "decided_by": "Председатель"},
    )
    package = build_group_evidence_package(group, public=True)
    assert "commission" not in package.manifest
    assert "decision" not in package.manifest
