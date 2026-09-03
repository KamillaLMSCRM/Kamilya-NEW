import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

# Structured JSON logging — emit machine-parseable lines in production so
# external log aggregators (Sentry, Datadog, Render Log Streams) can index
# by tenant_id, request_id, etc. without regex parsing.
# Audit §9.4: in dev (APP_ENV != 'production') we keep the human-readable
# formatter because JSON is awkward to read in a terminal.
try:
    from pythonjsonlogger import jsonlogger

    _HAS_JSON_LOGGER = True
except ImportError:
    _HAS_JSON_LOGGER = False

# Must be imported BEFORE router imports so SQLAlchemy sees 'positions' table
# before resolving User.position_id ForeignKey
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.log_redaction import (
    SensitiveDataFilter,
    install_sensitive_logging_filters,
    scrub_sentry_event,
)
from app.core.rate_limit import RateLimitMiddleware
from app.core.security import SecurityHeadersMiddleware
from app.modules.admin.onboarding.router import router as onboarding_router
from app.modules.admin.provider_keys.router import router as provider_keys_router
from app.modules.admin.router import router as admin_router
from app.modules.admin.superadmin.router import router as superadmin_router
from app.modules.ai.router import router as ai_router
from app.modules.announcements.router import router as announcements_router
from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.auth.superadmin_login import router as superadmin_login_router
from app.modules.auth.telegram import router as telegram_router
from app.modules.auth.telegram_register import router as telegram_register_router
from app.modules.candidate_assessments.router import public_router as candidate_assessment_public_router
from app.modules.candidate_assessments.router import router as candidate_assessments_router
from app.modules.certificates.router import router as certificates_router
from app.modules.cohorts.router import router as cohorts_router
from app.modules.competencies.router import router as competencies_router
from app.modules.course_approval.router import router as course_approval_router
from app.modules.courses.blueprints_router import router as course_blueprints_router
from app.modules.courses.router import router as courses_router
from app.modules.demo.router import router as demo_router
from app.modules.departments.router import router as departments_router
from app.modules.documents.router import router as documents_router
from app.modules.enrollments.router import public_access_router as assignment_access_router
from app.modules.enrollments.router import router as enrollments_router
from app.modules.enrollments.router import stats_router as enrollments_stats_router
from app.modules.integrations.router import router as integrations_router
from app.modules.learner_assistant.router import router as learner_assistant_router
from app.modules.learning_cycles.router import router as learning_cycles_router
from app.modules.learning_paths.router import router as learning_paths_router
from app.modules.lessons.router import router as lessons_router
from app.modules.notifications.router import router as notifications_router
from app.modules.organization_units.router import router as organization_units_router
from app.modules.positions.admin_router import router as positions_admin_router
from app.modules.positions.jd_router import router as positions_jd_router
from app.modules.positions.models import Position  # noqa: F401
from app.modules.positions.qualification_models import PositionQualificationVersion  # noqa: F401
from app.modules.positions.qualification_router import router as positions_qualification_router
from app.modules.positions.recommendations_router import router as positions_recommendations_router
from app.modules.positions.router import router as positions_router
from app.modules.progress.router import router as progress_router
from app.modules.quizzes.assignment_router import router as quiz_assignments_router
from app.modules.quizzes.router import router as quizzes_router
from app.modules.scorm.router import router as scorm_router
from app.modules.staff_import_sessions.router import router as staff_import_sessions_router
from app.modules.staff_sync.router import router as staff_sync_router
from app.modules.student.router import router as student_router
from app.modules.support.router import router as support_router
from app.modules.surveys.router import router as surveys_router
from app.modules.tenants.router import public_router as tenants_public_router
from app.modules.tenants.router import router as tenants_router
from app.modules.training_evidence.export_router import router as training_evidence_export_router
from app.modules.training_evidence.router import router as training_evidence_router
from app.modules.training_evidence.step_up_router import router as training_evidence_step_up_router
from app.modules.training_log.router import router as training_log_router
from app.modules.training_procedures.router import router as training_procedures_router
from app.modules.training_retention.router import router as training_retention_router
from app.modules.training_rules.router import router as training_rules_router
from app.modules.users.invitations_router import router as invitations_public_router
from app.modules.users.kiosk_router import admin_router as kiosks_admin_router
from app.modules.users.kiosk_router import public_router as kiosks_public_router
from app.modules.users.router import router as users_router
from app.modules.users.staff_import_mapping_router import router as staff_import_mapping_router
from app.modules.users.staff_import_router import router as staff_import_router
from app.modules.youtube_transcript.router import router as youtube_transcript_router

