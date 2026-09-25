"""Build a source-faithful engineering snapshot of the active Evidence V2 path."""

from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class SourceFile:
    path: str
    note: str


SOURCE_FILES = (
    SourceFile("apps/api/app/modules/ai/generation_engine.py", "Sole engine identity."),
    SourceFile("apps/api/app/modules/ai/evidence_engine/models.py", "Immutable evidence model."),
    SourceFile("apps/api/app/modules/ai/evidence_engine/adapters.py", "Source adapters."),
    SourceFile("apps/api/app/modules/ai/evidence_engine/engine.py", "Evidence planning core."),
    SourceFile("apps/api/app/modules/ai/evidence_engine/provider_models.py", "Provider result contracts."),
    SourceFile("apps/api/app/modules/ai/evidence_engine/providers.py", "Provider ports and adapters."),
    SourceFile("apps/api/app/modules/ai/evidence_engine/provider_engine.py", "Grounded realization."),
    SourceFile("apps/api/app/modules/ai/evidence_engine/source_blocks.py", "Narrative source blocks."),
    SourceFile("apps/api/app/modules/ai/evidence_engine/assessment_axes.py", "Assessment-axis planning."),
    SourceFile("apps/api/app/modules/ai/evidence_engine/assessment_coverage.py", "Coverage policy."),
    SourceFile("apps/api/app/modules/ai/evidence_engine/semantic_assessment.py", "Question authorship, review, repair and audit."),
    SourceFile("apps/api/app/modules/ai/evidence_engine/quality.py", "Final learner-visible quality policy."),
    SourceFile("apps/api/app/modules/ai/evidence_engine/application.py", "Production-shaped Evidence V2 interface."),
    SourceFile("apps/api/app/modules/ai/source_tables.py", "Shared Markdown-table parsing."),
    SourceFile("apps/api/app/modules/ai/direct_source.py", "Verified-original corpus and source recovery."),
    SourceFile("apps/api/app/modules/ai/ingestion.py", "Conversion, chunking, embeddings and persistence adapters."),
    SourceFile("apps/api/app/modules/ai/llm_client.py", "Generation and embedding failover clients."),
    SourceFile("apps/api/app/modules/ai/pipeline.py", "Job orchestration and draft persistence."),
    SourceFile("apps/api/app/modules/ai/job_service.py", "Admission and queue submission."),
    SourceFile("apps/api/app/modules/ai/tasks.py", "Celery entry points."),
    SourceFile("apps/api/app/modules/ai/assessment_schema.py", "Persisted assessment contract."),
    SourceFile("apps/api/app/modules/ai/architect_schema.py", "Persisted course-structure contract."),
    SourceFile("apps/api/app/modules/ai/writer_schema.py", "Persisted lesson-content contract."),
    SourceFile("scripts/dev/run_evidence_course_application.py", "Current full local provider/replay runner."),
    SourceFile("scripts/dev/review_semantic_artifact.py", "Current assessment-only replay."),
    SourceFile("docs/critical-journeys/ai-course-generation.json", "AI-COURSE-01 release contract."),
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], text=True, encoding="utf-8"
    ).strip()


def _language(path: str) -> str:
    return {
        ".json": "json",
        ".md": "markdown",
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "tsx",
    }.get(Path(path).suffix, "text")


def _fence(language: str, source: str) -> str:
    marker = "````" if "```" in source else "```"
    return f"{marker}{language}\n{source.rstrip()}\n{marker}\n"


def build_snapshot(repo: Path) -> str:
    sha = _git(repo, "rev-parse", "HEAD")
    branch = _git(repo, "branch", "--show-current")
    committed_at = _git(repo, "show", "-s", "--format=%cI", sha)
    lines = [
        "# Kamilya LMS: действующая логика генерации курса Evidence V2",
        "",
        f"> Снимок исходников на Git SHA `{sha}` (`{branch}`), commit `{committed_at}`.",
        "> Документ не содержит секретов и клиентских данных. Он описывает только",
        "> единственный поддерживаемый движок `evidence_v2`; снятый legacy-код исключён.",
        "",
        "## Исполняемый путь",
        "",
        "```text",
        "upload/reindex -> conversion -> chunks + embeddings",
        "  -> pipeline.run_generation_pipeline",
        "  -> evidence_engine.application.generate_evidence_course",
        "  -> source document plan + immutable facts",
        "  -> adaptive lessons + grounded realization",
        "  -> semantic assessment axes",
        "  -> authorship -> blind review -> constraint audit -> bounded repair",
        "  -> coverage/publishability diagnostics",
        "  -> transactional draft persistence -> methodologist review",
        "```",
        "",
        "## Ключевые правила",
        "",
        "- Документ является доказательством; сгенерированный текст урока не становится новым источником истины.",
        "- Объём курса и число вопросов следуют доказуемой плотности источника, без quota padding.",
        "- Каждый вопрос связан с `fact_id`, evidence locator и assessment axis.",
        "- Неоднозначные варианты удаляются или ремонтируются; удалённое не добивается слабым вопросом.",
        "- `assessment_review` хранит block/axis outcomes, omission reasons и coverage.",
        "- Черновик не становится опубликованным курсом без проверки методолога.",
        "",
        "## Полные исходные файлы",
        "",
    ]
    for spec in SOURCE_FILES:
        path = repo / spec.path
        if not path.is_file():
            raise FileNotFoundError(f"Snapshot source is missing: {spec.path}")
        source = path.read_text(encoding="utf-8-sig")
        lines.extend(
            (
                f"### `{spec.path}`",
                "",
                spec.note,
                "",
                _fence(_language(spec.path), source).rstrip(),
                "",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_snapshot(repo), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
