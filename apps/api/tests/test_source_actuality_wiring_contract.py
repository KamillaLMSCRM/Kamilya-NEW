from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]


def test_source_actuality_router_is_registered_once() -> None:
    text = (API_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert text.count("from app.modules.source_actuality.router import router as source_actuality_router") == 1
    assert text.count("app.include_router(source_actuality_router") == 1


def test_source_actuality_analysis_is_loaded_and_routed_to_documents_queue() -> None:
    text = (API_ROOT / "app" / "core" / "celery_app.py").read_text(encoding="utf-8")
    assert text.count('"app.modules.source_actuality.tasks"') == 1
    assert text.count('"source_actuality.analyze_review": {"queue": "documents"}') == 1
    assert '"source_actuality.analyze_review": {' in text
    assert '"soft_time_limit": 900' in text
    assert '"time_limit": 1200' in text

    task_text = (API_ROOT / "app" / "modules" / "source_actuality" / "tasks.py").read_text(
        encoding="utf-8"
    )
    assert "max_retries=3" in task_text
    assert "source_analysis_retry_exhausted" in task_text
