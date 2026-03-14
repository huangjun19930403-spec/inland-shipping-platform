"""
LLM客户端封装
统一管理Anthropic API调用，提供重试、错误处理、成本追踪能力
"""
import json
import logging
from typing import Any, Optional

import anthropic
from anthropic import AsyncAnthropic

from app.core.config import settings
from app.core.exceptions import AIServiceError

logger = logging.getLogger(__name__)

_client: Optional[AsyncAnthropic] = None


def get_client() -> AsyncAnthropic:
    """获取单例Anthropic客户端"""
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


async def chat_completion(
    system_prompt: str,
    user_message: str,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 2048,
    temperature: float = 0.1,
    response_format: str = "json",
) -> str:
    """
    基础文本对话补全

    Args:
        system_prompt: 系统提示词
        user_message: 用户消息
        model: 模型ID
        max_tokens: 最大输出Token数
        temperature: 温度 (0=确定性, 1=创造性)
        response_format: "json" 或 "text"

    Returns:
        LLM输出的文本内容

    Raises:
        AIServiceError: API调用失败时
    """
    client = get_client()

    system = system_prompt
    if response_format == "json":
        system = system_prompt + "\n\n必须以合法JSON格式输出，不要包含任何markdown代码块或额外文字。"

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        content = response.content[0].text
        logger.debug(
            f"[LLM] model={model} input_tokens={response.usage.input_tokens} "
            f"output_tokens={response.usage.output_tokens}"
        )
        return content

    except anthropic.APIConnectionError as e:
        logger.error(f"[LLM] Connection error: {e}")
        raise AIServiceError("AI service connection failed") from e

    except anthropic.RateLimitError as e:
        logger.warning(f"[LLM] Rate limit hit: {e}")
        raise AIServiceError("AI service rate limit exceeded") from e

    except anthropic.APIStatusError as e:
        logger.error(f"[LLM] API error status={e.status_code}: {e.message}")
        raise AIServiceError(f"AI API error: {e.message}") from e


async def json_completion(
    system_prompt: str,
    user_message: str,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 2048,
) -> dict[str, Any]:
    """
    JSON结构化输出补全
    自动解析LLM输出为Python字典

    Raises:
        AIServiceError: API调用失败或JSON解析失败时
    """
    raw = await chat_completion(
        system_prompt=system_prompt,
        user_message=user_message,
        model=model,
        max_tokens=max_tokens,
        response_format="json",
    )

    # 清理可能的markdown包装
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"[LLM] JSON parse failed: {e}\nRaw: {raw[:500]}")
        raise AIServiceError(f"AI output is not valid JSON: {e}") from e
