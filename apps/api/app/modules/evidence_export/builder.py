"""Deterministic evidence manifests, PDFs and ZIP packages."""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from zoneinfo import ZoneInfo

from fpdf import FPDF

from app.modules.evidence_export.schemas import (
    AttemptEvidence,
    GroupEvidenceInput,
    GroupRecordEvidence,
    IndividualEvidenceInput,
)

FONT_DIR = __import__("pathlib").Path(__file__).resolve().parents[2] / "assets" / "fonts"
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
_PDF_EPOCH = datetime(1980, 1, 1, tzinfo=UTC)
_KAZAKHSTAN_TIMEZONE = ZoneInfo("Asia/Almaty")
_PROCEDURE_TYPE_LABELS = {
    "training": "Обучение",
    "knowledge_check": "Проверка знаний",
    "acknowledgement": "Ознакомление",
    "internal_attestation": "Внутренняя аттестация",
    "admission_decision": "Решение о допуске",
}
_PROCEDURE_PURPOSE_LABELS = {
    "course_completion": "Завершение курса",
    "quiz_completion": "Завершение тестирования",
}
_DELIVERY_TYPE_LABELS = {
    "native": "Встроенный курс Kamilya",
    "scorm_1_2": "SCORM 1.2",
}
_ASSIGNMENT_SOURCE_LABELS = {
    "manual": "Вручную",
    "cohort": "По группе сотрудников",
    "department": "По подразделению",
    "position": "По должности",
    "learning_path": "По программе обучения",
    "recurring": "По периодическому правилу",
}
_ASSIGNMENT_RULE_LABELS = {
    "manual": "Прямое назначение",
    "cohort": "Правило группы сотрудников",
    "department": "Правило подразделения",
    "position": "Правило должности",
    "learning_path": "Программа обучения",
    "recurring": "Периодическое правило",
}


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON with stable key ordering and UTF-8 Cyrillic support."""
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_text(value: Any) -> str:
    """Remove PDF-hostile controls without interpreting tenant text as markup."""
    text = "" if value is None else str(value)
    return _CONTROL_CHARS.sub("", text).replace("\r\n", "\n").replace("\r", "\n")


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _human_datetime(value: Any) -> str | None:
    if value is None or value == "":
        return None
    parsed = value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if not isinstance(parsed, datetime):
        return str(parsed)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    local = parsed.astimezone(_KAZAKHSTAN_TIMEZONE)
    return f"{local:%d.%m.%Y %H:%M} (Алматы)"


def _human_label(value: Any, labels: dict[str, str]) -> Any:
    if value is None:
        return None
    return labels.get(str(value), value)


def _answer_count_text(count: int) -> str:
    last_two = count % 100
    last = count % 10
    if last == 1 and last_two != 11:
        noun = "ответ"
    elif last in {2, 3, 4} and last_two not in {12, 13, 14}:
        noun = "ответа"
    else:
        noun = "ответов"
    return f"{count} {noun}; детали включены в архив доказательств"


def _public_employee(employee: dict[str, Any]) -> dict[str, Any]:
    return {"display_name": "Сотрудник"}


def _public_attempt(attempt: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "completed_at",
        "threshold_percent",
        "score_percent",
        "passed",
    )
    return {key: attempt[key] for key in allowed if key in attempt}


def _public_confirmation(confirmation: dict[str, Any]) -> dict[str, Any]:
    result = {key: confirmation[key] for key in ("confirmed", "method", "confirmed_at") if key in confirmation}
    if result.get("method") == "otp":
        result["method_note"] = "Одноразовый код (OTP), не ЭЦП."
    return result


def _public_assignment(assignment: dict[str, Any]) -> dict[str, Any]:
    return {key: assignment[key] for key in ("source", "assigned_at", "due_at") if key in assignment}


def _public_course(course: dict[str, Any]) -> dict[str, Any]:
    return {
        key: course[key] for key in ("title", "delivery_type", "release_version", "release_sha256") if key in course
    }


def _publicize(manifest: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(canonical_json_bytes(manifest).decode("utf-8"))
    if "tenant" in result:
        result["tenant"] = {"name": result["tenant"].get("name", "")}
    if result.get("course"):
        result["course"] = _public_course(result["course"])
    if result.get("assignment"):
        result["assignment"] = _public_assignment(result["assignment"])
    if "employee" in result:
        result["employee"] = _public_employee(result["employee"])
    if "records" in result:
        for record in result["records"]:
            record["employee"] = _public_employee(record["employee"])
            if record.get("assignment"):
                record["assignment"] = _public_assignment(record["assignment"])
            record["attempts"] = [_public_attempt(item) for item in record.get("attempts", [])]
            if record.get("confirmation"):
                record["confirmation"] = _public_confirmation(record["confirmation"])
            record.pop("corrections", None)
            record.pop("decision", None)
    else:
        result["attempts"] = [_public_attempt(item) for item in result.get("attempts", [])]
        if result.get("confirmation"):
            result["confirmation"] = _public_confirmation(result["confirmation"])
        result.pop("corrections", None)
    result.pop("commission", None)
    result.pop("decision", None)
    result["public_mode"] = True
    return result


def _base_manifest(input_data: IndividualEvidenceInput | GroupEvidenceInput, package_type: str) -> dict[str, Any]:
    payload = input_data.model_dump(mode="json", exclude_none=True)
    payload.pop("generated_at", None)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "package_type": package_type,
        "public_mode": False,
        **payload,
    }
    generated_at = _iso(input_data.generated_at)
    if generated_at is not None:
        manifest["generated_at"] = generated_at
    return manifest


def _register_fonts(pdf: FPDF) -> None:
    pdf.add_font("Ubuntu", "", str(FONT_DIR / "Ubuntu-R.ttf"))
    pdf.add_font("Ubuntu", "B", str(FONT_DIR / "Ubuntu-B.ttf"))
    pdf.add_font("Ubuntu", "I", str(FONT_DIR / "Ubuntu-RI.ttf"))


class _EvidencePDF(FPDF):
    def header(self) -> None:
        self.set_draw_color(30, 58, 138)
        self.set_line_width(0.6)
        self.line(15, 14, self.w - 15, 14)

    def footer(self) -> None:
        self.set_y(-14)
        self.set_draw_color(30, 58, 138)
        self.line(15, self.h - 12, self.w - 15, self.h - 12)
        self.set_font("Ubuntu", "I", 7)
        self.set_text_color(100, 100, 100)
        self.cell(0, 5, "Kamilya LMS · доказательственный пакет · не специальная форма НПА", align="C")


def _new_pdf(creation_date: datetime | None = None) -> _EvidencePDF:
    pdf = _EvidencePDF(orientation="P", unit="mm", format="A4")
    _register_fonts(pdf)
    pdf.set_creation_date(creation_date or _PDF_EPOCH)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    pdf.set_margins(18, 20, 18)
    return pdf


def _heading(pdf: FPDF, title: str, level: int = 1) -> None:
    pdf.ln(5 if level == 1 else 2)
    pdf.set_text_color(30, 58, 138)
    pdf.set_font("Ubuntu", "B", 15 if level == 1 else 11)
    pdf.multi_cell(
        0,
        7 if level == 1 else 5,
        _safe_text(title),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_text_color(30, 30, 30)


def _paragraph(pdf: FPDF, text: str, *, italic: bool = False) -> None:
    pdf.set_font("Ubuntu", "I" if italic else "", 9)
    pdf.set_text_color(70, 70, 70 if italic else 30)
    pdf.multi_cell(0, 5, _safe_text(text), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(30, 30, 30)


def _field(pdf: FPDF, label: str, value: Any) -> None:
    if value is None or value == "":
        return
    pdf.set_font("Ubuntu", "B", 9)
    pdf.set_text_color(60, 60, 60)
    pdf.write(5, _safe_text(f"{label}: "))
    pdf.set_font("Ubuntu", "", 9)
    pdf.set_text_color(30, 30, 30)
    pdf.multi_cell(0, 5, _safe_text(value), new_x="LMARGIN", new_y="NEXT")


def _attempt_lines(attempt: AttemptEvidence) -> list[tuple[str, Any]]:
    return [
        ("Попытка", attempt.id),
        ("Завершена", _human_datetime(attempt.completed_at)),
        ("Порог", f"{attempt.threshold_percent}%" if attempt.threshold_percent is not None else None),
        ("Результат", f"{attempt.score_percent}%" if attempt.score_percent is not None else None),
        ("Итог", "Пройдено" if attempt.passed is True else "Не пройдено" if attempt.passed is False else None),
        ("Время", f"{attempt.time_spent_seconds} сек." if attempt.time_spent_seconds is not None else None),
    ]


def render_individual_act_pdf(input_data: IndividualEvidenceInput, *, public: bool = False) -> bytes:
    """Render a readable individual result act; it is not an NPA special form."""
    pdf = _new_pdf(input_data.generated_at)
    data = input_data.model_dump(mode="json", exclude_none=True)
    employee = data["employee"]
    tenant = data["tenant"]
    procedure = data["procedure"]
    course = data.get("course")
    if public:
        employee = _public_employee(employee)

    pdf.set_font("Ubuntu", "B", 20)
    pdf.set_text_color(30, 58, 138)
    pdf.cell(0, 10, "Акт результата обучения", new_x="LMARGIN", new_y="NEXT")
    _paragraph(
        pdf,
        "Документ фиксирует результат внутренней процедуры в Kamilya LMS. Он не заменяет специальную форму, аттестацию или иной документ, установленный НПА.",
        italic=True,
    )

    _heading(pdf, "1. Организация и процедура")
    _field(pdf, "Организация", tenant.get("name"))
    _field(pdf, "Процедура", procedure.get("title"))
    _field(pdf, "Тип процедуры", _human_label(procedure.get("type"), _PROCEDURE_TYPE_LABELS))
    _field(
        pdf, "Код / версия", " / ".join(str(item) for item in (procedure.get("code"), procedure.get("version")) if item)
    )
    _field(pdf, "Назначение", _human_label(procedure.get("purpose"), _PROCEDURE_PURPOSE_LABELS))

    _heading(pdf, "2. Сотрудник")
    _field(pdf, "ФИО", employee.get("display_name") or employee.get("full_name"))
    if not public:
        _field(pdf, "Email", employee.get("email"))
        _field(pdf, "Табельный номер", employee.get("personnel_number"))
        _field(pdf, "Подразделение", employee.get("department"))
        _field(pdf, "Должность", employee.get("position"))

    if course:
        _heading(pdf, "3. Курс и публикация")
        _field(pdf, "Курс", course.get("title"))
        _field(pdf, "Формат", _human_label(course.get("delivery_type"), _DELIVERY_TYPE_LABELS))
        _field(pdf, "Версия публикации", course.get("release_version"))
        _field(pdf, "Хэш публикации SHA-256", course.get("release_sha256"))

    section_number = 4 if course else 3
    if data.get("assignment"):
        _heading(pdf, f"{section_number}. Назначение")
        assignment = data["assignment"]
        _field(pdf, "Источник", _human_label(assignment.get("source"), _ASSIGNMENT_SOURCE_LABELS))
        _field(pdf, "Назначено", _human_datetime(assignment.get("assigned_at")))
        _field(pdf, "Срок", _human_datetime(assignment.get("due_at")))
        _field(
            pdf,
            "Правило / группа",
            _human_label(assignment.get("group_or_rule"), _ASSIGNMENT_RULE_LABELS),
        )
        section_number += 1

    _heading(pdf, f"{section_number}. Попытки и результат")
    attempts = (
        input_data.attempts
        if not public
        else [AttemptEvidence.model_validate(_public_attempt(item)) for item in input_data.attempts]
    )
    if attempts:
        for index, attempt in enumerate(attempts, 1):
            _heading(pdf, f"Попытка {index}", level=2)
            for label, value in _attempt_lines(attempt):
                _field(pdf, label, value)
            if not public and attempt.answers:
                _field(
                    pdf,
                    "Ответы",
                    _answer_count_text(len(attempt.answers)),
                )
    else:
        _paragraph(pdf, "Попытки не переданы в экспорт.")
    section_number += 1

    if data.get("confirmation"):
        _heading(pdf, f"{section_number}. Подтверждение")
        confirmation = data["confirmation"]
        _field(pdf, "Статус", "Подтверждено" if confirmation.get("confirmed") else "Не подтверждено")
        method = confirmation.get("method")
        method_text = "Одноразовый код (OTP), не ЭЦП." if method == "otp" else method
        _field(pdf, "Способ", method_text)
        _field(pdf, "Дата", _human_datetime(confirmation.get("confirmed_at")))
        if not public:
            _field(pdf, "Текст подтверждения", confirmation.get("statement"))
            _field(pdf, "Ссылка на событие", confirmation.get("evidence_reference"))
        section_number += 1

    if not public and data.get("corrections"):
        _heading(pdf, f"{section_number}. Коррекции и аннулирование")
        for correction in data["corrections"]:
            _field(pdf, correction.get("kind", "Запись"), correction.get("reason"))
            _field(pdf, "Дата", _human_datetime(correction.get("recorded_at")))
            _field(pdf, "Замещает хэш", correction.get("supersedes_sha256"))
        section_number += 1

    if not public and data.get("state"):
        state = data["state"]
        _heading(pdf, f"{section_number}. Состояние доказательства")
        _field(pdf, "Активная запись", state.get("active_event_id"))
        _field(pdf, "Тип активной записи", state.get("active_record_type"))
        _field(pdf, "Аннулировано", "Да" if state.get("revoked") else "Нет")
        _field(
            pdf,
            "Юридическое удержание",
            "Активно" if state.get("legal_hold_active") else "Не активно",
        )
        for hold in data.get("legal_holds", []):
            action = "Установлено" if hold.get("action") == "placed" else "Снято"
            _field(pdf, action, hold.get("reason"))
            _field(pdf, "Дата", _human_datetime(hold.get("occurred_at")))
            _field(pdf, "Ответственный", hold.get("acted_by"))
        section_number += 1

    if not public and data.get("commission"):
        _heading(pdf, f"{section_number}. Комиссия")
        commission = data["commission"]
        _field(pdf, "Члены", "; ".join(commission.get("members", [])))
        _field(pdf, "Основание", commission.get("basis"))
        _field(pdf, "Дата назначения", _human_datetime(commission.get("appointed_at")))
        section_number += 1

    if not public and data.get("decision"):
        _heading(pdf, f"{section_number}. Решение")
        decision = data["decision"]
        _field(pdf, "Результат", decision.get("outcome"))
        _field(pdf, "Дата", _human_datetime(decision.get("decided_at")))
        _field(pdf, "Принял", decision.get("decided_by"))
        _field(pdf, "Обоснование", decision.get("rationale"))

    return bytes(pdf.output())


def _record_summary(record: GroupRecordEvidence, *, public: bool) -> dict[str, Any]:
    employee = record.employee.model_dump(mode="json", exclude_none=True)
    latest = record.attempts[-1] if record.attempts else None
    return {
        "employee": _public_employee(employee) if public else employee,
        "status": (
            "Пройдено"
            if latest and latest.passed is True
            else "Не пройдено"
            if latest and latest.passed is False
            else "Нет результата"
        ),
        "score_percent": latest.score_percent if latest else None,
        "completed_at": _human_datetime(latest.completed_at) if latest else None,
        "confirmed": record.confirmation.confirmed if record.confirmation else None,
        "decision": (
            record.decision.model_dump(mode="json", exclude_none=True) if record.decision and not public else None
        ),
    }


def render_group_protocol_pdf(input_data: GroupEvidenceInput, *, public: bool = False) -> bytes:
    """Render a compact group protocol from supplied records only."""
    pdf = _new_pdf(input_data.generated_at)
    data = input_data.model_dump(mode="json", exclude_none=True)
    pdf.set_font("Ubuntu", "B", 20)
    pdf.set_text_color(30, 58, 138)
    pdf.cell(0, 10, "Групповой протокол результатов", new_x="LMARGIN", new_y="NEXT")
    _paragraph(
        pdf,
        "Протокол сформирован из переданных записей Kamilya LMS. Он не является специальной формой, установленной НПА.",
        italic=True,
    )
    _heading(pdf, "Процедура")
    _field(pdf, "Организация", data["tenant"]["name"])
    _field(pdf, "Процедура", data["procedure"]["title"])
    _field(pdf, "Тип", _human_label(data["procedure"]["type"], _PROCEDURE_TYPE_LABELS))
    if data.get("course"):
        _field(pdf, "Курс", data["course"].get("title"))
        _field(pdf, "Версия публикации", data["course"].get("release_version"))

    _heading(pdf, "Результаты сотрудников")
    headers = ["Сотрудник", "Статус", "Баллы", "Завершено", "Подтверждение"]
    pdf.set_font("Ubuntu", "B", 8)
    if public:
        widths = [48, 29, 18, 43, 36]
    else:
        headers.append("Решение")
        widths = [40, 24, 16, 34, 29, 31]
    pdf.set_fill_color(232, 238, 250)
    for header, width in zip(headers, widths, strict=True):
        pdf.cell(width, 8, header, border=1, fill=True, align="C")
    pdf.ln()
    for record in input_data.records:
        summary = _record_summary(record, public=public)
        values = [
            summary["employee"].get("display_name") or summary["employee"].get("full_name", ""),
            summary["status"],
            f"{summary['score_percent']}%" if summary["score_percent"] is not None else "—",
            summary["completed_at"] or "—",
            "Да" if summary["confirmed"] else "Нет" if summary["confirmed"] is False else "—",
        ]
        pdf.set_font("Ubuntu", "", 7.5)
        if not public:
            values.append((summary["decision"] or {}).get("outcome") or "-")
        for value, width in zip(values, widths, strict=True):
            pdf.cell(width, 9, _safe_text(value)[:72], border=1, align="C")
        pdf.ln()

    if not public and data.get("commission"):
        _heading(pdf, "Комиссия")
        _field(pdf, "Члены", "; ".join(data["commission"].get("members", [])))
        _field(pdf, "Основание", data["commission"].get("basis"))
    if not public and data.get("decision"):
        _heading(pdf, "Решение")
        _field(pdf, "Результат", data["decision"].get("outcome"))
        _field(pdf, "Обоснование", data["decision"].get("rationale"))
    return bytes(pdf.output())


@dataclass(frozen=True)
class EvidencePackage:
    zip_bytes: bytes
    manifest: dict[str, Any]
    manifest_bytes: bytes
    manifest_sha256: str
    artifact_hashes: dict[str, str]


def _safe_zip_path(path: str) -> str:
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or ".." in candidate.parts or not path.strip():
        raise ValueError(f"Unsafe artifact path: {path!r}")
    return candidate.as_posix()


def _zip_bytes(files: Iterable[tuple[str, bytes]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, content in sorted(files, key=lambda item: item[0]):
            info = zipfile.ZipInfo(_safe_zip_path(path), date_time=_ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, content)
    return output.getvalue()


def _package(manifest: dict[str, Any], artifacts: dict[str, tuple[str, bytes]]) -> EvidencePackage:
    artifact_hashes = {path: sha256_bytes(content) for path, (_, content) in artifacts.items()}
    manifest["artifacts"] = [
        {
            "path": path,
            "media_type": media_type,
            "size": len(content),
            "sha256": artifact_hashes[path],
        }
        for path, (media_type, content) in sorted(artifacts.items())
    ]
    manifest_bytes = canonical_json_bytes(manifest)
    manifest_sha256 = sha256_bytes(manifest_bytes)
    files = {
        "manifest.json": manifest_bytes,
        "manifest.sha256": f"{manifest_sha256}  manifest.json\n".encode("ascii"),
    }
    files.update({path: content for path, (_, content) in artifacts.items()})
    return EvidencePackage(
        zip_bytes=_zip_bytes(files.items()),
        manifest=manifest,
        manifest_bytes=manifest_bytes,
        manifest_sha256=manifest_sha256,
        artifact_hashes=artifact_hashes,
    )


def build_individual_evidence_package(input_data: IndividualEvidenceInput, *, public: bool = False) -> EvidencePackage:
    manifest = _base_manifest(input_data, "individual_result")
    if public:
        manifest = _publicize(manifest)
    pdf = render_individual_act_pdf(input_data, public=public)
    return _package(manifest, {"individual-act.pdf": ("application/pdf", pdf)})


def build_group_evidence_package(input_data: GroupEvidenceInput, *, public: bool = False) -> EvidencePackage:
    manifest = _base_manifest(input_data, "group_protocol")
    if public:
        manifest = _publicize(manifest)
    pdf = render_group_protocol_pdf(input_data, public=public)
    return _package(manifest, {"group-protocol.pdf": ("application/pdf", pdf)})
