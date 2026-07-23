"""Certificate PDF generation with bundled Unicode fonts."""

import logging
from datetime import datetime
from pathlib import Path

from fpdf import FPDF

logger = logging.getLogger(__name__)

FONT_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"
CERTIFICATE_TEMPLATE_VERSION = "v2"


class CertificatePDF(FPDF):
    """A4 landscape certificate with a restrained corporate layout."""

    def header(self) -> None:
        self.set_draw_color(30, 58, 138)
        self.set_line_width(1.5)
        self.line(15, 15, self.w - 15, 15)
        self.set_line_width(0.5)
        self.line(15, 18, self.w - 15, 18)

    def footer(self) -> None:
        self.set_y(-16)
        self.set_draw_color(30, 58, 138)
        self.set_line_width(0.5)
        self.line(15, self.h - 19, self.w - 15, self.h - 19)
        self.set_font("Ubuntu", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 5, "Kamilya LMS · Сертификат о прохождении курса", align="C")


def _safe_text(text: str) -> str:
    """Normalize unsupported dash variants while preserving Unicode text."""
    return (
        (text or "")
        .replace("\u2011", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )


def _register_fonts(pdf: FPDF) -> None:
    """Use bundled fonts so production output never depends on OS packages."""
    pdf.add_font("Ubuntu", "", str(FONT_DIR / "Ubuntu-R.ttf"))
    pdf.add_font("Ubuntu", "B", str(FONT_DIR / "Ubuntu-B.ttf"))
    pdf.add_font("Ubuntu", "I", str(FONT_DIR / "Ubuntu-RI.ttf"))


def _format_ru_date(value: datetime) -> str:
    months = (
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    )
    return f"{value.day} {months[value.month - 1]} {value.year} г."


def render_certificate_pdf(
    user_name: str,
    course_title: str,
    certificate_number: str,
    issued_at: datetime,
    organization: str = "Kamilya LMS",
    signer_name: str = "",
    signer_title: str = "",
    footer_note: str = "",
    verification_url: str = "",
) -> bytes:
    """Render a Kazakhstan-ready certificate with native Cyrillic text."""
    pdf = CertificatePDF(orientation="L", unit="mm", format="A4")
    _register_fonts(pdf)
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    pdf.set_font("Ubuntu", "B", 33)
    pdf.set_text_color(30, 58, 138)
    pdf.ln(18)
    pdf.cell(0, 16, "СЕРТИФИКАТ", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Ubuntu", "", 13)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 8, "О ПРОХОЖДЕНИИ КУРСА", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(12)
    pdf.set_font("Ubuntu", "", 11)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(0, 7, "Настоящим подтверждается, что", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(4)
    pdf.set_font("Ubuntu", "B", 25)
    pdf.set_text_color(20, 20, 20)
    pdf.cell(
        0,
        13,
        _safe_text(user_name) or "Обучающийся",
        align="C",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    pdf.ln(3)
    pdf.set_font("Ubuntu", "", 11)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(0, 7, "успешно завершил(а) курс", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(3)
    course_text = _safe_text(course_title) or "Учебный курс"
    pdf.set_font("Ubuntu", "B", 18 if len(course_text) <= 70 else 15)
    pdf.set_text_color(30, 58, 138)
    pdf.set_x(26)
    pdf.multi_cell(245, 8, course_text, align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_y(max(pdf.get_y() + 13, 145))
    pdf.set_font("Ubuntu", "", 10)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(135, 6, f"Дата выдачи: {_format_ru_date(issued_at)}", align="C")
    pdf.cell(
        135,
        6,
        f"Сертификат №: {_safe_text(certificate_number)}",
        align="C",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    pdf.ln(9)
    if signer_name or signer_title:
        pdf.set_font("Ubuntu", "", 10)
        pdf.set_text_color(50, 50, 50)
        pdf.cell(0, 6, _safe_text(signer_name), align="C", new_x="LMARGIN", new_y="NEXT")
        if signer_title:
            pdf.set_font("Ubuntu", "I", 9)
            pdf.cell(0, 5, _safe_text(signer_title), align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    pdf.set_font("Ubuntu", "I", 8)
    footer = f"Выдан: {_safe_text(organization)}"
    if verification_url:
        footer += f" · Проверка подлинности: {_safe_text(verification_url)}"
    pdf.cell(0, 5, footer, align="C")
    if footer_note:
        pdf.ln(5)
        pdf.cell(0, 5, _safe_text(footer_note), align="C")

    return bytes(pdf.output())


def certificate_storage_key(tenant_id: str, cert_id: str) -> str:
    """Version keys so already-issued certificates receive template upgrades."""
    return f"{tenant_id}/{cert_id}-{CERTIFICATE_TEMPLATE_VERSION}.pdf"


def write_certificate_pdf(
    cert_id: str,
    tenant_id: str,
    user_name: str,
    course_title: str,
    certificate_number: str,
    issued_at: datetime,
    organization: str = "Kamilya LMS",
    signer_name: str = "",
    signer_title: str = "",
    footer_note: str = "",
    verification_url: str = "",
) -> str:
    """Render and upload PDF to the active storage backend."""
    from app.core.storage import get_storage

    pdf_bytes = render_certificate_pdf(
        user_name=user_name,
        course_title=course_title,
        certificate_number=certificate_number,
        issued_at=issued_at,
        organization=organization,
        signer_name=signer_name,
        signer_title=signer_title,
        footer_note=footer_note,
        verification_url=verification_url,
    )
    key = certificate_storage_key(tenant_id, cert_id)
    get_storage().put_bytes(key, pdf_bytes, content_type="application/pdf")
    return key


def read_certificate_pdf(tenant_id: str, cert_id: str) -> bytes | None:
    """Read the current template version from the active storage backend."""
    from app.core.storage import get_storage

    return get_storage().get_bytes(certificate_storage_key(tenant_id, cert_id))
