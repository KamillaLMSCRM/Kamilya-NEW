"""Security headers middleware."""
from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlsplit

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    }

    CSP_DIRECTIVES = {
        "default-src": "'self'",
        "script-src": "'self' 'unsafe-inline'",
        "style-src": "'self' 'unsafe-inline'",
        "img-src": "'self' data: https:",
        "font-src": "'self'",
        "connect-src": "'self' https://api.kml.kz https://lms.kml.kz wss:",
        "frame-ancestors": "'none'",
        "base-uri": "'self'",
        "form-action": "'self'",
    }

    SCORM_CONTENT_CSP_DIRECTIVES = {
        "default-src": "'self'",
        "script-src": "'self' 'unsafe-inline'",
        "style-src": "'self' 'unsafe-inline'",
        "img-src": "'self' data: blob:",
        "font-src": "'self' data:",
        "media-src": "'self' blob:",
        "connect-src": "'self'",
        "frame-src": "'self'",
        "worker-src": "'self' blob:",
        "object-src": "'none'",
        "base-uri": "'none'",
        "form-action": "'self'",
    }

    @staticmethod
    def _is_scorm_content_request(request: Request) -> bool:
        settings = get_settings()
        if not settings.SCORM_CONTENT_ORIGIN:
            return False
        expected_host = urlsplit(settings.SCORM_CONTENT_ORIGIN).netloc.lower()
        actual_host = urlsplit(str(request.url)).netloc.lower()
        package_prefix = f"{settings.API_PREFIX}/scorm/packages/"
        return actual_host == expected_host and request.url.path.startswith(package_prefix)

    @staticmethod
    def _public_app_origin() -> str:
        parsed = urlsplit(get_settings().PUBLIC_URL.rstrip("/"))
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        if self._is_scorm_content_request(request):
            # Only the isolated SCORM hostname is frameable. The trusted API
            # origin continues to receive X-Frame-Options: DENY and
            # frame-ancestors 'none'.
            for header, value in self.HEADERS.items():
                if header != "X-Frame-Options":
                    response.headers[header] = value
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
            directives = {
                **self.SCORM_CONTENT_CSP_DIRECTIVES,
                "frame-ancestors": self._public_app_origin(),
            }
            response.headers["Content-Security-Policy"] = "; ".join(
                f"{key} {value}" for key, value in directives.items()
            )
            if "X-Frame-Options" in response.headers:
                del response.headers["X-Frame-Options"]
            return response

        for header, value in self.HEADERS.items():
            response.headers[header] = value

        csp = "; ".join(f"{k} {v}" for k, v in self.CSP_DIRECTIVES.items())
        response.headers["Content-Security-Policy"] = csp

        return response
