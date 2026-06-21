"""Security headers middleware."""
from __future__ import annotations

from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


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
        "script-src": "'self' 'unsafe-inline' 'unsafe-eval'",
        "style-src": "'self' 'unsafe-inline'",
        "img-src": "'self' data: https:",
        "font-src": "'self'",
        "connect-src": "'self' https://api.kml.kz https://lms.kml.kz wss:",
        "frame-ancestors": "'none'",
        "base-uri": "'self'",
        "form-action": "'self'",
    }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        for header, value in self.HEADERS.items():
            response.headers[header] = value

        csp = "; ".join(f"{k} {v}" for k, v in self.CSP_DIRECTIVES.items())
        response.headers["Content-Security-Policy"] = csp

        return response
