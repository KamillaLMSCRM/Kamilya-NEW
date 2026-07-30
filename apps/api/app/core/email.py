from __future__ import annotations

import logging
from html import escape

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class EmailService:
    @staticmethod
    def delivery_ready() -> bool:
        """Return whether transactional email can actually leave the service."""
        settings = get_settings()
        return (
            settings.EMAIL_PROVIDER.lower().strip() == "resend"
            and bool(settings.RESEND_API_KEY)
        )

    async def send_login_code(self, *, to_email: str, code: str) -> None:
        subject = "Kamilya LMS: код для входа"
        text = (
            f"Ваш код для входа в Kamilya LMS: {code}.\n\n"
            "Код действует 5 минут. Если вы не запрашивали код, просто проигнорируйте это письмо."
        )
        html = (
            "<p>Ваш код для входа в Kamilya LMS:</p>"
            f"<p style=\"font-size:28px;font-weight:700;letter-spacing:4px\">{code}</p>"
            "<p>Код действует 5 минут. Если вы не запрашивали код, просто проигнорируйте это письмо.</p>"
        )
        await self._send(to_email=to_email, subject=subject, text=text, html=html)

    async def send_trial_started(self, *, to_email: str, company_name: str) -> None:
        subject = "Kamilya LMS trial started"
        text = (
            f"Trial workspace for {company_name} has been created.\n\n"
            "You can sign in to Kamilya LMS with your email login code."
        )
        html = (
            f"<p>Trial workspace for <strong>{company_name}</strong> has been created.</p>"
            "<p>You can sign in to Kamilya LMS with your email login code.</p>"
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
            f"<p style=\"font-size:28px;font-weight:700;letter-spacing:4px\">{code}</p>"
            "<p>Код действует 5 минут. Никому не сообщайте его.</p>"
        )
        await self._send(to_email=to_email, subject=subject, text=text, html=html)

    async def send_announcement(self, *, to_email: str, company_name: str, title: str, body: str, course_title: str | None = None) -> None:
        subject = f"{company_name}: {title}"
        context = f"\nCourse: {course_title}" if course_title else ""
        text = f"{body}{context}\n\nKamilya LMS"
        html = f"<p>{escape(body).replace(chr(10), '<br>')}</p>"
        if course_title:
            html += f"<p><strong>Course:</strong> {escape(course_title)}</p>"
        await self._send(to_email=to_email, subject=subject, text=text, html=html)

    async def _send(self, *, to_email: str, subject: str, text: str, html: str) -> None:
        settings = get_settings()
        provider = settings.EMAIL_PROVIDER.lower().strip()

        if provider == "resend" and settings.RESEND_API_KEY:
            await self._send_resend(to_email=to_email, subject=subject, text=text, html=html)
            return

        logger.info("email queued provider=log to=%s subject=%s", to_email, subject)

    async def _send_resend(self, *, to_email: str, subject: str, text: str, html: str) -> None:
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
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post("https://api.resend.com/emails", json=payload, headers=headers)
        if response.status_code >= 400:
            logger.error("resend send failed status=%s body=%s", response.status_code, response.text[:500])
            response.raise_for_status()
