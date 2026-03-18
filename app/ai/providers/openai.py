"""OpenAI / DeepSeek Provider

两者使用完全相同的 OpenAI 协议，DeepSeek 只需替换 base_url。
需要安装：pip install openai>=1.0.0
"""
import logging
import time
from typing import Optional

from app.ai.providers.base import AbstractLLMProvider, LLMCallResult
from app.core.exceptions import AIServiceError

logger = logging.getLogger(__name__)


class OpenAIProvider(AbstractLLMProvider):
    """OpenAI ChatGPT Provider（gpt-4o、gpt-4-turbo 等）"""

    provider_name = "openai"

    def __init__(self, api_key: str, base_url: Optional[str] = None) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise RuntimeError(
                "openai 包未安装，使用 OpenAI/DeepSeek Provider 请执行: pip install openai>=1.0.0"
            )
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: str,
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ) -> LLMCallResult:
        start = time.monotonic()
        try:
            response = await self._client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
            )
        except Exception as e:
            raise AIServiceError(f"OpenAI API error: {e}") from e

        latency = int((time.monotonic() - start) * 1000)
        usage = response.usage
        logger.debug(
            "[OpenAI] model=%s input=%d output=%d latency=%dms",
            model,
            usage.prompt_tokens,
            usage.completion_tokens,
            latency,
        )
        return LLMCallResult(
            content=response.choices[0].message.content,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            model=model,
            provider=self.provider_name,
            latency_ms=latency,
        )


class DeepSeekProvider(OpenAIProvider):
    """DeepSeek Provider（使用 OpenAI 兼容协议，base_url 指向 DeepSeek API）"""

    provider_name = "deepseek"

    def __init__(self, api_key: str) -> None:
        super().__init__(api_key=api_key, base_url="https://api.deepseek.com")