logger = logging.getLogger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# Observability setup — Sentry + structured logging (audit §9.4)
# ---------------------------------------------------------------------------
# Sentry: enabled only when SENTRY_DSN env var is set. Skipped in dev
# because unhandled exceptions in local work would spam the project's
# Sentry quota.
if settings.SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.asyncpg import AsyncpgIntegration
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.APP_ENV,
            release=os.getenv("RENDER_GIT_COMMIT", "unknown"),
            traces_sample_rate=0.1,  # 10% of requests; tune via Sentry UI later
            profiles_sample_rate=0.1,
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                SqlalchemyIntegration(),
                AsyncpgIntegration(),
            ],
            # Don't send health-check pings to Sentry — they're noise.
            before_send_transaction=lambda event, hint: (
                None if event.get("transaction") in ("/api/v1/health", "GET /api/v1/health") else event
            ),
            # PII: scrub Authorization header, cookies, password fields.
            send_default_pii=False,
            before_send=scrub_sentry_event,
        )
        logger.info("Sentry initialized (env=%s)", settings.APP_ENV)
    except ImportError:
        logger.warning("SENTRY_DSN is set but sentry-sdk is not installed; skipping")


# Structured JSON logging in production. In dev/staging we keep the
# human-readable formatter because JSON in a terminal is hard to read.
if settings.APP_ENV == "production" and _HAS_JSON_LOGGER:
    handler = logging.StreamHandler()
    handler.addFilter(SensitiveDataFilter())
    handler.setFormatter(
        jsonlogger.JsonFormatter(
            "%(asctime)s %(name)s %(levelname)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level"},
        )
    )
    root = logging.getLogger()
    # Replace existing handlers so JSON takes effect (uvicorn already added its own).
    root.handlers = [handler]
    root.setLevel(logging.INFO)
elif settings.DEBUG:
    # Verbose logging in DEBUG mode.
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(name)s %(levelname)s %(message)s")

install_sensitive_logging_filters()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    # --- startup ---
    # Wire stdout/logger into the in-memory ring buffer so /v1/admin/debug/logs
    # can return recent lines without scraping Render Dashboard.
    from app.core import debug_log_buffer

    debug_log_buffer.install()
    yield
    # --- shutdown ---


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    docs_url=None if settings.APP_ENV == "production" else f"{settings.API_PREFIX}/docs",
    redoc_url=None if settings.APP_ENV == "production" else f"{settings.API_PREFIX}/redoc",
    openapi_url=None if settings.APP_ENV == "production" else f"{settings.API_PREFIX}/openapi.json",
    lifespan=lifespan,
)

# Security middleware (outermost = last to execute, first to respond)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware, redis_url=settings.REDIS_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Idempotency-Key"],
)

register_error_handlers(app)

