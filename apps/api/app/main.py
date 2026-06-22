from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.rate_limit import RateLimitMiddleware
from app.core.security import SecurityHeadersMiddleware
from app.modules.auth.router import router as auth_router
from app.modules.courses.router import router as courses_router
from app.modules.lessons.router import router as lessons_router
from app.modules.ai.router import router as ai_router
from app.modules.enrollments.router import router as enrollments_router
from app.modules.progress.router import router as progress_router
from app.modules.documents.router import router as documents_router
from app.modules.quizzes.router import router as quizzes_router
from app.modules.certificates.router import router as certificates_router
from app.modules.student.router import router as student_router
from app.modules.audit.router import router as audit_router
from app.modules.admin.router import router as admin_router
from app.modules.users.router import router as users_router
from app.modules.auth.telegram import router as telegram_router
from app.modules.positions.router import router as positions_router

settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    docs_url=f"{settings.API_PREFIX}/docs",
    redoc_url=f"{settings.API_PREFIX}/redoc",
    openapi_url=f"{settings.API_PREFIX}/openapi.json",
)

# Security middleware (outermost = last to execute, first to respond)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware, redis_url=settings.REDIS_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

app.include_router(auth_router, prefix=f"{settings.API_PREFIX}")
app.include_router(courses_router, prefix=f"{settings.API_PREFIX}", tags=["courses"])
app.include_router(lessons_router, prefix=f"{settings.API_PREFIX}", tags=["lessons"])
app.include_router(ai_router, prefix=f"{settings.API_PREFIX}", tags=["ai-generation"])
app.include_router(enrollments_router, prefix=f"{settings.API_PREFIX}", tags=["enrollments"])
app.include_router(progress_router, prefix=f"{settings.API_PREFIX}", tags=["progress"])
app.include_router(documents_router, prefix=f"{settings.API_PREFIX}", tags=["documents"])
app.include_router(quizzes_router, prefix=f"{settings.API_PREFIX}", tags=["quizzes"])
app.include_router(certificates_router, prefix=f"{settings.API_PREFIX}", tags=["certificates"])
app.include_router(student_router, prefix=f"{settings.API_PREFIX}", tags=["student"])
app.include_router(audit_router, prefix=f"{settings.API_PREFIX}", tags=["audit"])
app.include_router(admin_router, prefix=f"{settings.API_PREFIX}", tags=["admin"])
app.include_router(users_router, prefix=f"{settings.API_PREFIX}", tags=["users"])
app.include_router(telegram_router, prefix=f"{settings.API_PREFIX}", tags=["telegram"])
app.include_router(positions_router, prefix=f"{settings.API_PREFIX}", tags=["positions"])


@app.get("/health")
@app.get(f"{settings.API_PREFIX}/health")
async def health_check():
    return {"status": "ok", "app": settings.APP_NAME}


@app.on_event("startup")
async def run_migrations():
    """Run alembic migrations on startup (Render doesn't do this automatically)."""
    import subprocess
    import os
    try:
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            print(f"Alembic warning: {result.stderr[:500]}")
        else:
            print("Alembic migrations applied successfully")
    except Exception as e:
        print(f"Alembic migration error (non-fatal): {e}")
