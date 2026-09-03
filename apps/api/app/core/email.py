from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from dataclasses import dataclass, fields
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
from hashlib import sha256
from html import escape
from uuid import UUID

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PublicLeadNotification:
    """Immutable, bounded copy of a successfully stored public application."""

    lead_id: UUID
    received_at: datetime
    name: str
    company: str
    email: str
    phone: str | None = None
    company_size: int | None = None
    industry: str | None = None
    interest: str | None = None
    message: str | None = None
    locale: str | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    utm_term: str | None = None
    gclid: str | None = None
    referrer: str | None = None
    landing_page: str | None = None
    attribution_captured_at: datetime | None = None
    consent_version: str | None = None
    source_section: str | None = None
    plan: str | None = None
    roi_employees: int | None = None
    roi_industry: str | None = None
    roi_employee_band: str | None = None
    roi_formula_version: str | None = None


_PUBLIC_LEAD_LABELS = {
    "lead_id": "ID заявки",
    "received_at": "Получена",
    "name": "Имя",
    "company": "Компания",
    "email": "Email",
    "phone": "Телефон",
    "company_size": "Количество сотрудников",
    "industry": "Сфера",
    "interest": "Интерес",
    "message": "Комментарий",
    "locale": "Язык",
    "utm_source": "UTM source",
    "utm_medium": "UTM medium",
    "utm_campaign": "UTM campaign",
    "utm_content": "UTM content",
    "utm_term": "UTM term",
    "gclid": "Google Click ID",
    "referrer": "Источник перехода",
    "landing_page": "Страница заявки",
    "attribution_captured_at": "Атрибуция зафиксирована",
    "consent_version": "Версия согласия",
    "source_section": "Раздел формы",
    "plan": "План",
    "roi_employees": "Сотрудников в расчёте",
    "roi_industry": "Сфера в расчёте",
    "roi_employee_band": "Диапазон сотрудников",
    "roi_formula_version": "Версия расчёта",
}


