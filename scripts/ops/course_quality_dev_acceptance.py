"""Exercise the public DEV document-to-course journey with synthetic XLSX data.

The script is intentionally fail-closed and emits only structural evidence. It
loads the synthetic methodologist credentials from a local dotenv file, never
prints them, verifies the exact DEV release, checks every generated lesson and
question, and removes only the objects created by this run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from dotenv import dotenv_values, load_dotenv
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[2]
API_ROOT = ROOT / "apps" / "api"
TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}
META_QUESTION_PATTERNS = (
    re.compile(r"\b(?:о ч[её]м|что именно)\s+(?:этот|в этом)\s+(?:урок|курс|раздел|модул)", re.IGNORECASE),
    re.compile(r"\bwhat\s+(?:is|does|will)\s+(?:this|the)\s+(?:lesson|course|section|module)", re.IGNORECASE),
    re.compile(r"\bчто\s+(?:включает|содержит)\s+.+\s+согласно\s+заголовку\b", re.IGNORECASE),
    re.compile(r"\bчто\s+(?:задано|указано|описано)\s+в\s+(?:таблице|исходном\s+материале)\b", re.IGNORECASE),
    re.compile(r"\bв\s+каком\s+виде\s+.+\s+(?:даны|представлены)\b", re.IGNORECASE),
    re.compile(r"\bчто\s+описывает\s+каждая\s+строка\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+does\s+.+\s+include\s+according\s+to\s+the\s+title\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+is\s+(?:specified|shown|described)\s+in\s+the\s+(?:table|source)\b", re.IGNORECASE),
    re.compile(r"\bin\s+what\s+form\s+.+\s+(?:given|presented)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+does\s+each\s+row\s+describe\b", re.IGNORECASE),
    re.compile(r"\b(?:в|во)\s+заголовк\w*\b", re.IGNORECASE),
    re.compile(r"\bв\s+(?:рабочей\s+)?таблиц\w*\b", re.IGNORECASE),
    re.compile(r"\b(?:разобран\w*|приведен\w*|показан\w*)\s+ниже\b", re.IGNORECASE),
    re.compile(r"\bрассматрива\w*\s+в\s+раздел\w*\b", re.IGNORECASE),
    re.compile(r"\bпредставлен\w*\s+в\s+свидетельств\w*\b", re.IGNORECASE),
    re.compile(r"\bсогласно\s+(?:урок\w*|раздел\w*|заголовк\w*|материал\w*|текст\w*)\b", re.IGNORECASE),
    re.compile(r"\bв\s+исходн\w*\s+материал\w*\b", re.IGNORECASE),
    re.compile(r"\b(?:in|according\s+to)\s+the\s+(?:title|heading|table|section|lesson|source\s+material)\b", re.IGNORECASE),
    re.compile(r"\b(?:shown|presented|discussed)\s+below\b", re.IGNORECASE),
    re.compile(r"\bчто\s+рассматривается\s+в\s+тем\w*\b", re.IGNORECASE),
    re.compile(
        r"\bчто\s+в\s+(?:этом|данном)\s+(?:уроке|курсе|разделе|модуле)\s+"
        r"(?:разбираем|изучаем|рассматриваем)\b",
        re.IGNORECASE,
    ),
)
UNSUPPORTED_RELATIONSHIP_PATTERNS = (
    re.compile(r"\b(?:прямо|напрямую)\s+связан\w*\b", re.IGNORECASE),
    re.compile(r"\bоснов\w*\s+для\b", re.IGNORECASE),
    re.compile(
        r"\bпоэтому\b.{0,100}\b(?:важно|нужно|следует|необходимо)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bзначит\b.{0,140}\b(?:рабоч\w*\s+шаг\w*|важно|нужно|следует|необходимо)\b",
        re.IGNORECASE,
    ),
)
SUPPORTING_CATALOG_TITLE_PATTERN = re.compile(
    r"\b(?:sku(?:[-_ ]?\d+)?|артикул\w*|прайс[-\s]?лист\w*|"
    r"каталог\w*|номенклатур\w*|"
    r"catalog(?:ue)?|price\s*list|nomenclature)\b",
    re.IGNORECASE,
)
WORD_RE = re.compile(r"[^\W\d_]{4,}", re.UNICODE)
STOP_WORDS = {
    "будет", "какая", "какие", "какой", "материал", "материале", "правильный",
    "согласно", "указано", "урока", "уроке", "этого", "этой", "является",
}


class AcceptanceError(RuntimeError):
    pass


class DevClient:
    def __init__(self, base_url: str, browser_origin: str, email: str, password: str) -> None:
        self._email = email
        self._password = password
        self._token = ""
        self.http = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            timeout=httpx.Timeout(90.0, connect=30.0),
            follow_redirects=False,
            headers={
                "Origin": browser_origin,
                "User-Agent": "Kamilya-DEV-course-quality-acceptance/1",
            },
        )

    def close(self) -> None:
        self.http.close()

    def login(self) -> dict[str, Any]:
        response = self.http.post(
            "v1/auth/login",
            json={"email": self._email, "password": self._password},
        )
        self._expect(response, {200}, "login")
        payload = response.json()
        self._token = str(payload.get("access_token") or "")
        if not self._token:
            raise AcceptanceError("login_missing_access_token")
        return payload

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {self._token}"
        response = self.http.request(method, url, headers=headers, **kwargs)
        if response.status_code != 401:
            return response
        refresh = self.http.post("v1/auth/refresh", json={})
        self._expect(refresh, {200}, "refresh")
        self._token = str(refresh.json().get("access_token") or "")
        if not self._token:
            raise AcceptanceError("refresh_missing_access_token")
        headers["Authorization"] = f"Bearer {self._token}"
        return self.http.request(method, url, headers=headers, **kwargs)

    @staticmethod
    def _expect(response: httpx.Response, statuses: set[int], stage: str) -> None:
        if response.status_code not in statuses:
            detail_code = "unknown"
            try:
                detail = response.json().get("detail")
                if isinstance(detail, dict):
                    detail_code = str(detail.get("code") or "structured_error")
                elif isinstance(detail, str):
                    detail_code = "message_error"
            except Exception:
                detail_code = "non_json_error"
            raise AcceptanceError(f"{stage}_http_{response.status_code}_{detail_code}")


def stage(value: str) -> None:
    print(f"stage={value}", flush=True)


def health_url(api_base: str) -> str:
    parsed = urlsplit(api_base)
    return urlunsplit((parsed.scheme, parsed.netloc, "/health", "", ""))


def poll_job(
    client: DevClient,
    job_id: str,
    *,
    timeout_seconds: int,
    label: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_marker: tuple[str, str, int] | None = None
    while time.monotonic() < deadline:
        response = client.request("GET", f"v1/ai/jobs/{job_id}")
        client._expect(response, {200}, f"{label}_poll")
        payload = response.json()
        marker = (
            str(payload.get("status") or ""),
            str(payload.get("stage") or ""),
            int(payload.get("progress") or 0),
        )
        if marker != last_marker:
            stage(f"{label}:{marker[0]}:{marker[1]}:{marker[2]}")
            last_marker = marker
        if marker[0] in TERMINAL_JOB_STATUSES:
            return payload
        time.sleep(4)
    raise AcceptanceError(f"{label}_timeout")


def execute_generation_locally(
    *,
    env_file: Path,
    job_id: str,
    document_id: str,
    recommendation: dict[str, Any],
    source_analysis: dict[str, Any],
    tenant_id: str,
    user_id: str,
) -> dict[str, Any]:
    """Run only the just-created synthetic job with the candidate source tree."""

    load_dotenv(env_file, override=True)
    database_host = urlsplit(str(os.environ.get("DATABASE_URL") or "")).hostname or ""
    if "supabase" not in database_host.casefold():
        raise AcceptanceError("local_worker_not_pointing_to_supabase_dev")
    if not os.environ.get("STORAGE_BACKEND", "").strip():
        if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_KEY"):
            raise AcceptanceError("local_worker_supabase_storage_unavailable")
        os.environ["STORAGE_BACKEND"] = "supabase"
    if str(API_ROOT) not in sys.path:
        sys.path.insert(0, str(API_ROOT))
    # A real Celery worker imports the full configured task set before handling
    # AI jobs, which registers every cross-module SQLAlchemy FK target.  This
    # direct runner must establish the same model registry before task import.
    import app.main as _application  # noqa: F401
    from app.modules.ai.tasks import generate_course_task

    return generate_course_task.run(
        job_id=job_id,
        documents=[document_id],
        target_audience="",
        guidance="",
        num_modules=int(recommendation.get("module_count") or 1),
        lessons_per_module=int(recommendation.get("lessons_per_module") or 1),
        max_total_lessons=int(recommendation.get("recommended_total_lessons") or 1),
        language="ru",
        tenant_id=tenant_id,
        user_id=user_id,
        source_strategy="single_topic",
        combination_goal="",
        source_analysis=source_analysis,
    )


def execute_document_cleanup_locally(
    *, env_file: Path, job_id: str, document_id: str, tenant_id: str
) -> None:
    load_dotenv(env_file, override=True)
    import asyncio
    from uuid import UUID

    if str(API_ROOT) not in sys.path:
        sys.path.insert(0, str(API_ROOT))
    from app.modules.documents.cleanup import run_document_cleanup

    result = asyncio.run(
        run_document_cleanup(job_id, UUID(document_id), UUID(tenant_id))
    )
    if not result.get("deleted"):
        raise AcceptanceError("local_document_cleanup_failed")


def poll_document(client: DevClient, document_id: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_status = ""
    while time.monotonic() < deadline:
        response = client.request(
            "GET",
            "v1/documents/catalog?lifecycle_status=active&limit=100",
        )
        client._expect(response, {200}, "document_catalog")
        document = next(
            (item for item in response.json().get("items", []) if str(item.get("id")) == document_id),
            None,
        )
        if not document:
            raise AcceptanceError("uploaded_document_not_in_catalog")
        index = document.get("index") or {}
        status = str(index.get("status") or "")
        if status != last_status:
            stage(f"document_index:{status}")
            last_status = status
        if status in {"ready", "partial"}:
            return document
        if status == "failed":
            raise AcceptanceError(f"document_index_failed_{index.get('error_code') or 'unknown'}")
        time.sleep(3)
    raise AcceptanceError("document_index_timeout")


def normalized_words(value: str) -> set[str]:
    return {word.casefold() for word in WORD_RE.findall(value) if word.casefold() not in STOP_WORDS}


def fixture_focus_terms(xlsx: Path) -> set[str]:
    workbook = load_workbook(xlsx, read_only=True, data_only=True)
    try:
        if "Коллекция" not in workbook.sheetnames:
            raise AcceptanceError("fixture_primary_sheet_missing")
        rows = workbook["Коллекция"].iter_rows(min_row=2, values_only=True)
        return {
            str(row[0]).strip().casefold()
            for row in rows
            if row and row[0] is not None and len(str(row[0]).strip()) >= 4
        }
    finally:
        workbook.close()


def has_meta_question(value: str) -> bool:
    return any(pattern.search(value) for pattern in META_QUESTION_PATTERNS)


def has_supporting_catalog_title(value: str) -> bool:
    return bool(SUPPORTING_CATALOG_TITLE_PATTERN.search(" ".join(value.split())))


def choices_share_only_one_word_suffix(choices: list[str]) -> bool:
    tokenized = [[word.casefold() for word in re.findall(r"\S+", choice)] for choice in choices]
    if len(tokenized) < 3 or min(map(len, tokenized), default=0) < 2:
        return False
    if len({len(tokens) for tokens in tokenized}) != 1:
        return False
    common = 0
    for columns in zip(*tokenized, strict=False):
        if len(set(columns)) != 1:
            break
        common += 1
    return common == len(tokenized[0]) - 1


def inspect_output(
    preview: dict[str, Any],
    quizzes: list[dict[str, Any]],
    recommendation: dict[str, Any],
    focus_terms: set[str],
) -> tuple[list[str], dict[str, Any]]:
    failures: list[str] = []
    modules = preview.get("modules") or []
    lessons = [lesson for module in modules for lesson in module.get("lessons", [])]
    if not modules:
        failures.append("course_has_no_modules")
    if not lessons:
        failures.append("course_has_no_lessons")

    hard_max = int(recommendation.get("hard_max_total_lessons") or 0)
    recommended = int(recommendation.get("recommended_total_lessons") or 0)
    if hard_max and len(lessons) > hard_max:
        failures.append("lesson_count_exceeds_hard_max")
    if recommended and len(lessons) > recommended:
        failures.append("lesson_count_exceeds_recommendation")

    unverified_lessons = 0
    lessons_without_sources = 0
    sku_title_lessons = 0
    supporting_catalog_title_lessons = 0
    for lesson in lessons:
        if lesson.get("source_validation_status") != "verified":
            unverified_lessons += 1
        if not lesson.get("source_document_ids") or not lesson.get("source_references"):
            lessons_without_sources += 1
        if re.search(r"\bSKU[-_ ]?\d+\b", str(lesson.get("title") or ""), re.IGNORECASE):
            sku_title_lessons += 1
        if has_supporting_catalog_title(str(lesson.get("title") or "")):
            supporting_catalog_title_lessons += 1
    if unverified_lessons:
        failures.append("lesson_source_validation_not_verified")
    if lessons_without_sources:
        failures.append("lesson_source_references_missing")
    if sku_title_lessons:
        failures.append("supporting_sku_became_lesson_title")
    if supporting_catalog_title_lessons:
        failures.append("supporting_catalog_became_lesson_title")
    unsupported_relationship_claims = sum(
        1
        for lesson in lessons
        if any(
            pattern.search(str(lesson.get("content_preview") or ""))
            for pattern in UNSUPPORTED_RELATIONSHIP_PATTERNS
        )
    )
    if unsupported_relationship_claims:
        failures.append("unsupported_relationship_claims_present")
    visible_course_text = " ".join(
        [
            str(preview.get("title") or ""),
            str(preview.get("description") or ""),
            *(str(module.get("title") or "") for module in modules),
            *(str(lesson.get("title") or "") for lesson in lessons),
            *(str(lesson.get("content_preview") or "") for lesson in lessons),
        ]
    ).casefold()
    matched_focus_terms = {term for term in focus_terms if term in visible_course_text}
    if len(matched_focus_terms) < min(2, len(focus_terms)):
        failures.append("primary_collection_focus_missing")

    quiz_by_id = {str(quiz.get("id")): quiz for quiz in quizzes}
    expected_quiz_ids = {
        str(lesson.get("quiz_id")) for lesson in lessons if lesson.get("quiz_id")
    }
    missing_quizzes = expected_quiz_ids - set(quiz_by_id)
    if missing_quizzes:
        failures.append("preview_quiz_missing_from_api")

    questions: list[dict[str, Any]] = []
    meta_questions = 0
    invalid_correct_counts = 0
    duplicate_choice_sets = 0
    question_equals_choice = 0
    low_information_distractors = 0
    missing_explanations = 0
    review_state_failures = 0
    seen_questions: set[str] = set()
    duplicate_questions = 0
    for quiz_id in expected_quiz_ids:
        quiz = quiz_by_id.get(quiz_id)
        if not quiz:
            continue
        if quiz.get("review_status") != "needs_review":
            review_state_failures += 1
        for question in quiz.get("questions") or []:
            questions.append(question)
            text = " ".join(str(question.get("text") or "").split())
            normalized_question = text.casefold()
            if normalized_question in seen_questions:
                duplicate_questions += 1
            seen_questions.add(normalized_question)
            if has_meta_question(text):
                meta_questions += 1
            choices = [" ".join(str(choice.get("text") or "").split()) for choice in question.get("choices") or []]
            if sum(bool(choice.get("is_correct")) for choice in question.get("choices") or []) != 1:
                invalid_correct_counts += 1
            if len(choices) != len({choice.casefold() for choice in choices}):
                duplicate_choice_sets += 1
            if normalized_question in {choice.casefold() for choice in choices}:
                question_equals_choice += 1
            if choices_share_only_one_word_suffix(choices):
                low_information_distractors += 1
            if not str(question.get("explanation") or "").strip():
                missing_explanations += 1

    if not questions:
        failures.append("course_has_no_questions")
    for count, code in (
        (meta_questions, "generic_meta_questions_present"),
        (invalid_correct_counts, "question_correct_answer_count_invalid"),
        (duplicate_choice_sets, "duplicate_choices_present"),
        (question_equals_choice, "question_repeated_as_choice"),
        (low_information_distractors, "low_information_distractors_present"),
        (missing_explanations, "question_explanation_missing"),
        (review_state_failures, "quiz_not_marked_needs_review"),
        (duplicate_questions, "duplicate_questions_present"),
    ):
        if count:
            failures.append(code)

    facts = {
        "modules": len(modules),
        "lessons": len(lessons),
        "quizzes": len(expected_quiz_ids),
        "questions": len(questions),
        "recommended_lessons": recommended,
        "hard_max_lessons": hard_max,
        "unverified_lessons": unverified_lessons,
        "lessons_without_sources": lessons_without_sources,
        "sku_title_lessons": sku_title_lessons,
        "supporting_catalog_title_lessons": supporting_catalog_title_lessons,
        "meta_questions": meta_questions,
        "invalid_correct_counts": invalid_correct_counts,
        "duplicate_choice_sets": duplicate_choice_sets,
        "question_equals_choice": question_equals_choice,
        "low_information_distractors": low_information_distractors,
        "missing_explanations": missing_explanations,
        "review_state_failures": review_state_failures,
        "duplicate_questions": duplicate_questions,
        "primary_focus_terms_available": len(focus_terms),
        "primary_focus_terms_matched": len(matched_focus_terms),
        "unsupported_relationship_claims": unsupported_relationship_claims,
    }
    return failures, facts


def build_review_sample(
    preview: dict[str, Any],
    quizzes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Keep bounded synthetic learner text for a human quality review."""

    quiz_by_id = {str(quiz.get("id")): quiz for quiz in quizzes}
    modules: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    for module in (preview.get("modules") or [])[:8]:
        sampled_lessons: list[dict[str, str]] = []
        for lesson in (module.get("lessons") or [])[:14]:
            sampled_lessons.append(
                {
                    "title": str(lesson.get("title") or "")[:240],
                    "content_preview": str(lesson.get("content_preview") or "")[:1200],
                }
            )
            quiz = quiz_by_id.get(str(lesson.get("quiz_id") or ""))
            for question in (quiz.get("questions") if quiz else []) or []:
                questions.append(
                    {
                        "text": str(question.get("text") or "")[:500],
                        "choices": [
                            {
                                "text": str(choice.get("text") or "")[:300],
                                "is_correct": choice.get("is_correct") is True,
                            }
                            for choice in (question.get("choices") or [])[:6]
                        ],
                        "explanation": str(question.get("explanation") or "")[:700],
                    }
                )
        modules.append(
            {
                "title": str(module.get("title") or "")[:240],
                "lessons": sampled_lessons,
            }
        )
    return {
        "course_title": str(preview.get("title") or "")[:240],
        "course_description": str(preview.get("description") or "")[:700],
        "modules": modules,
        "questions": questions[:60],
    }


