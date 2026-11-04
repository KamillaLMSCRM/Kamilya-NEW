"""Explicit fresh-course QA profile for the owner-operated ASUS through a DEV bridge."""
from __future__ import annotations

from typing import Any

from app.modules.ai.llm_client import LLMProviderConfig, ResilientLLMClient
from app.modules.ai.qa_luna_dev_route import QA_TENANT
from app.modules.ai.v3.revision_policy import MATERIALITY_PRACTICAL_REVIEW_POLICY

PROVIDER = 'deepseek-local-asus'
MODEL = 'DeepSeek-V4.1-Flash-1017'
BASE_URL = 'http://127.0.0.1:18890/v1'
GENERATION_SECONDS = 300.0
THINKING_BUDGET = 4096
MAX_TOKENS = 16384
LUNA_FLAGS = ('AI_QA_LUNA_DEV_ENABLED', 'AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED',
              'AI_DIRECT_LUNA_QA_DEV_ENABLED', 'AI_MANAGED_LUNA_QA_DEV_ENABLED')


def configuration() -> LLMProviderConfig:
    # The loopback belongs to the pinned DEV container's temporary SSH stream.
    # No commercial API credential is copied to the unauthenticated local model.
    return LLMProviderConfig(PROVIDER, BASE_URL, '', MODEL, timeout=GENERATION_SECONDS,
        connect_timeout=8.0, max_retries=0, trust_env=False, structured_output_mode='prompt_json',
        extra_body={'reasoning_effort':'low', 'chat_template_kwargs':{'enable_thinking':True},
                    'thinking_budget':THINKING_BUDGET})


def create_local_deepseek_dev_client(*, settings: Any, tenant_id: Any, course_id: Any,
                                    review_policy: Any, temperature: float) -> ResilientLLMClient | None:
    if getattr(settings, 'AI_QA_LOCAL_DEEPSEEK_DEV_ENABLED', False) is not True:
        return None
    if getattr(settings, 'DEPLOYMENT_ENVIRONMENT', None) not in {'render-development','vm-development-worker'}:
        raise ValueError('local_deepseek_dev_environment_invalid')
    if str(tenant_id) != str(QA_TENANT) or course_id is not None or review_policy != MATERIALITY_PRACTICAL_REVIEW_POLICY:
        return None
    if any(getattr(settings, name, None) is not False for name in LUNA_FLAGS):
        raise ValueError('local_deepseek_dev_route_conflict')
    return ResilientLLMClient([configuration()],temperature=temperature,max_tokens=MAX_TOKENS,
                              max_retries_per_provider=0)


def is_local_deepseek_dev_client(client: Any) -> bool:
    return (type(client) is ResilientLLMClient and client.provider_names == [PROVIDER]
            and len(client._clients) == 1 and client._clients[0].config == configuration()
            and client.max_tokens == MAX_TOKENS)
