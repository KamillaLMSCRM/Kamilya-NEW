from __future__ import annotations

import logging

import httpx

from app.core.config import get_settings


logger = logging.getLogger(__name__)


class EmailService:
    async def send_login_code(self, *, to_email: str, code: str) -> None:
        settings = get_settings()
        subject = "Kamilya LMS login code"
        text = (
            f"Your Kamilya LMS login code is {code}.\n\n"
            "The code expires in 5 minutes. If you did not request it, ignore this email."
        )
        html = (
            "<p>Your Kamilya LMS login code:</p>"
            f"<p style=\"font-size:28px;font-weight:700;letter-spacing:4px\">{code}</p>"
            "<p>The code expires in 5 minutes. If you did not request it, ignore this email.</p>"
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

    async def _send(self, *, to_email: str, subject: str, text: str, html: str) -> None:
        settings = get_settings()
        provider = settings.EMAIL_PROVIDER.lower().strip()

        if provider == "resend" and settings.RESEND_API_KEY:
            await self._send_resend(to_email=to_email, subject=subject, text=text, html=html)
            return

        logger.info("email queued provider=log to=%s subject=%s body=%s", to_email, subject, text)

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
