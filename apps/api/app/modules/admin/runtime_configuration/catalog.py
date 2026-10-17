"""Closed key catalog and pure validation shared by readers and writers."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, cast

from app.core.config import get_settings

Value = int | float | str


@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    kind: Literal["integer", "number", "model"]
    default: Value
    minimum: float | None = None
    maximum: float | None = None
    env: str | None = None
    choices: tuple[str, ...] = ()


CATALOG = (
    Setting("assignment.total_seconds", "Назначение: общий таймаут, с", "integer", 90, 45, 90),
    Setting("assignment.deepseek_seconds", "Назначение: попытка DeepSeek, с", "integer", 30, 5, 60),
    Setting("assignment.chatgpt_seconds", "Назначение: попытка ChatGPT, с", "integer", 40, 5, 40),
    Setting("assignment.fallback_seconds", "Назначение: попытка последнего резерва, с", "integer", 8, 2, 10),
    Setting("assignment.max_tokens", "Назначение: максимум токенов ответа", "integer", 1200, 256, 1200),
    Setting("document_intent.total_seconds", "Подготовка документа: общий таймаут, с", "integer", 30, 10, 90),
    Setting("document_intent.max_tokens", "Подготовка документа: максимум токенов", "integer", 1200, 256, 1200),
    Setting("document_dialogue.provider_seconds", "Диалог подготовки: попытка провайдера, с", "integer", 8, 2, 30),
    Setting("generation.temperature", "Генерация курса: температура", "number", 0.2, 0, 0.5),
    Setting("reviewer.timeout_seconds", "Проверка курса: таймаут модели, с", "integer", 45, 5, 60),
    Setting("document_answer.total_seconds", "Ответ по документам: общий таймаут, с", "integer", 60, 15, 90),
    Setting("document_answer.provider_seconds", "Ответ по документам: попытка провайдера, с", "integer", 8, 2, 30),
    Setting("document_answer.max_tokens", "Ответ по документам: максимум токенов", "integer", 2000, 512, 2000),
    Setting("evidence_low.deepseek_seconds", "Ответ DeepSeek по документам: попытка, с", "integer", 45, 5, 60),
    Setting("evidence_low.max_tokens", "Ответ DeepSeek по документам: токены с рассуждением", "integer", 8192, 4096, 8192),
    Setting("editor.temperature", "ИИ-правка теста: температура", "number", 0.2, 0, 0.5),
    Setting("editor.max_tokens", "ИИ-правка теста: максимум токенов", "integer", 4096, 512, 4096),
    Setting("writer.retrieval_count", "Поиск для урока: кандидаты на запрос", "integer", 15, 5, 15),
    Setting("writer.result_count", "Поиск для урока: итоговые фрагменты", "integer", 10, 3, 10),
    Setting("writer.similarity_threshold", "Поиск для урока: порог сходства", "number", 0.45, 0.3, 0.8),
    Setting("provider.deepseek.model", "DeepSeek: модель", "model", "deepseek-v4-flash", env="DEEPSEEK_MODEL"),
    Setting("provider.deepseek.timeout_seconds", "DeepSeek: транспортный таймаут, с", "integer", 120, 30, 180),
    Setting("provider.qwen.model", "Qwen: модель (не включает провайдер)", "model", "qwen3.8-flash-next", env="QWEN38_FLASH_MODEL"),
    Setting("provider.qwen.timeout_seconds", "Qwen: транспортный таймаут, с", "number", 600, 30, 600, env="FREE_LLM_REQUEST_TIMEOUT_SECONDS"),
    Setting("provider.glm.model", "GLM: модель (не включает провайдер)", "model", "LibertAIDAI/GLM-5.3-Flash-NVFP4", env="GLM53_FLASH_MODEL"),
    Setting("provider.glm.timeout_seconds", "GLM: транспортный таймаут, с", "number", 600, 30, 600, env="FREE_LLM_REQUEST_TIMEOUT_SECONDS"),
    Setting("provider.chatgpt.model", "ChatGPT: модель установленного коннектора", "model", "gpt-5.6-luna", env="CHATGPT_RESERVE_MODEL", choices=("gpt-5.6-luna",)),
    Setting("provider.chatgpt.timeout_seconds", "ChatGPT: транспортный таймаут, с", "number", 60, 40, 120, env="CHATGPT_RESERVE_TIMEOUT_SECONDS"),
    Setting("outbox.assignment.batch_size", "Уведомления назначений: пакет восстановления", "integer", 20, 1, 50),
    Setting("outbox.reminders.batch_size", "Напоминания: пакет восстановления", "integer", 20, 1, 50),
    Setting("outbox.crm.batch_size", "CRM: пакет восстановления", "integer", 20, 1, 50),
)
BY_KEY = MappingProxyType({item.key: item for item in CATALOG})
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-/]{0,159}\Z")


class InvalidSettings(ValueError):  # noqa: N818 - compact module-local policy error
    """Safe error codes only; never echo an untrusted configuration value."""


def validate_value(spec: Setting, value: Any) -> Value:
    if spec.kind == "model":
        if not isinstance(value, str) or not MODEL_ID.fullmatch(value) or ".." in value:
            raise InvalidSettings(f"runtime_settings_invalid_model:{spec.key}")
        if spec.choices and value not in spec.choices:
            raise InvalidSettings(f"runtime_settings_unsupported_model:{spec.key}")
        return value
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidSettings(f"runtime_settings_invalid_type:{spec.key}")
    if spec.kind == "integer" and not isinstance(value, int):
        raise InvalidSettings(f"runtime_settings_integer_required:{spec.key}")
    if not math.isfinite(value) or not spec.minimum <= value <= spec.maximum:
        raise InvalidSettings(f"runtime_settings_out_of_range:{spec.key}")
    return cast(int | float, value)


def effective_values(overrides: Mapping[str, Any], *, settings: Any = None) -> Mapping[str, Value]:
    if not isinstance(overrides, dict) or set(overrides) - BY_KEY.keys():
        raise InvalidSettings("runtime_settings_unknown_key")
    settings = settings or get_settings()
    values = {spec.key: validate_value(spec, overrides.get(spec.key,
        getattr(settings, spec.env) if spec.env else spec.default)) for spec in CATALOG}
    required = sum(float(values[f"assignment.{key}_seconds"]) for key in ("deepseek", "chatgpt", "fallback")) + 5
    if required > float(values["assignment.total_seconds"]):
        raise InvalidSettings("runtime_settings_assignment_deadline_budget")
    if float(values["document_dialogue.provider_seconds"]) > float(values["document_intent.total_seconds"]):
        raise InvalidSettings("runtime_settings_document_deadline_budget")
    if float(values["document_answer.provider_seconds"]) + 5 > float(values["document_answer.total_seconds"]):
        raise InvalidSettings("runtime_settings_answer_deadline_budget")
    if float(values["evidence_low.deepseek_seconds"]) + float(values["document_answer.provider_seconds"]) + 5 > float(values["document_answer.total_seconds"]):
        raise InvalidSettings("runtime_settings_evidence_deadline_budget")
    if int(values["writer.result_count"]) > int(values["writer.retrieval_count"]):
        raise InvalidSettings("runtime_settings_retrieval_count_budget")
    return MappingProxyType(values)


@dataclass(frozen=True)
class RuntimeSnapshot:
    revision: int
    values: Mapping[str, Value]

    def number(self, key: str) -> float:
        value = self.values[key]
        if isinstance(value, str):
            raise TypeError("runtime_setting_not_numeric")
        return float(value)

    def integer(self, key: str) -> int:
        value = self.values[key]
        if not isinstance(value, int):
            raise TypeError("runtime_setting_not_integer")
        return value

    def text(self, key: str) -> str:
        value = self.values[key]
        if not isinstance(value, str):
            raise TypeError("runtime_setting_not_text")
        return value


def default_snapshot() -> RuntimeSnapshot:
    return RuntimeSnapshot(0, effective_values({}))
