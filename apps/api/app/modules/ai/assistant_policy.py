"""Fail-closed public response policy for the tenant course assistant."""

from __future__ import annotations

import re
from typing import Literal

from app.core.log_redaction import redact_sensitive_text

AssistantLanguage = Literal["ru", "kk", "en"]

MAX_ASSISTANT_REPLY_CHARS = 12_000

_SCOPE_REFUSALS: dict[str, str] = {
    "ru": "Я помогаю только с учебными материалами текущей организации и не раскрываю внутренние настройки или защищённые данные.",
    "kk": "Мен тек ағымдағы ұйымның оқу материалдары бойынша көмектесемін және ішкі баптауларды немесе қорғалған деректерді ашпаймын.",
    "en": "I only help with the current organization's learning materials and do not disclose internal settings or protected data.",
}

_REQUEST_DENY_PATTERNS = (
    re.compile(r"(?i)\b(?:system|developer)\s+(?:prompt|message|instructions?)\b"),
    re.compile(r"(?i)\b(?:ignore|disregard|override)\b.{0,40}\b(?:previous|prior|system|developer)\b"),
    re.compile(
        r"(?i)\b(?:show|reveal|print|return|give|list|dump|expose|tell me)\b.{0,50}"
        r"\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|credential|secret|\.env)\b"
    ),
    re.compile(
        r"(?i)\b(?:which|what)\s+(?:llm|ai|language)?\s*(?:model|provider|engine)\b.{0,50}"
        r"\b(?:do you use|are you using|is used|powers you|serves you)\b"
    ),
    re.compile(
        r"(?i)\b(?:model|provider|endpoint|base[_ -]?url)\b.{0,35}"
        r"\b(?:do you use|are you using|is used|powers you|are you running)\b"
    ),
    re.compile(r"(?i)\b(?:other|another)\s+(?:tenant|organization|company)\b.{0,50}\b(?:data|document|course|user|employee)\b"),
    re.compile(r"(?i)\b(?:data|documents?|courses?|users?|employees?)\b.{0,50}\bfrom\s+(?:an?\s+)?(?:other|another)\s+(?:tenant|organization|company)\b"),
    re.compile(
        r"(?i)\b(?:какая|какой)\b.{0,20}\b(?:модель|провайдер|движок|эндпоинт|endpoint)\b.{0,40}"
        r"\b(?:используется|подключен|обслуживает|у ассистента|в чате|у тебя|ты используешь)\b"
    ),
    re.compile(
        r"(?i)\b(?:назови|покажи|раскрой|выведи|дай)\b.{0,45}"
        r"\b(?:модель ассистента|ai[- ]?провайдер|llm[- ]?провайдер|эндпоинт|endpoint|api[- _]?key|\.env|ключ|токен|пароль|секрет)\b"
    ),
    re.compile(r"(?i)\b(?:системн(?:ый|ого)\s+промпт|внутренн(?:ие|их)\s+инструкци|переменн(?:ые|ых)\s+окружения)\b"),
    re.compile(r"(?i)\b(?:игнорируй|отмени|обойди)\b.{0,45}\b(?:предыдущ|системн|инструкци|ограничени)\b"),
    re.compile(r"(?i)\b(?:другого|чужого|иной)\b.{0,30}\b(?:тенанта|организации|компании)\b.{0,50}\b(?:данн|документ|курс|сотрудник)\b"),
    re.compile(
        r"(?i)\b(?:қандай|қай)\b.{0,30}\b(?:модель|провайдер|қозғалтқыш)\b.{0,40}"
        r"\b(?:қолданылады|пайдаланасың|қосылған)\b"
    ),
    re.compile(r"(?i)\b(?:жүйелік\s+промпт|ішкі\s+нұсқаулар|құпия\s+деректер)\b"),
)

