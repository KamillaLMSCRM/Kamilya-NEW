"""Single browser-session policy for refresh-token cookie flows."""

from collections.abc import Sequence
from typing import Literal
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Response

from app.core.config import get_settings

REFRESH_COOKIE_NAME = "kamilya_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"
CookieProfile = Literal["same_site", "cross_site"]


def _normalize_origin(value: str) -> str:
    origin = value.strip()
    parsed = urlsplit(origin)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("origin must contain only an HTTP(S) scheme and authority")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("origin has an invalid port") from exc
    hostname = parsed.hostname.lower()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    authority = f"{hostname}:{port}" if port is not None else hostname
    return f"{parsed.scheme.lower()}://{authority}"


class BrowserSessionPolicy:
    """Validate browser requests and own the complete refresh-cookie contract."""

    def __init__(
        self,
        *,
        environment: str,
        deployment_environment: str,
        application_origin: str,
        trusted_origins: Sequence[str],
        cookie_profile: CookieProfile,
        cookie_secure: bool,
        allow_legacy_refresh_body: bool,
        refresh_max_age_seconds: int,
    ) -> None:
        self.environment = environment.strip().lower()
        self.deployment_environment = deployment_environment.strip().lower()
        self.is_production = self.environment == "production"
        if cookie_profile not in {"same_site", "cross_site"}:
            raise ValueError("AUTH_COOKIE_PROFILE must be same_site or cross_site")
        if refresh_max_age_seconds <= 0:
            raise ValueError("refresh cookie lifetime must be positive")
        if (
            self.is_production
            and cookie_profile == "cross_site"
            and self.deployment_environment != "render-development"
        ):
            raise ValueError("cross_site cookie profile is allowed only for explicit development topology")
        if (self.is_production or cookie_profile == "cross_site") and not cookie_secure:
            raise ValueError("secure refresh cookies are required for this environment/profile")
        if self.is_production and allow_legacy_refresh_body:
            raise ValueError("legacy refresh-token body fallback is forbidden in production")

        try:
            normalized_application_origin = _normalize_origin(application_origin)
            origins = frozenset(_normalize_origin(origin) for origin in trusted_origins)
        except (TypeError, ValueError) as exc:
            raise ValueError("PUBLIC_URL or AUTH_BROWSER_ORIGINS contains an invalid origin") from exc
        if not origins:
            raise ValueError("AUTH_BROWSER_ORIGINS must contain at least one trusted origin")
        if self.is_production and any(not origin.startswith("https://") for origin in origins):
            raise ValueError("AUTH_BROWSER_ORIGINS must use HTTPS in production")
        if self.is_production and not normalized_application_origin.startswith("https://"):
            raise ValueError("PUBLIC_URL must use HTTPS in production")
        if (
            self.is_production
            and self.deployment_environment != "render-development"
            and origins != {normalized_application_origin}
        ):
            raise ValueError("AUTH_BROWSER_ORIGINS must exactly match PUBLIC_URL in KZ production")

        self.application_origin = normalized_application_origin
        self.trusted_origins = origins
        self.cookie_profile = cookie_profile
        self.cookie_secure = cookie_secure
        self.allow_legacy_refresh_body = allow_legacy_refresh_body
        self.refresh_max_age_seconds = refresh_max_age_seconds

    @staticmethod
    def _reject(status_code: int, code: str, message: str) -> None:
        raise HTTPException(status_code=status_code, detail={"code": code, "message": message})

    def enforce_request(self, request: Request) -> None:
        """Reject an untrusted browser-session request before caller side effects."""
        fetch_site = request.headers.get("sec-fetch-site", "").strip().lower()
        if fetch_site == "cross-site" and self.cookie_profile != "cross_site":
            self._reject(403, "cross_site_request_forbidden", "Cross-site browser request is not allowed.")

        raw_origin = request.headers.get("origin")
        if raw_origin is None or not raw_origin.strip():
            if self.is_production:
                self._reject(403, "browser_origin_required", "A trusted browser Origin is required.")
        else:
            try:
                origin = _normalize_origin(raw_origin)
            except ValueError:
                self._reject(403, "browser_origin_forbidden", "Browser Origin is not trusted.")
                return
            if origin not in self.trusted_origins:
                self._reject(403, "browser_origin_forbidden", "Browser Origin is not trusted.")

        if self.is_production:
            media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if media_type != "application/json":
                self._reject(400, "browser_json_required", "Browser session requests must use JSON.")

    def read_refresh_token(self, request: Request, body_token: str | None = None) -> str | None:
        self.enforce_request(request)
        cookie_token = request.cookies.get(REFRESH_COOKIE_NAME)
        if cookie_token:
            return cookie_token
        if body_token:
            if not self.allow_legacy_refresh_body:
                self._reject(
                    400,
                    "legacy_refresh_body_forbidden",
                    "Refresh tokens in request bodies are not accepted.",
                )
            return body_token
        return None

    def set_refresh_cookie(self, response: Response, refresh_token: str) -> None:
        response.set_cookie(
            key=REFRESH_COOKIE_NAME,
            value=refresh_token,
            max_age=self.refresh_max_age_seconds,
            path=REFRESH_COOKIE_PATH,
            httponly=True,
            secure=self.cookie_secure,
            samesite="none" if self.cookie_profile == "cross_site" else "lax",
        )
        if self.cookie_profile == "cross_site":
            self._append_partitioned(response)

    def clear_refresh_cookie(self, response: Response) -> None:
        response.set_cookie(
            key=REFRESH_COOKIE_NAME,
            value="",
            max_age=0,
            path=REFRESH_COOKIE_PATH,
            httponly=True,
            secure=self.cookie_secure,
            samesite="none" if self.cookie_profile == "cross_site" else "lax",
        )
        if self.cookie_profile == "cross_site":
            self._append_partitioned(response)

    @staticmethod
    def _append_partitioned(response: Response) -> None:
        prefix = f"{REFRESH_COOKIE_NAME}=".lower().encode()
        for index in range(len(response.raw_headers) - 1, -1, -1):
            key, value = response.raw_headers[index]
            if key.lower() == b"set-cookie" and value.lower().startswith(prefix):
                if b"partitioned" not in value.lower():
                    response.raw_headers[index] = (key, value + b"; Partitioned")
                return


def get_browser_session_policy() -> BrowserSessionPolicy:
    settings = get_settings()
    return BrowserSessionPolicy(
        environment=settings.APP_ENV,
        deployment_environment=settings.DEPLOYMENT_ENVIRONMENT,
        application_origin=settings.PUBLIC_URL,
        trusted_origins=settings.AUTH_BROWSER_ORIGINS,
        cookie_profile=settings.AUTH_COOKIE_PROFILE,
        cookie_secure=settings.AUTH_COOKIE_SECURE,
        allow_legacy_refresh_body=settings.AUTH_REFRESH_BODY_FALLBACK,
        refresh_max_age_seconds=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )
