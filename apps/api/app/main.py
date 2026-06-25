import logging
import os
import subprocess
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
from app.modules.users.router import router as users_router
from app.modules.users.invitations_router import router as invitations_public_router
from app.modules.users.kiosk_router import admin_router as kiosks_admin_router, public_router as kiosks_public_router
from app.modules.auth.telegram import router as telegram_router
from app.modules.positions.router import router as positions_router

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    # --- startup ---
    _run_migrations()
    yield
    # --- shutdown ---


def _run_migrations():
    """Run alembic migrations on startup (Render doesn't do this automatically)."""
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
            logger.warning("Alembic warning: %s", result.stderr[:500])
        else:
            logger.info("Alembic migrations OK")
    except Exception as e:
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
app.include_router(users_router, prefix=f"{settings.API_PREFIX}", tags=["users"])
app.include_router(invitations_public_router, prefix=f"{settings.API_PREFIX}", tags=["invitations"])
app.include_router(kiosks_admin_router, prefix=f"{settings.API_PREFIX}", tags=["kiosks"])
app.include_router(kiosks_public_router, prefix=f"{settings.API_PREFIX}", tags=["kiosks"])
app.include_router(telegram_router, prefix=f"{settings.API_PREFIX}", tags=["telegram"])
app.include_router(positions_router, prefix=f"{settings.API_PREFIX}", tags=["positions"])

# Suppress Render health check spam in logs
class HealthCheckFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "health" not in record.getMessage().lower()

logging.getLogger("uvicorn.access").addFilter(HealthCheckFilter())


@app.get("/health")
@app.get(f"{settings.API_PREFIX}/health")
async def health_check():
    return {"status": "ok", "app": settings.APP_NAME}