def _public_lead_rows(notification: PublicLeadNotification) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for field in fields(notification):
        value = getattr(notification, field.name)
        if isinstance(value, datetime):
            rendered = value.isoformat()
        elif value is None or value == "":
            rendered = "—"
        else:
            rendered = str(value)
        rows.append((_PUBLIC_LEAD_LABELS[field.name], rendered))
    return rows


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
        provider = settings.EMAIL_PROVIDER.lower().strip()
        if provider == "resend":
            return bool(settings.RESEND_API_KEY)
        if provider == "smtp":
            return bool(
                settings.SMTP_HOST
                and settings.SMTP_PORT
                and settings.EMAIL
                and settings.EMAIL_PASSWORD
            )
        return False

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

    async def send_registration_code(self, *, to_email: str, code: str) -> None:
        subject = "Kamilya LMS: подтверждение email"
        text = (
            f"Код подтверждения email для регистрации в Kamilya LMS: {code}.\n\n"
            "Код действует 5 минут. Tenant будет создан только после ввода кода. "
            "Если вы не начинали регистрацию, проигнорируйте письмо."
        )
        html = (
            "<p>Подтвердите email для регистрации в Kamilya LMS:</p>"
            f'<p style="font-size:28px;font-weight:700;letter-spacing:4px">{code}</p>'
            "<p>Код действует 5 минут. Tenant будет создан только после ввода кода.</p>"
            "<p>Если вы не начинали регистрацию, проигнорируйте письмо.</p>"
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

    async def send_team_member_welcome(
        self,
        *,
        to_email: str,
        company_name: str,
        member_name: str,
        login_url: str,
        password_configured: bool,
        user_id: UUID,
        language: str = "ru",
    ) -> str | None:
        """Send first-access instructions after a team account is durable."""
        language = language if language in {"ru", "kk", "en"} else "ru"
        subject_company = _subject_component(company_name, fallback="Kamilya LMS")
        safe_company = escape(company_name)
        safe_name = escape(member_name)
        safe_url = escape(login_url, quote=True)

        if language == "kk":
            subject = f"{subject_company}: Kamilya LMS жүйесіне қолжетімділік"
            password_note = (
                "Әкімші орнатқан құпиясөзбен немесе email-ге келетін бір реттік кодпен кіре аласыз."
                if password_configured
                else "Кіру бетінде «Email коды» тәсілін таңдап, бір реттік код алыңыз."
            )
            text = f"{member_name}, {company_name} ұйымының Kamilya LMS командасына қосылдыңыз.\n\n{password_note}\n\nКіру: {login_url}"
            html = f"<p>{safe_name}, сіз <strong>{safe_company}</strong> ұйымының Kamilya LMS командасына қосылдыңыз.</p><p>{escape(password_note)}</p><p><a href=\"{safe_url}\">Kamilya LMS жүйесіне кіру</a></p>"
        elif language == "en":
            subject = f"{subject_company}: access to Kamilya LMS"
            password_note = (
                "Sign in with the password set by your administrator or request a one-time email code."
                if password_configured
                else "On the sign-in page, choose Email code and request a one-time code."
            )
            text = f"{member_name}, you have been added to the {company_name} team in Kamilya LMS.\n\n{password_note}\n\nSign in: {login_url}"
            html = f"<p>{safe_name}, you have been added to the <strong>{safe_company}</strong> team in Kamilya LMS.</p><p>{escape(password_note)}</p><p><a href=\"{safe_url}\">Sign in to Kamilya LMS</a></p>"
        else:
            subject = f"{subject_company}: доступ к Kamilya LMS"
            password_note = (
                "Вы можете войти по паролю, заданному администратором, или получить одноразовый код на email."
                if password_configured
                else "На странице входа выберите «Код на email» и получите одноразовый код."
            )
            text = f"{member_name}, вас добавили в команду {company_name} в Kamilya LMS.\n\n{password_note}\n\nВойти: {login_url}"
            html = f"<p>{safe_name}, вас добавили в команду <strong>{safe_company}</strong> в Kamilya LMS.</p><p>{escape(password_note)}</p><p><a href=\"{safe_url}\">Войти в Kamilya LMS</a></p>"

        return await self._send(
            to_email=to_email,
            subject=subject,
            text=text,
            html=html,
            idempotency_key=f"team-member-welcome/{user_id}",
        )

    async def send_public_lead_notification(
        self,
        *,
        to_email: str,
        notification: PublicLeadNotification,
    ) -> str | None:
        """Send the complete stored lead copy to the configured operator."""

        rows = _public_lead_rows(notification)
        recipient_key = sha256(to_email.strip().lower().encode("utf-8")).hexdigest()[:16]
        subject = "Kamilya LMS: новая заявка с сайта"
        text = "Новая заявка Kamilya LMS\n\n" + "\n".join(f"{label}: {value}" for label, value in rows)
        html_rows = "".join(
            "<tr>"
            f'<th style="text-align:left;vertical-align:top;padding:6px 12px 6px 0">{escape(label)}</th>'
            f'<td style="padding:6px 0;white-space:pre-wrap">{escape(value)}</td>'
            "</tr>"
            for label, value in rows
        )
        html = "<h2>Новая заявка Kamilya LMS</h2>" '<table style="border-collapse:collapse">' f"{html_rows}" "</table>"
        return await self._send(
            to_email=to_email,
            subject=subject,
            text=text,
            html=html,
            idempotency_key=(
                f"public-lead-notification/{notification.lead_id}/{recipient_key}"
            ),
        )

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

    async def send_course_review_invitation(
        self,
        *,
        to_email: str,
        reviewer_name: str | None,
        course_title: str,
        access_url: str,
        pin: str,
        idempotency_key: str,
    ) -> str | None:
        """Send a reviewer link and PIN without logging either secret."""
        name = reviewer_name or "Коллега"
        subject = f"Kamilya LMS: проверка курса «{_subject_component(course_title, fallback='Курс')}»"
        text = (
            f"{name}, вам назначена проверка курса «{course_title}».\n\n"
            f"Откройте ссылку: {access_url}\n"
            f"PIN-код: {pin}\n\n"
            "Ссылка и PIN действуют ограниченное время и не должны пересылаться другим людям."
        )
        html = (
            f"<p>{escape(name)}, вам назначена проверка курса <strong>{escape(course_title)}</strong>.</p>"
            f'<p><a href="{escape(access_url, quote=True)}">Открыть проверку курса</a></p>'
            f'<p>PIN-код: <strong>{escape(pin)}</strong></p>'
            "<p>Ссылка и PIN действуют ограниченное время и не должны пересылаться другим людям.</p>"
        )
        return await self._send(
            to_email=to_email,
            subject=subject,
            text=text,
            html=html,
            idempotency_key=idempotency_key,
        )

    async def send_course_review_reminder(
        self,
        *,
        to_email: str,
        reviewer_name: str | None,
        course_title: str,
        access_url: str,
        due_at: datetime | None,
        idempotency_key: str,
    ) -> str | None:
        """Send a PIN-free reminder for an existing course-review access link."""
        name = reviewer_name or "Коллега"
        subject = f"Kamilya LMS: напоминание о проверке курса «{_subject_component(course_title, fallback='Курс')}»"
        deadline = due_at.isoformat() if due_at is not None else "не указан"
        text = (
            f"{name}, это напоминание о проверке курса «{course_title}».\n\n"
            f"Открыть проверку: {access_url}\n"
            f"Срок: {deadline}\n"
            "Используйте ранее выданный доступ."
        )
        html = (
            f"<p>{escape(name)}, напоминаем о проверке курса <strong>{escape(course_title)}</strong>.</p>"
            f'<p><a href="{escape(access_url, quote=True)}">Открыть проверку курса</a></p>'
            f"<p>Срок: {escape(deadline)}</p>"
        )
        return await self._send(to_email=to_email, subject=subject, text=text, html=html, idempotency_key=idempotency_key)

    async def send_course_review_escalation(
        self,
        *,
        to_email: str,
        requester_name: str | None,
        course_title: str,
        action_url: str,
        due_at: datetime | None,
        idempotency_key: str,
    ) -> str | None:
        """Notify the requester about an overdue review without forwarding credentials."""
        name = requester_name or "Коллега"
        subject = f"Kamilya LMS: проверка курса просрочена «{_subject_component(course_title, fallback='Курс')}»"
        deadline = due_at.isoformat() if due_at is not None else "не указан"
        text = (
            f"{name}, проверка курса «{course_title}» просрочена.\n\n"
            f"Открыть запрос: {action_url}\n"
            f"Срок был: {deadline}"
        )
        html = (
            f"<p>{escape(name)}, проверка курса <strong>{escape(course_title)}</strong> просрочена.</p>"
            f'<p><a href="{escape(action_url, quote=True)}">Открыть запрос</a></p>'
            f"<p>Срок был: {escape(deadline)}</p>"
        )
        return await self._send(to_email=to_email, subject=subject, text=text, html=html, idempotency_key=idempotency_key)

    async def send_learning_path_assignment(
        self,
        *,
        to_email: str,
        company_name: str,
        learner_name: str,
        path_title: str,
        access_url: str,
        program_url: str,
        activation_required: bool,
        idempotency_key: str,
    ) -> str | None:
        subject = f"{_subject_component(company_name, fallback='Kamilya LMS')}: назначена программа"
        if activation_required:
            action = "Активируйте доступ к программе"
            route_note = f"После активации программа доступна здесь: {program_url}"
        else:
            action = "Откройте назначенную программу"
            route_note = f"Страница программы: {program_url}"
        text = (
            f"{learner_name}, {company_name} назначила вам программу «{path_title}».\n\n"
            f"{action}: {access_url}\n\n{route_note}"
        )
        html = (
            f"<p>{escape(learner_name)}, организация <strong>{escape(company_name)}</strong> "
            f"назначила вам программу <strong>{escape(path_title)}</strong>.</p>"
            f'<p><a href="{escape(access_url, quote=True)}">{action}</a></p>'
            f'<p><a href="{escape(program_url, quote=True)}">Открыть раздел программ</a></p>'
        )
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

    async def send_support_request(
        self,
        *,
        to_email: str,
        reply_to: str | None,
        reference: str,
        tenant_name: str,
        requester_name: str,
        requester_email: str | None,
        requester_role: str,
        category: str,
        subject: str,
        message: str,
        current_path: str | None,
    ) -> str | None:
        safe_subject = _subject_component(subject, fallback="Support request")
        email_subject = f"{reference}: {safe_subject}"
        rows = (
            ("Reference", reference),
            ("Tenant", tenant_name),
            ("Requester", requester_name),
            ("Email", requester_email or "Not available"),
            ("Role", requester_role),
            ("Category", category),
            ("Page", current_path or "Not available"),
        )
        text = "Kamilya LMS support request\n\n" + "\n".join(f"{label}: {value}" for label, value in rows)
        text += f"\n\nSubject: {subject}\n\nMessage:\n{message}"
        html_rows = "".join(
            "<tr>"
            f'<th style="text-align:left;vertical-align:top;padding:5px 12px 5px 0">{escape(label)}</th>'
            f'<td style="padding:5px 0">{escape(value)}</td>'
            "</tr>"
            for label, value in rows
        )
        html = (
            "<h2>Kamilya LMS support request</h2>"
            f'<table style="border-collapse:collapse">{html_rows}</table>'
            f"<h3>{escape(subject)}</h3>"
            f'<div style="white-space:pre-wrap">{escape(message)}</div>'
        )
        return await self._send(
            to_email=to_email,
            subject=email_subject,
            text=text,
            html=html,
            idempotency_key=f"support-request/{reference}",
            reply_to=reply_to,
        )

    async def _send(
        self,
        *,
        to_email: str,
        subject: str,
        text: str,
        html: str,
        idempotency_key: str | None = None,
        reply_to: str | None = None,
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
                reply_to=reply_to,
            )

        if provider == "smtp" and self.delivery_ready():
            await self._send_smtp(
                to_email=to_email,
                subject=subject,
                text=text,
                html=html,
                reply_to=reply_to,
            )
            return None

        logger.info("email_queued", extra={"provider": "log"})
        return None

    async def _send_smtp(
        self,
        *,
        to_email: str,
        subject: str,
        text: str,
        html: str,
        reply_to: str | None = None,
    ) -> None:
        """Deliver through the configured authenticated SMTP transport."""

        settings = get_settings()
        message = EmailMessage()
        message["From"] = formataddr(("Kamilya LMS", settings.EMAIL))
        message["To"] = to_email
        message["Subject"] = subject
        if reply_to:
            message["Reply-To"] = reply_to
        message.set_content(text)
        message.add_alternative(html, subtype="html")

        def deliver() -> None:
            context = ssl.create_default_context()

            def send(client: smtplib.SMTP) -> None:
                client.login(settings.EMAIL, settings.EMAIL_PASSWORD)
                refused = client.send_message(message)
                if refused:
                    raise smtplib.SMTPRecipientsRefused(refused)

            if settings.SMTP_USE_SSL:
                with smtplib.SMTP_SSL(
                    settings.SMTP_HOST,
                    settings.SMTP_PORT,
                    timeout=10,
                    context=context,
                ) as ssl_client:
                    send(ssl_client)
            else:
                with smtplib.SMTP(
                    settings.SMTP_HOST,
                    settings.SMTP_PORT,
                    timeout=10,
                ) as plain_client:
                    plain_client.starttls(context=context)
                    send(plain_client)

        try:
            await asyncio.to_thread(deliver)
        except smtplib.SMTPAuthenticationError as exc:
            raise EmailDeliveryError(
                "provider_auth_failed",
                "The email provider rejected authentication.",
            ) from exc
        except (TimeoutError, smtplib.SMTPServerDisconnected) as exc:
            raise EmailDeliveryError(
                "provider_timeout",
                "The email provider did not respond in time.",
            ) from exc
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError) as exc:
            raise EmailDeliveryError(
                "provider_rejected",
                "The email provider rejected the message.",
            ) from exc
        except (OSError, smtplib.SMTPException) as exc:
            raise EmailDeliveryError(
                "provider_unreachable",
                "The email provider could not be reached.",
            ) from exc

    async def _send_resend(
        self,
        *,
        to_email: str,
        subject: str,
        text: str,
        html: str,
        idempotency_key: str | None = None,
        reply_to: str | None = None,
    ) -> str | None:
        settings = get_settings()
        payload = {
            "from": settings.EMAIL_FROM,
            "to": [to_email],
            "subject": subject,
            "text": text,
            "html": html,
        }
        if reply_to:
            payload["reply_to"] = reply_to
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
