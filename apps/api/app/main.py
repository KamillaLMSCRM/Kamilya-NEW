import logging
import os
import subprocess
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
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
from app.modules.positions.models import Position  # noqa: F401

from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.rate_limit import RateLimitMiddleware
from app.core.security import SecurityHeadersMiddleware
from app.modules.auth.router import router as auth_router
from app.modules.courses.router import router as courses_router
from app.modules.lessons.router import router as lessons_router
from app.modules.ai.router import router as ai_router
from app.modules.enrollments.router import router as enrollments_router, stats_router as enrollments_stats_router
from app.modules.progress.router import router as progress_router
from app.modules.documents.router import router as documents_router
from app.modules.quizzes.router import router as quizzes_router
from app.modules.quizzes.assignment_router import router as quiz_assignments_router
from app.modules.certificates.router import router as certificates_router
from app.modules.student.router import router as student_router
from app.modules.audit.router import router as audit_router
from app.modules.admin.router import router as admin_router
from app.modules.admin.provider_keys.router import router as provider_keys_router
from app.modules.admin.superadmin.router import router as superadmin_router
from app.modules.demo.router import router as demo_router
from app.modules.auth.superadmin_login import router as superadmin_login_router
from app.modules.users.router import router as users_router
from app.modules.users.invitations_router import router as invitations_public_router
from app.modules.users.kiosk_router import admin_router as kiosks_admin_router, public_router as kiosks_public_router
from app.modules.users.staff_import_router import router as staff_import_router
from app.modules.auth.telegram import router as telegram_router
from app.modules.auth.telegram_register import router as telegram_register_router
from app.modules.tenants.router import public_router as tenants_public_router, router as tenants_router
from app.modules.positions.router import router as positions_router
from app.modules.positions.jd_router import router as positions_jd_router
from app.modules.positions.recommendations_router import router as positions_recommendations_router
from app.modules.positions.admin_router import router as positions_admin_router
from app.modules.departments.router import router as departments_router
from app.modules.integrations.router import router as integrations_router

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
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        from sentry_sdk.integrations.asyncpg import AsyncpgIntegration

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
                None
                if event.get("transaction") in ("/api/v1/health", "GET /api/v1/health")
                else event
            ),
            # PII: scrub Authorization header, cookies, password fields.
            send_default_pii=False,
        )
        logger.info("Sentry initialized (env=%s)", settings.APP_ENV)
    except ImportError:
        logger.warning(
            "SENTRY_DSN is set but sentry-sdk is not installed; skipping"
        )


# Structured JSON logging in production. In dev/staging we keep the
# human-readable formatter because JSON in a terminal is hard to read.
if settings.APP_ENV == "production" and _HAS_JSON_LOGGER:
    handler = logging.StreamHandler()
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    # --- startup ---
    _run_migrations()
    # Wire stdout/logger into the in-memory ring buffer so /v1/admin/debug/logs
    # can return recent lines without scraping Render Dashboard.
    from app.core import debug_log_buffer
    debug_log_buffer.install()
    yield
    # --- shutdown ---


