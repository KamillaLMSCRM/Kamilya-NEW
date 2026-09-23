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
    if output.name not in {"structured_policy.pdf", "expanded_policy.pdf"}:
        raise ValueError("Pass the exact structured_policy.pdf or expanded_policy.pdf fixture path")
    pdfmetrics.registerFont(TTFont("Arial", r"C:\Windows\Fonts\arial.ttf"))
    canvas = Canvas(str(output), pagesize=A4)
    canvas.setTitle("Синтетические правила приёмки товара")
    left = 54
    y = A4[1] - 70
    canvas.setFont("Arial", 18)
    canvas.drawString(left, y, "Приёмка товара")
    y -= 52
    compact_sections = [
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
    ]
    expanded_sections = [
        (
            "1. Сверка документов",
            [
                "До разгрузки сотрудник сверяет номер заказа с номером накладной.",
                "Если номера различаются, разгрузку не начинают и сообщают",
                "руководителю смены. Исправленную накладную получают до разгрузки.",
            ],
        ),
        (
            "2. Осмотр упаковки",
            [
                "После сверки документов сотрудник осматривает целостность упаковки.",
                "Если упаковка повреждена, сотрудник фотографирует повреждение",
                "и составляет акт до подписания накладной.",
            ],
        ),
        (
            "3. Учёт расхождений",
            [
                "Сотрудник сравнивает фактическое количество мест с накладной.",
                "Недостачу отмечают в акте с указанием позиции и количества.",
                "До регистрации акта расхождения приёмку не закрывают.",
            ],
        ),
        (
            "4. Завершение приёмки",
            [
                "Если расхождений нет, сотрудник подписывает накладную после",
                "осмотра упаковки и сверки количества мест.",
                "После подписания сотрудник сохраняет накладную в карточке поставки.",
            ],
        ),
    ]
    for heading, lines in (
        expanded_sections if output.name == "expanded_policy.pdf" else compact_sections
    ):
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
