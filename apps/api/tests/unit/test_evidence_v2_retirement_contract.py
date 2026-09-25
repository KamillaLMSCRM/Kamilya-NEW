from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
AI_MODULE = ROOT / "apps/api/app/modules/ai"


def test_only_evidence_v2_generation_implementation_remains() -> None:
    retired_paths = (
        AI_MODULE / "assessment.py",
        AI_MODULE / "assessment_audit.py",
        AI_MODULE / "assessment_completion.py",
        ROOT / "scripts/ops/ai_assessment_replay.py",
        ROOT / "apps/api/app/ml_prompts/prompts/assessment/system.md",
        ROOT / "packages/ml_pipeline/prompts/assessment/system.md",
    )

    assert [path.relative_to(ROOT).as_posix() for path in retired_paths if path.exists()] == []

    production_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in AI_MODULE.rglob("*.py")
    )
    assert "generate_course_assessment" not in production_source
    assert "generate_lesson_assessment" not in production_source
    assert "audit_course_assessment" not in production_source
    assert "finalize_course_assessment" not in production_source


def test_supported_replay_and_snapshot_builder_target_evidence_v2() -> None:
    replay = ROOT / "scripts/dev/review_semantic_artifact.py"
    builder = ROOT / "scripts/dev/build_ai_course_logic_snapshot.py"

    replay_source = replay.read_text(encoding="utf-8")
    builder_source = builder.read_text(encoding="utf-8")

    assert "evidence_engine.semantic_assessment" in replay_source
    assert "generate_block_assessment" in replay_source
    assert "evidence_engine/application.py" in builder_source
    assert "evidence_engine/semantic_assessment.py" in builder_source
    assert '"apps/api/app/modules/ai/assessment.py"' not in builder_source
    assert '"apps/api/app/modules/ai/assessment_audit.py"' not in builder_source
    assert '"apps/api/app/modules/ai/assessment_completion.py"' not in builder_source


def test_active_question_quality_does_not_import_retired_assessment() -> None:
    quality_source = (AI_MODULE / "evidence_engine/quality.py").read_text(encoding="utf-8")

    assert "app.modules.ai.assessment" not in quality_source


def test_snapshot_builder_emits_current_engine_without_retired_modules(tmp_path: Path) -> None:
    output = tmp_path / "snapshot.md"

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/dev/build_ai_course_logic_snapshot.py"),
            "--repo",
            str(ROOT),
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    snapshot = output.read_text(encoding="utf-8")
    assert "evidence_engine.application.generate_evidence_course" in snapshot
    assert "apps/api/app/modules/ai/evidence_engine/semantic_assessment.py" in snapshot
    assert "apps/api/app/modules/ai/assessment.py" not in snapshot
    assert "apps/api/app/modules/ai/assessment_audit.py" not in snapshot
    assert "apps/api/app/modules/ai/assessment_completion.py" not in snapshot
