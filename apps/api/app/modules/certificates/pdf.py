"""Certificate PDF generation with bundled Unicode fonts."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

import qrcode
from fpdf import FPDF

from app.modules.certificates.schemas import DEFAULT_CERTIFICATE_TEMPLATE, KARLSKRONA_CERTIFICATE_TEMPLATE

FONT_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"
KARLSKRONA_ASSETS = FONT_DIR.parent / "certificates" / "karlskrona"
CERTIFICATE_TEMPLATE_VERSION = DEFAULT_CERTIFICATE_TEMPLATE
SUPPORTED_CERTIFICATE_TEMPLATE_VERSIONS = {"v2", CERTIFICATE_TEMPLATE_VERSION, KARLSKRONA_CERTIFICATE_TEMPLATE}


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


def _wrap_text(pdf: FPDF, text: str, max_width: float) -> list[str]:
    words = _safe_text(text).split()
    if not words:
        return [""]

    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if pdf.get_string_width(candidate) <= max_width:
            current = candidate
            continue

        if current:
            lines.append(current)
            current = ""

        if pdf.get_string_width(word) <= max_width:
            current = word
            continue

        chunk = ""
        for character in word:
            candidate = f"{chunk}{character}"
            if chunk and pdf.get_string_width(candidate) > max_width:
                lines.append(chunk)
                chunk = character
            else:
                chunk = candidate
        current = chunk

    if current:
        lines.append(current)
    return lines


def _fit_lines(
    pdf: FPDF,
    text: str,
    *,
    font_style: str,
    start_size: int,
    min_size: int,
    max_width: float,
    max_lines: int,
    font_family: str = "Ubuntu",
) -> tuple[int, list[str]]:
    for size in range(start_size, min_size - 1, -1):
        pdf.set_font(font_family, font_style, size)
        lines = _wrap_text(pdf, text, max_width)
        if len(lines) <= max_lines:
            return size, lines

    pdf.set_font(font_family, font_style, min_size)
    lines = _wrap_text(pdf, text, max_width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        final = lines[-1]
        while final and pdf.get_string_width(f"{final}…") > max_width:
            final = final[:-1]
        lines[-1] = f"{final.rstrip()}…"
    return min_size, lines


def _draw_fitted_centered(
    pdf: FPDF,
    text: str,
    *,
    y: float,
    max_width: float,
    max_lines: int,
    start_size: int,
    min_size: int,
    line_height: float,
    style: str = "",
) -> float:
    size, lines = _fit_lines(
        pdf,
        text,
        font_style=style,
        start_size=start_size,
        min_size=min_size,
        max_width=max_width,
        max_lines=max_lines,
    )
    pdf.set_font("Ubuntu", style, size)
    pdf.set_y(y)
    x = (pdf.w - max_width) / 2
    for line in lines:
        pdf.set_x(x)
        pdf.cell(max_width, line_height, line, align="C", new_x="LMARGIN", new_y="NEXT")
    return y + len(lines) * line_height


def _draw_fitted_left(
    pdf: FPDF,
    text: str,
    *,
    x: float,
    y: float,
    max_width: float,
    max_lines: int,
    start_size: int,
    min_size: int,
    line_height: float,
    style: str = "",
    font_family: str = "Ubuntu",
) -> float:
    size, lines = _fit_lines(
        pdf,
        text,
        font_style=style,
        start_size=start_size,
        min_size=min_size,
        max_width=max_width,
        max_lines=max_lines,
        font_family=font_family,
    )
    pdf.set_font(font_family, style, size)
    pdf.set_y(y)
    for line in lines:
        pdf.set_x(x)
        pdf.cell(max_width, line_height, line, align="L", new_x="LMARGIN", new_y="NEXT")
    return y + len(lines) * line_height


def _render_certificate_pdf_v2(
    *,
    user_name: str,
    course_title: str,
    certificate_number: str,
    issued_at: datetime,
    organization: str,
    signer_name: str,
    signer_title: str,
    footer_note: str,
    verification_url: str,
) -> bytes:
    """Preserve the renderer used by certificates issued before v3."""
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


def _render_certificate_pdf_v3(
    *,
    user_name: str,
    course_title: str,
    certificate_number: str,
    issued_at: datetime,
    expires_at: datetime | None,
    organization: str,
    signer_name: str,
    signer_title: str,
    footer_note: str,
    verification_url: str,
) -> bytes:
    pdf = CertificatePDF(orientation="L", unit="mm", format="A4")
    _register_fonts(pdf)
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    pdf.set_text_color(30, 58, 138)
    pdf.set_font("Ubuntu", "B", 31)
    pdf.set_y(26)
    pdf.cell(0, 14, "СЕРТИФИКАТ", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Ubuntu", "", 12)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 7, "О ПРОХОЖДЕНИИ КУРСА", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_y(53)
    pdf.set_font("Ubuntu", "", 10)
    pdf.set_text_color(70, 70, 70)
    pdf.cell(0, 6, "Настоящим подтверждается, что", align="C")

    pdf.set_text_color(20, 20, 20)
    _draw_fitted_centered(
        pdf,
        _safe_text(user_name) or "Обучающийся",
        y=64,
        max_width=260,
        max_lines=2,
        start_size=25,
        min_size=16,
        line_height=10,
        style="B",
    )

    pdf.set_y(87)
    pdf.set_font("Ubuntu", "", 10)
    pdf.set_text_color(70, 70, 70)
    pdf.cell(0, 6, "успешно завершил(а) курс", align="C")

    pdf.set_text_color(30, 58, 138)
    _draw_fitted_centered(
        pdf,
        _safe_text(course_title) or "Учебный курс",
        y=98,
        max_width=245,
        max_lines=3,
        start_size=18,
        min_size=12,
        line_height=8,
        style="B",
    )

    pdf.set_font("Ubuntu", "", 8.5)
    pdf.set_text_color(80, 80, 80)
    pdf.set_y(133)
    pdf.set_x(18)
    pdf.cell(82, 6, f"Дата выдачи: {_format_ru_date(issued_at)}", align="C")
    expiry_label = (
        f"Действителен до: {_format_ru_date(expires_at)}"
        if expires_at
        else "Срок действия: бессрочно"
    )
    pdf.cell(92, 6, expiry_label, align="C")
    pdf.cell(
        87,
        6,
        f"Сертификат №: {_safe_text(certificate_number)}",
        align="C",
    )

    pdf.set_text_color(50, 50, 50)
    if signer_name:
        _draw_fitted_left(
            pdf,
            _safe_text(signer_name),
            x=24,
            y=148,
            max_width=202,
            max_lines=2,
            start_size=10,
            min_size=8,
            line_height=5,
        )
    if signer_title:
        _draw_fitted_left(
            pdf,
            _safe_text(signer_title),
            x=24,
            y=159,
            max_width=202,
            max_lines=2,
            start_size=8,
            min_size=7,
            line_height=4,
            style="I",
        )

    pdf.set_text_color(70, 70, 70)
    next_y = _draw_fitted_left(
        pdf,
        f"Выдан: {_safe_text(organization)}",
        x=24,
        y=169,
        max_width=208,
        max_lines=2,
        start_size=8,
        min_size=7,
        line_height=4,
        style="I",
    )
    if footer_note:
        _draw_fitted_left(
            pdf,
            _safe_text(footer_note),
            x=24,
            y=next_y + 1,
            max_width=208,
            max_lines=2,
            start_size=7,
            min_size=6,
            line_height=3.5,
            style="I",
        )

    if verification_url:
        qr = qrcode.make(verification_url)
        qr_buffer = BytesIO()
        qr.save(qr_buffer, format="PNG")
        qr_buffer.seek(0)
        pdf.image(qr_buffer, x=247, y=148, w=25, h=25, link=verification_url)
        pdf.set_font("Ubuntu", "B", 7)
        pdf.set_text_color(30, 58, 138)
        pdf.set_xy(237, 174)
        pdf.cell(45, 4, "Проверить подлинность", align="C", link=verification_url)
        pdf.set_font("Ubuntu", "", 6)
        pdf.set_text_color(90, 90, 90)
        pdf.set_xy(237, 178)
        pdf.cell(45, 3.5, _safe_text(certificate_number), align="C")

    return bytes(pdf.output())


def _render_karlskrona_certificate_pdf(
    *,
    user_name: str,
    course_title: str,
    certificate_number: str,
    issued_at: datetime,
    expires_at: datetime | None,
    organization: str,
    signer_name: str,
    signer_title: str,
    footer_note: str,
    verification_url: str,
) -> bytes:
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.add_font("Roboto", "B", str(KARLSKRONA_ASSETS / "Roboto-Bold.ttf"))
    pdf.add_font("OpenSans", "", str(KARLSKRONA_ASSETS / "OpenSans-Regular.ttf"))
    pdf.set_title("KARLSKRONA Pump Academy | Сертификат")
    pdf.set_creation_date(issued_at)
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    orange = (243, 107, 47)
    charcoal = (37, 36, 35)
    gray = (87, 87, 87)

    pdf.set_fill_color(*orange)
    pdf.rect(0, 0, 5, pdf.h, style="F")
    pdf.set_fill_color(247, 246, 244)
    pdf.rect(21, 147, pdf.w - 42, 34, style="F")
    pdf.set_draw_color(231, 227, 222)
    pdf.set_line_width(0.35)
    for radius in (11, 17, 23):
        pdf.circle(250, 33, radius)
    pdf.set_draw_color(*orange)
    pdf.set_line_width(1.25)
    pdf.line(250, 33, 271, 12)
    pdf.line(21, 42, 276, 42)
    pdf.image(str(KARLSKRONA_ASSETS / "logo.png"), x=21, y=10, w=31)

    def label(x: float, y: float, value: str, *, size: float = 8.5) -> None:
        pdf.set_font("OpenSans", size=size)
        pdf.set_text_color(*gray)
        pdf.set_xy(x, y)
        pdf.cell(text=value)

    def heading(x: float, y: float, value: str, *, size: float) -> None:
        pdf.set_font("Roboto", "B", size)
        pdf.set_text_color(*charcoal)
        pdf.set_xy(x, y)
        pdf.cell(text=value)

    label(59, 17, "KARLSKRONA LC AB")
    heading(59, 25, "PUMP ACADEMY", size=16)
    heading(21, 52, "СЕРТИФИКАТ", size=33)
    label(21, 66, "Курсты аяқтағаны туралы", size=12)

    pdf.set_text_color(*charcoal)
    _draw_fitted_left(
        pdf, user_name or "Білім алушы", x=21, y=79, max_width=252, max_lines=2,
        start_size=28, min_size=16, line_height=10, style="B", font_family="Roboto",
    )
    label(21, 107, "ОҚУ КУРСЫ")
    pdf.set_text_color(*charcoal)
    _draw_fitted_left(
        pdf, course_title or "Оқу курсы", x=21, y=113, max_width=252, max_lines=3,
        start_size=17, min_size=12, line_height=8, style="B", font_family="Roboto",
    )

    for x, field, value in (
        (27, "БЕРІЛГЕН КҮНІ", issued_at.strftime("%d.%m.%Y")),
        (91, "ЖАРАМДЫЛЫҚ МЕРЗІМІ", expires_at.strftime("%d.%m.%Y") if expires_at else "Мерзімсіз"),
        (160, "СЕРТИФИКАТ НӨМІРІ", certificate_number),
    ):
        label(x, 155, field)
        heading(x, 165, _safe_text(value), size=11.5)

    if certificate_number.endswith("-PREVIEW"):
        label(226, 164, "ДЕМО ҮЛГІСІ")
    elif verification_url:
        code = BytesIO()
        qrcode.make(verification_url).save(code, format="PNG")
        code.seek(0)
        pdf.image(code, x=243, y=149, w=23, link=verification_url)
        pdf.set_font("OpenSans", size=7)
        pdf.set_text_color(*gray)
        pdf.set_xy(238, 172)
        pdf.cell(33, 4, "Түпнұсқасын тексеру", align="C", link=verification_url)

    pdf.set_text_color(*gray)
    _draw_fitted_left(
        pdf, f"Берген ұйым: {organization}", x=21, y=184, max_width=127, max_lines=2,
        start_size=8, min_size=7, line_height=3.6, font_family="OpenSans",
    )
    signatory = " · ".join(text for text in (signer_name, signer_title) if text)
    if signatory:
        _draw_fitted_left(
            pdf, signatory, x=151, y=184, max_width=124, max_lines=3,
            start_size=8, min_size=7, line_height=3.6, font_family="OpenSans",
        )
    if footer_note:
        _draw_fitted_left(
            pdf, footer_note, x=21, y=198, max_width=254, max_lines=2,
            start_size=8, min_size=7, line_height=3.6, font_family="OpenSans",
        )
    return bytes(pdf.output())


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
    expires_at: datetime | None = None,
    template_version: str = CERTIFICATE_TEMPLATE_VERSION,
) -> bytes:
    """Render a certificate using the issue-time template version."""
    if template_version == KARLSKRONA_CERTIFICATE_TEMPLATE:
        return _render_karlskrona_certificate_pdf(
            user_name=user_name,
            course_title=course_title,
            certificate_number=certificate_number,
            issued_at=issued_at,
            expires_at=expires_at,
            organization=organization,
            signer_name=signer_name,
            signer_title=signer_title,
            footer_note=footer_note,
            verification_url=verification_url,
        )
    if template_version == "v2":
        return _render_certificate_pdf_v2(
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
    if template_version != CERTIFICATE_TEMPLATE_VERSION:
        raise ValueError(f"Unsupported certificate template version: {template_version}")
    return _render_certificate_pdf_v3(
        user_name=user_name,
        course_title=course_title,
        certificate_number=certificate_number,
        issued_at=issued_at,
        expires_at=expires_at,
        organization=organization,
        signer_name=signer_name,
        signer_title=signer_title,
        footer_note=footer_note,
        verification_url=verification_url,
    )


def certificate_storage_key(
    tenant_id: str,
    cert_id: str,
    template_version: str = CERTIFICATE_TEMPLATE_VERSION,
) -> str:
    return f"{tenant_id}/{cert_id}-{template_version}.pdf"


def store_certificate_pdf(
    pdf_bytes: bytes,
    *,
    cert_id: str,
    tenant_id: str,
    template_version: str = CERTIFICATE_TEMPLATE_VERSION,
) -> str:
    from app.core.storage import get_storage

    key = certificate_storage_key(tenant_id, cert_id, template_version)
    get_storage().put_bytes(key, pdf_bytes, content_type="application/pdf")
    return key


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
    expires_at: datetime | None = None,
    template_version: str = CERTIFICATE_TEMPLATE_VERSION,
) -> str:
    pdf_bytes = render_certificate_pdf(
        user_name=user_name,
        course_title=course_title,
        certificate_number=certificate_number,
        issued_at=issued_at,
        expires_at=expires_at,
        organization=organization,
        signer_name=signer_name,
        signer_title=signer_title,
        footer_note=footer_note,
        verification_url=verification_url,
        template_version=template_version,
    )
    return store_certificate_pdf(
        pdf_bytes,
        cert_id=cert_id,
        tenant_id=tenant_id,
        template_version=template_version,
    )


def read_certificate_pdf(
    tenant_id: str,
    cert_id: str,
    template_version: str = CERTIFICATE_TEMPLATE_VERSION,
) -> bytes | None:
    from app.core.storage import get_storage

    return get_storage().get_bytes(certificate_storage_key(tenant_id, cert_id, template_version))