app.include_router(auth_router, prefix=f"{settings.API_PREFIX}")
app.include_router(courses_router, prefix=f"{settings.API_PREFIX}", tags=["courses"])
app.include_router(course_approval_router, prefix=f"{settings.API_PREFIX}")
app.include_router(notifications_router, prefix=f"{settings.API_PREFIX}")
app.include_router(course_blueprints_router, prefix=f"{settings.API_PREFIX}")
app.include_router(scorm_router, prefix=f"{settings.API_PREFIX}", tags=["scorm"])
app.include_router(lessons_router, prefix=f"{settings.API_PREFIX}", tags=["lessons"])
app.include_router(ai_router, prefix=f"{settings.API_PREFIX}", tags=["ai-generation"])
app.include_router(enrollments_router, prefix=f"{settings.API_PREFIX}", tags=["enrollments"])
app.include_router(enrollments_stats_router, prefix=f"{settings.API_PREFIX}", tags=["enrollments"])
app.include_router(learning_cycles_router, prefix=f"{settings.API_PREFIX}", tags=["learning-cycles"])
app.include_router(assignment_access_router, prefix=f"{settings.API_PREFIX}", tags=["assignment-access"])
app.include_router(candidate_assessments_router, prefix=f"{settings.API_PREFIX}", tags=["candidate-assessments"])
app.include_router(candidate_assessment_public_router, prefix=f"{settings.API_PREFIX}", tags=["candidate-assessment"])
app.include_router(progress_router, prefix=f"{settings.API_PREFIX}", tags=["progress"])
app.include_router(documents_router, prefix=f"{settings.API_PREFIX}", tags=["documents"])
app.include_router(youtube_transcript_router, prefix=f"{settings.API_PREFIX}", tags=["youtube-transcript"])
app.include_router(quizzes_router, prefix=f"{settings.API_PREFIX}", tags=["quizzes"])
app.include_router(quiz_assignments_router, prefix=f"{settings.API_PREFIX}", tags=["quiz-assignments"])
app.include_router(certificates_router, prefix=f"{settings.API_PREFIX}", tags=["certificates"])
app.include_router(student_router, prefix=f"{settings.API_PREFIX}", tags=["student"])
app.include_router(learning_paths_router, prefix=f"{settings.API_PREFIX}", tags=["learning-paths"])
app.include_router(competencies_router, prefix=f"{settings.API_PREFIX}", tags=["competencies"])
app.include_router(announcements_router, prefix=f"{settings.API_PREFIX}", tags=["announcements"])
app.include_router(surveys_router, prefix=f"{settings.API_PREFIX}", tags=["surveys"])
app.include_router(support_router, prefix=f"{settings.API_PREFIX}", tags=["support"])
app.include_router(cohorts_router, prefix=f"{settings.API_PREFIX}", tags=["cohorts"])
app.include_router(audit_router, prefix=f"{settings.API_PREFIX}", tags=["audit"])
app.include_router(admin_router, prefix=f"{settings.API_PREFIX}", tags=["admin"])
app.include_router(provider_keys_router, prefix=f"{settings.API_PREFIX}", tags=["admin"])
app.include_router(superadmin_router, prefix=f"{settings.API_PREFIX}", tags=["admin"])
app.include_router(onboarding_router, prefix=f"{settings.API_PREFIX}", tags=["admin"])
app.include_router(demo_router, prefix=f"{settings.API_PREFIX}", tags=["demo"])
app.include_router(superadmin_login_router, prefix=f"{settings.API_PREFIX}")
app.include_router(users_router, prefix=f"{settings.API_PREFIX}", tags=["users"])
app.include_router(invitations_public_router, prefix=f"{settings.API_PREFIX}", tags=["invitations"])
app.include_router(kiosks_admin_router, prefix=f"{settings.API_PREFIX}", tags=["kiosks"])
app.include_router(kiosks_public_router, prefix=f"{settings.API_PREFIX}", tags=["kiosks"])
app.include_router(staff_import_router, prefix=f"{settings.API_PREFIX}", tags=["staff"])
app.include_router(staff_import_mapping_router, prefix=f"{settings.API_PREFIX}", tags=["staff"])
app.include_router(staff_import_sessions_router, prefix=f"{settings.API_PREFIX}")
app.include_router(staff_sync_router, prefix=f"{settings.API_PREFIX}")
app.include_router(telegram_router, prefix=f"{settings.API_PREFIX}", tags=["telegram"])
app.include_router(telegram_register_router, prefix=f"{settings.API_PREFIX}", tags=["auth"])
app.include_router(tenants_router, prefix=f"{settings.API_PREFIX}", tags=["tenants"])
app.include_router(tenants_public_router, prefix=f"{settings.API_PREFIX}", tags=["public"])
app.include_router(positions_router, prefix=f"{settings.API_PREFIX}", tags=["positions"])
app.include_router(positions_jd_router, prefix=f"{settings.API_PREFIX}", tags=["positions"])
app.include_router(positions_recommendations_router, prefix=f"{settings.API_PREFIX}", tags=["positions"])
app.include_router(positions_admin_router, prefix=f"{settings.API_PREFIX}", tags=["positions"])
app.include_router(positions_qualification_router, prefix=f"{settings.API_PREFIX}", tags=["positions"])
app.include_router(organization_units_router, prefix=f"{settings.API_PREFIX}")
app.include_router(departments_router, prefix=f"{settings.API_PREFIX}", tags=["departments"])
app.include_router(training_rules_router, prefix=f"{settings.API_PREFIX}", tags=["training-rules"])
app.include_router(integrations_router, prefix=f"{settings.API_PREFIX}", tags=["integrations"])
app.include_router(learner_assistant_router, prefix=f"{settings.API_PREFIX}", tags=["learner-assistant"])
app.include_router(training_log_router, prefix=f"{settings.API_PREFIX}", tags=["admin"])
app.include_router(training_evidence_router, prefix=f"{settings.API_PREFIX}", tags=["training-evidence"])
app.include_router(training_evidence_step_up_router, prefix=f"{settings.API_PREFIX}", tags=["training-evidence"])
app.include_router(training_evidence_export_router, prefix=f"{settings.API_PREFIX}", tags=["training-evidence"])
app.include_router(training_procedures_router, prefix=f"{settings.API_PREFIX}", tags=["training-procedures"])
app.include_router(training_retention_router, prefix=f"{settings.API_PREFIX}", tags=["training-retention"])


# Suppress Render health check spam in logs
class HealthCheckFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "health" not in record.getMessage().lower()


logging.getLogger("uvicorn.access").addFilter(HealthCheckFilter())


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
async def root_probe():
    return {"status": "ok", "app": settings.APP_NAME}


def _deployment_identity() -> dict[str, str]:
    release_sha = settings.RELEASE_SHA.strip() or os.getenv("RENDER_GIT_COMMIT", "").strip() or "unknown"
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "app_environment": settings.APP_ENV,
        "deployment_environment": settings.DEPLOYMENT_ENVIRONMENT,
        "release_sha": release_sha,
    }


@app.get("/health")
@app.get(f"{settings.API_PREFIX}/health")
async def health_check(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return _deployment_identity()
