"""Generate synthetic-only reference PDFs; no database or tenant credentials."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from app.modules.evidence_export import (  # noqa: E402
    AssignmentEvidence,
    AttemptEvidence,
    CourseEvidence,
    EmployeeEvidence,
    IndividualEvidenceInput,
    PrintFormEvidence,
    ProcedureEvidence,
    TenantEvidence,
    render_completion_form_pdf,
)
from app.modules.evidence_export.form_fields import FORM_FIELD_CATALOG  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    now = datetime(2026, 10, 18, 7, tzinfo=UTC)
    form = PrintFormEvidence(
        title="Подтверждение прохождения курса и тестирования",
        organization_name="ТОО Учебная компания (синтетический пример)",
        intro_text="Документ составлен на вымышленных данных для проверки конструктора.",
        confirmation_text="Подтверждаю ознакомление с материалами курса и самостоятельное прохождение тестирования.",
        employee_signature_label="Подпись сотрудника",
        employee_date_label="Дата подписания",
        representative_signature_label="Подпись представителя организации",
        representative_date_label="Дата проверки",
        representative_name="Ерлан Тестов",
        representative_title="Методист",
        footer_note="Демонстрационный образец. Не является документом реального сотрудника.",
        selected_fields=[item[0] for item in FORM_FIELD_CATALOG],
    )
    sample = IndividualEvidenceInput(
        tenant=TenantEvidence(name=form.organization_name),
        employee=EmployeeEvidence(
            full_name="Әлия Сотрудникова",
            personnel_number="QA-001",
            department="Учебный отдел",
            position="Специалист",
        ),
        procedure=ProcedureEvidence(type="training", title="Прохождение курса"),
        course=CourseEvidence(
            title="Порядок проверки документов и действия при конфликте оснований",
            release_version=3,
        ),
        assignment=AssignmentEvidence(source="manual", assigned_at=now, due_at=now),
        attempts=[
            AttemptEvidence(
                quiz_title="Итоговый тест по проверке документов",
                passed=False,
                score_percent=0,
                threshold_percent=80,
                completed_at=now,
                time_spent_seconds=180,
            ),
            AttemptEvidence(
                quiz_title="Итоговый тест по проверке документов",
                passed=True,
                score_percent=90,
                threshold_percent=80,
                completed_at=now,
                time_spent_seconds=240,
            ),
        ],
        generated_at=now,
        print_form=form,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "completion-form-all-fields.pdf").write_bytes(
        render_completion_form_pdf(sample)
    )
    minimal_form = form.model_copy(
        update={"selected_fields": ["employee_name", "course_title", "test_results"]}
    )
    minimal = sample.model_copy(update={"print_form": minimal_form})
    (args.output_dir / "completion-form-required-fields.pdf").write_bytes(
        render_completion_form_pdf(minimal)
    )
    print("Generated two synthetic completion-form samples.")


if __name__ == "__main__":
    main()
