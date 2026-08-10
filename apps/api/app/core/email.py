from __future__ import annotations

import logging
from html import escape

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def _subject_component(value: str, *, fallback: str) -> str:
    """Keep tenant-controlled text on one bounded email subject line."""

    normalized = " ".join(value.splitlines()).strip()
    return (normalized or fallback)[:160]


class EmailDeliveryError(RuntimeError):
    """Provider failure with a safe, non-payload error description."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.message = message


class EmailService:
    @staticmethod
    def delivery_ready() -> bool:
        """Return whether transactional email can actually leave the service."""
        settings = get_settings()
        return settings.EMAIL_PROVIDER.lower().strip() == "resend" and bool(settings.RESEND_API_KEY)

    async def send_login_code(self, *, to_email: str, code: str) -> None:
        subject = "Kamilya LMS: код для входа"
        text = (
            f"Ваш код для входа в Kamilya LMS: {code}.\n\n"
            "Код действует 5 минут. Если вы не запрашивали код, просто проигнорируйте это письмо."
        )
        html = (
            "<p>Ваш код для входа в Kamilya LMS:</p>"
            f'<p style="font-size:28px;font-weight:700;letter-spacing:4px">{code}</p>'
            "<p>Код действует 5 минут. Если вы не запрашивали код, просто проигнорируйте это письмо.</p>"
        )
        await self._send(to_email=to_email, subject=subject, text=text, html=html)

    async def send_trial_started(self, *, to_email: str, company_name: str) -> None:
        subject = "Kamilya LMS trial started"
        text = (
            f"Trial workspace for {company_name} has been created.\n\n"
            "You can sign in to Kamilya LMS with your email login code.\n\n"
            "Contact: askar@kml.kz · +7 707 275 0007"
        )
        html = (
            f"<p>Trial workspace for <strong>{company_name}</strong> has been created.</p>"
            "<p>You can sign in to Kamilya LMS with your email login code.</p>"
            "<p>Contact: <a href=\"mailto:askar@kml.kz\">askar@kml.kz</a> · +7 707 275 0007</p>"
        )
        await self._send(to_email=to_email, subject=subject, text=text, html=html)

    async def send_invitation_code(
        self,
        *,
        to_email: str,
        code: str,
        company_name: str,
        learner_name: str,
    ) -> None:
        safe_company = escape(company_name)
        safe_name = escape(learner_name)
        subject = f"{company_name}: код подтверждения приглашения"
        text = (
            f"{learner_name}, подтвердите доступ к обучению в {company_name}.\n\n"
            f"Код: {code}\n\n"
            "Код действует 5 минут. Никому не сообщайте его."
        )
        html = (
            f"<p>{safe_name}, подтвердите доступ к обучению в "
            f"<strong>{safe_company}</strong>.</p>"
            "<p>Код подтверждения:</p>"
            f'<p style="font-size:28px;font-weight:700;letter-spacing:4px">{code}</p>'
            "<p>Код действует 5 минут. Никому не сообщайте его.</p>"
        )
        await self._send(to_email=to_email, subject=subject, text=text, html=html)

    async def send_invitation_link(
        self,
        *,
        to_email: str,
        invite_url: str,
        company_name: str,
        learner_name: str,
        language: str = "ru",
    ) -> str | None:
        """Send the initial activation link and return the provider message id."""
        language = language if language in {"ru", "kk", "en"} else "ru"
        subject_company = _subject_component(company_name, fallback="Kamilya LMS")
        safe_company = escape(company_name)
        safe_name = escape(learner_name)
        safe_url = escape(invite_url, quote=True)
        if language == "kk":
            subject = f"{subject_company}: Kamilya LMS жүйесіне шақыру"
            text = (
                f"{learner_name}, сізге {company_name} ұйымының Kamilya LMS жүйесіне шақыруы жіберілді.\n\n"
                f"Жүйеге кіруді белсендіру үшін мына сілтемені ашыңыз: {invite_url}\n\n"
                "Сілтеменің жарамдылық мерзімі ұйымның шақыру саясатына сәйкес шектеулі."
            )
            html = (
                f"<p>{safe_name}, сізге <strong>{safe_company}</strong> ұйымының "
                "Kamilya LMS жүйесіне шақыруы жіберілді.</p>"
                f'<p><a href="{safe_url}">Шақыруды ашу және қолжетімділікті белсендіру</a></p>'
                "<p>Сілтеменің жарамдылық мерзімі ұйымның шақыру саясатына сәйкес шектеулі.</p>"
            )
        elif language == "en":
            subject = f"{subject_company}: invitation to Kamilya LMS"
            text = (
                f"{learner_name}, {company_name} has invited you to Kamilya LMS.\n\n"
                f"Open this activation link to continue: {invite_url}\n\n"
                "This activation link expires according to your organization's invitation policy."
            )
            html = (
                f"<p>{safe_name}, <strong>{safe_company}</strong> has invited you to Kamilya LMS.</p>"
                f'<p><a href="{safe_url}">Open the activation link</a></p>'
                "<p>This activation link expires according to your organization's invitation policy.</p>"
            )
        else:
            subject = f"{subject_company}: приглашение в Kamilya LMS"
            text = (
                f"{learner_name}, организация {company_name} пригласила вас в Kamilya LMS.\n\n"
                f"Откройте ссылку активации, чтобы продолжить: {invite_url}\n\n"
                "Срок действия ссылки активации ограничен и определяется политикой приглашений вашей организации."
            )
            html = (
                f"<p>{safe_name}, организация <strong>{safe_company}</strong> пригласила вас в Kamilya LMS.</p>"
                f'<p><a href="{safe_url}">Открыть ссылку активации</a></p>'
                "<p>Срок действия ссылки активации ограничен и определяется политикой приглашений вашей организации.</p>"
            )
        return await self._send(to_email=to_email, subject=subject, text=text, html=html)

    async def send_course_assignment(
        self,
        *,
        to_email: str,
        company_name: str,
        learner_name: str,
        course_title: str,
        access_url: str,
        activation_required: bool,
        idempotency_key: str,
    ) -> str | None:
        subject = f"{_subject_component(company_name, fallback='Kamilya LMS')}: назначен курс"
        action = "Активируйте доступ и откройте курс" if activation_required else "Откройте назначенный курс"
        text = f"{learner_name}, {company_name} назначила вам курс «{course_title}».\n\n{action}: {access_url}"
        html = f'<p>{escape(learner_name)}, организация <strong>{escape(company_name)}</strong> назначила вам курс <strong>{escape(course_title)}</strong>.</p><p><a href="{escape(access_url, quote=True)}">{action}</a></p>'
        return await self._send(
            to_email=to_email,
            subject=subject,
            text=text,
            html=html,
            idempotency_key=idempotency_key,
        )

    async def send_training_confirmation_code(
        self,
        *,
        to_email: str,
        code: str,
        company_name: str,
    ) -> None:
        """Send the purpose-bound learner confirmation code."""

        safe_company = escape(company_name)
        subject = "Kamilya LMS: подтверждение прохождения обучения"
        text = (
            f"Подтвердите действие в Kamilya LMS для организации «{company_name}».\n\n"
            f"Одноразовый код: {code}\n\n"
            "Код действует 5 минут и предназначен только для этого подтверждения. "
            "Никому не сообщайте код. Если вы не запрашивали подтверждение, проигнорируйте письмо."
        )
        html = (
            f"<p>Подтвердите действие в Kamilya LMS для организации «<strong>{safe_company}</strong>».</p>"
            f'<p style="font-size:28px;font-weight:700;letter-spacing:4px">{code}</p>'
            "<p>Код действует 5 минут и предназначен только для этого подтверждения. "
            "Никому не сообщайте код.</p>"
        )
        await self._send(to_email=to_email, subject=subject, text=text, html=html)

    async def send_announcement(
        self, *, to_email: str, company_name: str, title: str, body: str, course_title: str | None = None
    ) -> None:
        subject = f"{company_name}: {title}"
        context = f"\nCourse: {course_title}" if course_title else ""
        text = f"{body}{context}\n\nKamilya LMS"
        html = f"<p>{escape(body).replace(chr(10), '<br>')}</p>"
        if course_title:
            html += f"<p><strong>Course:</strong> {escape(course_title)}</p>"
        await self._send(to_email=to_email, subject=subject, text=text, html=html)

    async def _send(
        self,
        *,
        to_email: str,
        subject: str,
        text: str,
        html: str,
        idempotency_key: str | None = None,
    ) -> str | None:
        settings = get_settings()
        provider = settings.EMAIL_PROVIDER.lower().strip()

        if provider == "resend" and settings.RESEND_API_KEY:
            return await self._send_resend(
                to_email=to_email,
                subject=subject,
                text=text,
                html=html,
                idempotency_key=idempotency_key,
            )

        logger.info("email_queued", extra={"provider": "log"})
        return None

    async def _send_resend(
        self,
        *,
        to_email: str,
        subject: str,
        text: str,
        html: str,
        idempotency_key: str | None = None,
    ) -> str | None:
        settings = get_settings()
        payload = {
            "from": settings.EMAIL_FROM,
            "to": [to_email],
            "subject": subject,
            "text": text,
            "html": html,
        }
        headers = {
            "Authorization": f"Bearer {settings.RESEND_API_KEY}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post("https://api.resend.com/emails", json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise EmailDeliveryError("provider_timeout", "The email provider did not respond in time.") from exc
        except httpx.RequestError as exc:
            raise EmailDeliveryError("provider_unreachable", "The email provider could not be reached.") from exc
        if response.status_code >= 400:
            logger.error("resend send failed status=%s", response.status_code)
            if response.status_code == 429:
                category = "provider_rate_limited"
            elif response.status_code >= 500:
                category = "provider_unavailable"
            else:
                category = "provider_rejected"
            raise EmailDeliveryError(
                category,
                f"The email provider rejected the message (HTTP {response.status_code}).",
            )
        try:
            response_data = response.json()
        except ValueError:
            return None
        message_id = response_data.get("id") if isinstance(response_data, dict) else None
        return str(message_id) if message_id else None
