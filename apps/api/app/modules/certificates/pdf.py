"""Certificate PDF generation — pure-Python (fpdf2)."""
import logging
from datetime import datetime

from fpdf import FPDF

logger = logging.getLogger(__name__)


class CertificatePDF(FPDF):
    """Simple A4 landscape certificate."""

    def header(self):
        # Decorative top border
        self.set_draw_color(30, 58, 138)  # primary blue
        self.set_line_width(1.5)
        self.line(15, 15, 282, 15)
        self.set_line_width(0.5)
        self.line(15, 18, 282, 18)

    def footer(self):
        self.set_y(-20)
        self.set_draw_color(30, 58, 138)
        self.set_line_width(0.5)
        self.line(15, 280, 282, 280)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 5, "Kamilya LMS - Certificate of Completion", align="C")


def _safe_text(text: str) -> str:
    """Strip non-latin-1 chars for Helvetica core font. Cyrillic is transliterated.

    For MVP, we transliterate cyrillic -> latin to keep pure-Python deps.
    Also handles common non-latin-1 punctuation (№, —, etc.) by ascii fallback.
    """
    # Cyrillic transliteration
    translit_map = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    # Non-latin-1 punctuation (CP1252-safe fallback to ASCII)
    punct_map = {
        "№": "No.",  # numero sign
        "—": "-",   # em dash
        "–": "-",   # en dash
        """: '"',  # left double quote
        """: '"',  # right double quote
        "'": "'",   # left single quote
        "'": "'",   # right single quote
        "…": "...", # ellipsis
    }
    out = []
    for ch in text:
        if ch in punct_map:
            out.append(punct_map[ch])
            continue
        lower = ch.lower()
        if lower in translit_map:
            out.append(translit_map[lower].upper() if ch.isupper() else translit_map[lower])
        else:
            out.append(ch)
    return "".join(out)


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
    """Render certificate as PDF bytes. Uses Helvetica + transliteration for Cyrillic."""
    pdf = CertificatePDF(orientation="L", unit="mm", format="A4")
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 36)
    pdf.set_text_color(30, 58, 138)
    pdf.ln(20)
    pdf.cell(0, 18, "CERTIFICATE", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 14)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 8, "OF COMPLETION", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(15)

    # Body
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(0, 8, "This is to certify that", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5)

    # Name
    pdf.set_font("Helvetica", "B", 28)
    pdf.set_text_color(20, 20, 20)
    pdf.cell(0, 14, _safe_text(user_name) or "Student", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5)

    # Course intro
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(0, 8, "has successfully completed the course", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5)

    # Course title
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(30, 58, 138)
    pdf.cell(0, 12, _safe_text(course_title) or "Course", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(20)

    # Details row: date, number
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(80, 80, 80)

    date_str = issued_at.strftime("%B %d, %Y")
    pdf.cell(95, 6, f"Date: {date_str}", align="C")
    pdf.cell(95, 6, f"Certificate {_safe_text('№')}: {_safe_text(certificate_number)}", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(15)
    if signer_name or signer_title:
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(50, 50, 50)
        pdf.cell(0, 6, _safe_text(signer_name), align="C", new_x="LMARGIN", new_y="NEXT")
        if signer_title:
            pdf.set_font("Helvetica", "I", 9)
            pdf.cell(0, 5, _safe_text(signer_title), align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)

    pdf.set_font("Helvetica", "I", 9)
    footer = f"Issued by {_safe_text(organization)}"
    if verification_url:
        footer += f" - Verify: {_safe_text(verification_url)}"
    pdf.cell(
        0,
        5,
        footer,
        align="C",
    )
    if footer_note:
        pdf.ln(5)
        pdf.cell(0, 5, _safe_text(footer_note), align="C")

    return bytes(pdf.output())


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
    """Render and upload PDF to the active storage backend. Returns the storage key."""
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
    key = f"{tenant_id}/{cert_id}.pdf"
    get_storage().put_bytes(key, pdf_bytes, content_type="application/pdf")
    return key


def read_certificate_pdf(tenant_id: str, cert_id: str) -> bytes | None:
    """Read PDF bytes from the active storage backend. None if missing."""
    from app.core.storage import get_storage
    key = f"{tenant_id}/{cert_id}.pdf"
    return get_storage().get_bytes(key)
