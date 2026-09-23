"""Rebuild the synthetic text-layer policy PDF used by quality probes."""

from __future__ import annotations

import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas


def main() -> None:
    output = Path(sys.argv[1])
    if output.name != "structured_policy.pdf":
        raise ValueError("Pass the exact structured_policy.pdf fixture path")
    pdfmetrics.registerFont(TTFont("Arial", r"C:\Windows\Fonts\arial.ttf"))
    canvas = Canvas(str(output), pagesize=A4)
    canvas.setTitle("Синтетические правила приёмки товара")
    left = 54
    y = A4[1] - 70
    canvas.setFont("Arial", 18)
    canvas.drawString(left, y, "Приёмка товара")
    y -= 52
    for heading, lines in [
        (
            "1. Проверка документов",
            [
                "Сотрудник сверяет номер накладной с номером заказа до разгрузки.",
                "Если номера не совпадают, разгрузку не начинают и сообщают",
                "руководителю смены.",
            ],
        ),
        (
            "2. Осмотр товара",
            [
                "После сверки документов сотрудник осматривает упаковку.",
                "Повреждение упаковки фиксируют в акте приёмки до подписания",
                "накладной.",
            ],
        ),
    ]:
        canvas.setFont("Arial", 13)
        canvas.drawString(left, y, heading)
        y -= 30
        canvas.setFont("Arial", 11)
        for line in lines:
            canvas.drawString(left, y, line)
            y -= 20
        y -= 28
    canvas.showPage()
    canvas.save()


if __name__ == "__main__":
    main()