_OUTPUT_DENY_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,})\b"),
    re.compile(r"(?i)\b(?:sk|rk)-[a-z0-9_-]{16,}\b"),
    re.compile(r"(?i)\b(?:postgres(?:ql)?|redis|rediss|mongodb(?:\+srv)?)://"),
    re.compile(
        r"(?i)\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|secret|ключ|токен|пароль)\b"
        r"\s+(?:is|равен|это|:)\s*\S+"
    ),
    re.compile(r"(?i)\b(?:system|developer)\s+(?:prompt|message|instructions?)\b"),
    re.compile(r"(?i)\b(?:системн(?:ый|ого)\s+промпт|внутренн(?:ие|их)\s+инструкци)\b"),
    re.compile(r"(?i)\b(?:жүйелік\s+промпт|ішкі\s+нұсқаулар)\b"),
    re.compile(
        r"(?i)\b(?:my|our|internal|runtime)\s+(?:provider|model|endpoint|base[_ -]?url)\s*[:=—-]\s*\S+"
    ),
    re.compile(
        r"(?i)\b(?:мой|наша|используемая|внутренняя)\s+(?:провайдер|модель|эндпоинт)\s*[:=—-]?\s*\S+"
    ),
    re.compile(
        r"(?i)\b(?:powered by|i am running on|i use|this assistant uses)\b.{0,60}"
        r"\b(?:DeepSeek|OpenAI|Anthropic|Claude|Qwen|GLM[-\w.]*|GPT[-\w.]*|model|provider|engine)\b"
    ),
    re.compile(
        r"(?i)\b(?:я работаю на|меня обслуживает|ассистент использует|чат использует)\b.{0,60}"
        r"\b(?:DeepSeek|OpenAI|Anthropic|Claude|Qwen|GLM[-\w.]*|GPT[-\w.]*|модель|провайдер)\b"
    ),
    re.compile(
        r"(?i)\b(?:provider|провайдер)\s*[:=—-]\s*"
        r"(?:DeepSeek|OpenAI|Anthropic|Qwen|Cohere)\b.{0,80}"
        r"\b(?:model|модель)\s*[:=—-]"
    ),
    re.compile(
        r"(?i)^\s*(?:model|модель|provider|провайдер)\s*[:=—-]\s*"
        r"(?:DeepSeek|OpenAI|Anthropic|Claude|Qwen|Cohere|GLM[-\w.]*|GPT[-\w.]*)\b"
    ),
    re.compile(r"(?i)^\s*(?:endpoint|base[_ -]?url|эндпоинт)\s*[:=—-]\s*https?://"),
    re.compile(
        r"(?i)^\s*(?:DeepSeek|OpenAI|Anthropic|Claude|Qwen|Cohere|GLM[-\w.]*|GPT[-\w.]*)"
        r"(?:\s+[A-Za-z0-9._-]+)?\s*[.!]?\s*$"
    ),
)


def assistant_scope_refusal(language: AssistantLanguage | str) -> str:
    """Return one stable, non-reflecting refusal in the requested UI language."""

    return _SCOPE_REFUSALS.get(language, _SCOPE_REFUSALS["ru"])


def assistant_request_refusal(
    message: str,
    language: AssistantLanguage | str,
) -> str | None:
    """Reject explicit attempts to inspect internals, secrets, or another tenant."""

    normalized = " ".join(message.split())
    if any(pattern.search(normalized) for pattern in _REQUEST_DENY_PATTERNS):
        return assistant_scope_refusal(language)
    return None


def assistant_reply_is_safe(reply: str) -> bool:
    """Accept only bounded replies with no common secret, PII, or AI-internal disclosure."""

    text = reply.strip()
    if not text or len(text) > MAX_ASSISTANT_REPLY_CHARS:
        return False
    if redact_sensitive_text(text) != text:
        return False
    return not any(pattern.search(text) for pattern in _OUTPUT_DENY_PATTERNS)


__all__ = [
    "MAX_ASSISTANT_REPLY_CHARS",
    "assistant_reply_is_safe",
    "assistant_request_refusal",
    "assistant_scope_refusal",
]
