"""通义千问 Provider（阿里云 DashScope SDK）

需要安装：pip install dashscope>=1.14.0
DashScope SDK 为同步接口，使用 asyncio.to_thread 包装为异步。
"""
import asyncio
import logging
import time
from http import HTTPStatus

from app.ai.providers.base import AbstractLLMProvider, LLMCallResult
from app.core.exceptions import AIServiceError

logger = logging.getLogger(__name__)


class TongyiProvider(AbstractLLMProvider):
    """通义千问 Provider（qwen-turbo、qwen-plus、qwen-max 等）"""

    provider_name = "tongyi"

    def __init__(self, api_key: str) -> None:
        try:
            import dashscope
            self._dashscope = dashscope
        except ImportError:
            raise RuntimeError(
                "dashscope 包未安装，使用通义千问 Provider 请执行: pip install dashscope>=1.14.0"
            )
        self._api_key = api_key

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: str,
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ) -> LLMCallResult:
        self._dashscope.api_key = self._api_key
        start = time.monotonic()
        try:
            # DashScope SDK 是同步调用，放入线程池避免阻塞事件循环
            response = await asyncio.to_thread(
                self._dashscope.Generation.call,
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
                result_format="message",
            )
        except Exception as e:
            raise AIServiceError(f"DashScope call error: {e}") from e

        if response.status_code != HTTPStatus.OK:
            raise AIServiceError(
                f"DashScope error {response.status_code}: {response.message}"
            )

        latency = int((time.monotonic() - start) * 1000)
        usage = response.usage
        logger.debug(
            "[Tongyi] model=%s input=%d output=%d latency=%dms",
            model,
            usage.input_tokens,
            usage.output_tokens,
            latency,
        )
        return LLMCallResult(
            content=response.output.choices[0].message.content,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            model=model,
            provider=self.provider_name,
            latency_ms=latency,
        )