def cleanup_object(action: Callable[[], None], failures: list[str], code: str) -> None:
    try:
        action()
    except Exception:
        failures.append(code)


def run(args: argparse.Namespace) -> dict[str, Any]:
    config = dotenv_values(args.env_file)
    email = str(config.get("DEV_QA_METHODOLOGIST_EMAIL") or "")
    password = str(config.get("DEV_QA_METHODOLOGIST_PASSWORD") or "")
    if not email or not password:
        raise AcceptanceError("dev_methodologist_credentials_missing")
    xlsx = args.xlsx.resolve(strict=True)
    if xlsx.suffix.casefold() != ".xlsx":
        raise AcceptanceError("fixture_must_be_xlsx")
    focus_terms = fixture_focus_terms(xlsx)

    report: dict[str, Any] = {
        "passed": False,
        "expected_release_sha": args.expected_release_sha,
        "synthetic_fixture_bytes": xlsx.stat().st_size,
        "checks": [],
        "quality": {},
        "cleanup": {"course": False, "document": False},
    }
    client = DevClient(args.api_base, args.browser_origin, email, password)
    document_id = ""
    course_id = ""
    generation_job_id = ""
    tenant_id = ""
    cleanup_failures: list[str] = []
    try:
        stage("health")
        health = client.http.get(health_url(args.api_base))
        client._expect(health, {200}, "health")
        health_payload = health.json()
        if health_payload.get("release_sha") != args.expected_release_sha:
            raise AcceptanceError("dev_release_sha_mismatch")
        report["checks"].append("exact_dev_release")

        stage("login")
        login = client.login()
        login_user = login.get("user") or {}
        role = str(login_user.get("role") or "")
        if role != "methodologist":
            raise AcceptanceError("synthetic_user_not_methodologist")
        tenant_id = str(login_user.get("tenant_id") or "")
        user_id = str(login_user.get("user_id") or "")
        if not tenant_id or not user_id:
            raise AcceptanceError("synthetic_user_identity_incomplete")
        report["checks"].append("synthetic_methodologist_login")

        stage("upload")
        with xlsx.open("rb") as handle:
            upload = client.request(
                "POST",
                "v1/documents/upload",
                files={
                    "file": (
                        f"course-quality-{int(time.time())}.xlsx",
                        handle,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
                data={"title": "Синтетическая проверка качества курса"},
            )
        client._expect(upload, {201}, "upload")
        upload_payload = upload.json()
        document_id = str(upload_payload.get("id") or "")
        if not document_id:
            raise AcceptanceError("upload_missing_document_id")
        report["checks"].append("xlsx_uploaded")

        document = poll_document(client, document_id, args.index_timeout)
        index = document["index"]
        if not index.get("chunks_total") or index.get("chunks_indexed") != index.get("chunks_total"):
            raise AcceptanceError("document_index_incomplete")
        report["checks"].append(f"document_index_{document['index']['status']}")

        stage("compatibility")
        compatibility = client.request(
            "POST",
            "v1/ai/document-compatibility",
            json={"documents": [document_id], "course_format": "automatic"},
        )
        client._expect(compatibility, {200}, "compatibility")
        compatibility_payload = compatibility.json()
        passport = compatibility_payload.get("source_passport") or {}
        roles = {str(section.get("name")): str(section.get("role")) for section in passport.get("sections") or []}
        if roles.get("Коллекция") != "primary":
            raise AcceptanceError("collection_sheet_not_primary")
        if roles.get("Список") != "supporting":
            raise AcceptanceError("list_sheet_not_supporting")
        if "Расчёты" in roles:
            raise AcceptanceError("hidden_sheet_entered_passport")
        if passport.get("confidence") not in {"high", "medium"}:
            raise AcceptanceError("document_passport_low_confidence")
        recommendation = compatibility_payload.get("recommended_structure") or {}
        if int(recommendation.get("recommended_total_lessons") or 0) > 14:
            raise AcceptanceError("supporting_rows_inflated_course_size")
        report["passport"] = {
            "confidence": passport.get("confidence"),
            "teachable_units": passport.get("teachable_units"),
            "roles": roles,
            "recommended_total_lessons": recommendation.get("recommended_total_lessons"),
        }
        report["checks"].append("document_passport_roles")
        report["checks"].append("adaptive_course_size")

        stage("generation_submit")
        generation = client.request(
            "POST",
            "v1/ai/generate-course",
            json={
                "documents": [document_id],
                "target_audience": "",
                "course_intent": "",
                "course_format": "automatic",
                "language": "ru",
                "source_strategy": "single_topic",
                "combination_goal": "",
            },
        )
        client._expect(generation, {202}, "generation_submit")
        generation_job_id = str(generation.json().get("id") or "")
        if not generation_job_id:
            raise AcceptanceError("generation_missing_job_id")
        report["checks"].append("blank_intent_generation_accepted")

        if args.execute_local_worker:
            stage("candidate_local_worker")
            local_result = execute_generation_locally(
                env_file=args.env_file,
                job_id=generation_job_id,
                document_id=document_id,
                recommendation=recommendation,
                source_analysis=compatibility_payload,
                tenant_id=tenant_id,
                user_id=user_id,
            )
            report["local_worker"] = {
                "used": True,
                "status": local_result.get("status"),
            }

        job = poll_job(
            client,
            generation_job_id,
            timeout_seconds=args.generation_timeout,
            label="course_generation",
        )
        course_id = str(job.get("course_id") or "")
        if job.get("status") != "completed":
            error_codes = [
                str(error.get("code") or "unknown") if isinstance(error, dict) else str(error)
                for error in job.get("errors") or []
            ]
            report["generation"] = {"status": job.get("status"), "error_codes": error_codes}
            raise AcceptanceError("generation_not_completed")
        if not course_id:
            raise AcceptanceError("completed_generation_missing_course")
        report["checks"].append("course_generation_completed")

        stage("output_inspection")
        preview_response = client.request("GET", f"v1/courses/{course_id}/preview?max_chars=2000")
        client._expect(preview_response, {200}, "course_preview")
        preview = preview_response.json()
        quizzes_response = client.request("GET", "v1/quizzes")
        client._expect(quizzes_response, {200}, "quiz_list")
        failures, facts = inspect_output(
            preview,
            quizzes_response.json(),
            recommendation,
            focus_terms,
        )
        report["quality"] = facts
        report["review_sample"] = build_review_sample(
            preview,
            quizzes_response.json(),
        )
        if failures:
            report["quality_failures"] = failures
            raise AcceptanceError("generated_output_quality_gate_failed")
        report["checks"].extend(
            [
                "all_lessons_source_verified",
                "supporting_rows_not_promoted_to_lessons",
                "all_generated_quizzes_need_review",
                "all_questions_pass_structural_quality",
            ]
        )
        report["passed"] = True
    except Exception as exc:
        report["failure"] = str(exc) if isinstance(exc, AcceptanceError) else type(exc).__name__
    finally:
        stage("cleanup")
        if generation_job_id:
            try:
                response = client.request("GET", f"v1/ai/jobs/{generation_job_id}")
                if response.status_code == 200:
                    job = response.json()
                    course_id = course_id or str(job.get("course_id") or "")
                    if job.get("status") not in TERMINAL_JOB_STATUSES:
                        client.request("POST", f"v1/ai/jobs/{generation_job_id}/cancel")
            except Exception:
                cleanup_failures.append("generation_cancel_failed")
        if course_id:
            def delete_course() -> None:
                response = client.request("DELETE", f"v1/courses/{course_id}")
                client._expect(response, {204, 404}, "course_cleanup")
                report["cleanup"]["course"] = True

            cleanup_object(delete_course, cleanup_failures, "course_cleanup_failed")
        else:
            report["cleanup"]["course"] = True
        if document_id:
            def delete_document() -> None:
                response = client.request("DELETE", f"v1/documents/{document_id}")
                client._expect(response, {202, 404}, "document_cleanup")
                if response.status_code == 202:
                    cleanup_job_id = str(response.json().get("job_id") or "")
                    if args.execute_local_worker:
                        execute_document_cleanup_locally(
                            env_file=args.env_file,
                            job_id=cleanup_job_id,
                            document_id=document_id,
                            tenant_id=tenant_id,
                        )
                    cleanup_job = poll_job(client, cleanup_job_id, timeout_seconds=180, label="document_cleanup")
                    if cleanup_job.get("status") != "completed":
                        raise AcceptanceError("document_cleanup_job_failed")
                report["cleanup"]["document"] = True

            cleanup_object(delete_document, cleanup_failures, "document_cleanup_failed")
        else:
            report["cleanup"]["document"] = True
        if cleanup_failures:
            report["cleanup_failures"] = cleanup_failures
            report["passed"] = False
        client.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--browser-origin", required=True)
    parser.add_argument("--expected-release-sha", required=True)
    parser.add_argument("--xlsx", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--index-timeout", type=int, default=600)
    parser.add_argument("--generation-timeout", type=int, default=1800)
    parser.add_argument("--execute-local-worker", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        report = run(args)
    except Exception as exc:
        report = {"passed": False, "failure": type(exc).__name__}
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload + "\n", encoding="utf-8")
    cleanup = report.get("cleanup") or {}
    return 0 if report.get("passed") and cleanup.get("course") and cleanup.get("document") else 1


if __name__ == "__main__":
    sys.exit(main())