def _run_migrations():
    """Run alembic migrations on startup (Render doesn't do this automatically)."""
    import traceback
    try:
        venv_bin = os.path.dirname(sys.executable)
        alembic_bin = os.path.join(venv_bin, "alembic")
        if not os.path.exists(alembic_bin):
            alembic_bin = os.path.join(venv_bin, "alembic.exe")
        result = subprocess.run(
            [alembic_bin, "-c", "alembic.ini", "upgrade", "head"],
            cwd=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            print(f"[alembic] FAILED stdout={result.stdout[:500]} stderr={result.stderr[:500]}", flush=True)
            logger.warning("Alembic warning: %s", result.stderr[:500])
        else:
            print("[alembic] OK", flush=True)
            logger.info("Alembic migrations OK")
    except Exception as e:
        print(f"[alembic] EXC {e.__class__.__name__}: {e}", flush=True)
        print(traceback.format_exc(), flush=True)
        logger.error("Alembic error (non-fatal): %s", e)


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    docs_url=f"{settings.API_PREFIX}/docs",
    redoc_url=f"{settings.API_PREFIX}/redoc",
    openapi_url=f"{settings.API_PREFIX}/openapi.json",
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
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

register_error_handlers(app)

app.include_router(auth_router, prefix=f"{settings.API_PREFIX}")
app.include_router(courses_router, prefix=f"{settings.API_PREFIX}", tags=["courses"])
app.include_router(lessons_router, prefix=f"{settings.API_PREFIX}", tags=["lessons"])
app.include_router(ai_router, prefix=f"{settings.API_PREFIX}", tags=["ai-generation"])
app.include_router(enrollments_router, prefix=f"{settings.API_PREFIX}", tags=["enrollments"])
app.include_router(enrollments_stats_router, prefix=f"{settings.API_PREFIX}", tags=["enrollments"])
app.include_router(progress_router, prefix=f"{settings.API_PREFIX}", tags=["progress"])
app.include_router(documents_router, prefix=f"{settings.API_PREFIX}", tags=["documents"])
app.include_router(quizzes_router, prefix=f"{settings.API_PREFIX}", tags=["quizzes"])
app.include_router(quiz_assignments_router, prefix=f"{settings.API_PREFIX}", tags=["quiz-assignments"])
app.include_router(certificates_router, prefix=f"{settings.API_PREFIX}", tags=["certificates"])
app.include_router(student_router, prefix=f"{settings.API_PREFIX}", tags=["student"])
app.include_router(audit_router, prefix=f"{settings.API_PREFIX}", tags=["audit"])
app.include_router(admin_router, prefix=f"{settings.API_PREFIX}", tags=["admin"])
app.include_router(provider_keys_router, prefix=f"{settings.API_PREFIX}", tags=["admin"])
app.include_router(superadmin_router, prefix=f"{settings.API_PREFIX}", tags=["admin"])
app.include_router(demo_router, prefix=f"{settings.API_PREFIX}", tags=["demo"])
app.include_router(superadmin_login_router, prefix=f"{settings.API_PREFIX}")
app.include_router(users_router, prefix=f"{settings.API_PREFIX}", tags=["users"])
app.include_router(invitations_public_router, prefix=f"{settings.API_PREFIX}", tags=["invitations"])
app.include_router(kiosks_admin_router, prefix=f"{settings.API_PREFIX}", tags=["kiosks"])
app.include_router(kiosks_public_router, prefix=f"{settings.API_PREFIX}", tags=["kiosks"])
app.include_router(staff_import_router, prefix=f"{settings.API_PREFIX}", tags=["staff"])
app.include_router(telegram_router, prefix=f"{settings.API_PREFIX}", tags=["telegram"])
app.include_router(telegram_register_router, prefix=f"{settings.API_PREFIX}", tags=["auth"])
app.include_router(tenants_router, prefix=f"{settings.API_PREFIX}", tags=["tenants"])
app.include_router(tenants_public_router, prefix=f"{settings.API_PREFIX}", tags=["public"])
app.include_router(positions_router, prefix=f"{settings.API_PREFIX}", tags=["positions"])
app.include_router(positions_jd_router, prefix=f"{settings.API_PREFIX}", tags=["positions"])
app.include_router(positions_recommendations_router, prefix=f"{settings.API_PREFIX}", tags=["positions"])
app.include_router(positions_admin_router, prefix=f"{settings.API_PREFIX}", tags=["positions"])
app.include_router(departments_router, prefix=f"{settings.API_PREFIX}", tags=["departments"])
app.include_router(integrations_router, prefix=f"{settings.API_PREFIX}", tags=["integrations"])

# Suppress Render health check spam in logs
class HealthCheckFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "health" not in record.getMessage().lower()

logging.getLogger("uvicorn.access").addFilter(HealthCheckFilter())


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
async def root_probe():
    return {"status": "ok", "app": settings.APP_NAME}


@app.get("/health")
@app.get(f"{settings.API_PREFIX}/health")
async def health_check():
    return {"status": "ok", "app": settings.APP_NAME}
