"""Anthropic Claude Provider"""
import logging
import time
from typing import Optional

import anthropic
from anthropic import AsyncAnthropic

from app.ai.providers.base import AbstractLLMProvider, LLMCallResult
from app.core.exceptions import AIServiceError

logger = logging.getLogger(__name__)

# 单例客户端（进程内复用连接池）
_client: Optional[AsyncAnthropic] = None


def _get_client(api_key: str) -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=api_key)
    return _client


class AnthropicProvider(AbstractLLMProvider):
    """Anthropic Claude Provider（支持 claude-sonnet-4-6 等所有 Claude 模型）"""

    provider_name = "anthropic"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: str,
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ) -> LLMCallResult:
        client = _get_client(self._api_key)
        start = time.monotonic()
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
        except anthropic.APIConnectionError as e:
            raise AIServiceError("AI service connection failed") from e
        except anthropic.RateLimitError as e:
            raise AIServiceError("AI service rate limit exceeded") from e
        except anthropic.APIStatusError as e:
            raise AIServiceError(f"AI API error: {e.message}") from e

        latency = int((time.monotonic() - start) * 1000)
        logger.debug(
            "[Anthropic] model=%s input=%d output=%d latency=%dms",
            model,
            response.usage.input_tokens,
            response.usage.output_tokens,
            latency,
        )
        return LLMCallResult(
            content=response.content[0].text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=model,
            provider=self.provider_name,
            latency_ms=latency,
        )
