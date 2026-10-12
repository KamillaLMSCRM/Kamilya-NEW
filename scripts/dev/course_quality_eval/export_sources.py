"""Deterministically export synthetic benchmark sources to readable PDFs.

Run with the bundled artifact Python (reportlab), not the API test runtime.
Only the sources are exported: gold answers are never inside input documents.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from scripts.dev.course_quality_eval.benchmark import DEFAULT_SUITE, digest, load_suite


def export(suite: Path, output_dir: Path, font: Path) -> None:
    cases = load_suite(suite)
    output_dir.mkdir(parents=True, exist_ok=False)
    pdfmetrics.registerFont(TTFont("Benchmark", str(font)))
    styles = getSampleStyleSheet()
    body = ParagraphStyle("Source", parent=styles["BodyText"], fontName="Benchmark",
                          fontSize=11, leading=16, spaceAfter=9)
    title = ParagraphStyle("SourceTitle", parent=body, fontSize=18, leading=23, spaceAfter=18)
    cell = ParagraphStyle("Cell", parent=body, fontSize=9, leading=13, spaceAfter=0)
    manifest = []
    for case in cases:
        text_path = output_dir / case["filename"]
        text_path.write_text(case["source"], encoding="utf-8")
        pdf_path = output_dir / f"{case['id']}.pdf"
        story = [Paragraph(html.escape(case["title"]), title)]
        paragraphs = case["source"].split("\n\n")
        for index, paragraph in enumerate(paragraphs):
            if index == 0 and paragraph.strip() == case["title"]:
                continue
            if paragraph.startswith("|"):
                rows = [line.strip().strip("|").split("|") for line in paragraph.splitlines()]
                rows = [row for row in rows if not all(set(value.strip()) <= set("-:") for value in row)]
                table = Table([[Paragraph(html.escape(value.strip()), cell) for value in row] for row in rows],
                              colWidths=[6.5 * inch / len(rows[0])] * len(rows[0]), repeatRows=1)
                table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E4EAF0")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D9D9D9")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]))
                story.extend([table, Spacer(1, 12)])
            else:
                story.append(Paragraph(html.escape(paragraph).replace("\n", "<br/>"), body))
        SimpleDocTemplate(str(pdf_path), pagesize=(8.5 * inch, 11 * inch),
                          leftMargin=inch, rightMargin=inch, topMargin=0.7 * inch,
                          bottomMargin=0.7 * inch, title=case["title"], author="Kamilya QA").build(story)
        manifest.append({"case": case["id"], "source": text_path.name,
                         "source_sha256": digest(text_path), "pdf": pdf_path.name,
                         "pdf_sha256": digest(pdf_path), "gold_inside_pdf": False})
    (output_dir / "manifest.json").write_text(json.dumps({
        "suite_sha256": digest(suite), "files": manifest,
        "conversion_acceptance": "NOT_TESTED", "visual_review": "PENDING",
    }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    cli.add_argument("--output-dir", type=Path, required=True)
    cli.add_argument("--font", type=Path, default=Path("C:/Windows/Fonts/arial.ttf"))
    args = cli.parse_args()
    export(args.suite, args.output_dir, args.font)
