from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .domain import EvaluationFinding, EvaluationReport


def _finding_line(finding: EvaluationFinding) -> str:
    reasons = ", ".join(finding.reasons) if finding.reasons else "нет"
    return f"- **{finding.decision.upper()}** — {finding.title}  \n  Сигналы: {reasons}."


def render_markdown(report: EvaluationReport) -> str:
    models = ", ".join(report.resolved_models) or "нет ответов"
    lines = [
        "# Отчёт оценки качества курса",
        "",
        f"- Решение: **{report.decision.upper()}**",
        f"- Режим: **{report.enforcement}** (не блокирует клиентский flow)",
        f"- Рубрика: `{report.rubric_version}`",
        f"- Модель: `{models}`",
        f"- SHA-256 артефакта: `{report.artifact.sha256}`",
        f"- Вызовы / live / cache: {report.usage.calls} / {report.usage.live_calls} / {report.usage.cache_hits}",
        f"- Входные токены / provider latency / wall time: {report.usage.input_tokens} / {report.usage.provider_latency_ms} мс / {report.usage.evaluation_wall_ms} мс",
        f"- Оценочная стоимость: ${report.usage.estimated_cost_usd:.8f}",
        "",
        "## Уроки",
        "",
        *(_finding_line(finding) for finding in report.lessons),
        "",
        "## Вопросы",
        "",
        *(_finding_line(finding) for finding in report.questions),
        "",
        "## Ограничения",
        "",
        "Пороговые значения пока исследовательские. Итог рассчитывается кодом и служит сигналом для разработки; он не публикует и не изменяет курс.",
        "",
    ]
    return "\n".join(lines)


def write_report(report: EvaluationReport, output_dir: str | Path) -> tuple[Path, Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    stem = f"{report.artifact.sha256[:12]}-{report.rubric_version}"
    json_path = destination / f"{stem}.json"
    markdown_path = destination / f"{stem}.md"
    json_path.write_text(
        json.dumps(asdict(report), ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path
