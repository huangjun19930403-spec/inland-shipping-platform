"""LLM Provider 注册中心

统一入口：根据配置动态创建 Provider 单例，提供 json_completion 高层调用。
调用方只需关心业务逻辑，无需了解底层 Provider 细节。
"""
import json
import logging
from typing import Any, Optional

from app.ai.providers.base import AbstractLLMProvider, LLMCallResult
from app.core.exceptions import AIServiceError

logger = logging.getLogger(__name__)

# 单例缓存：provider_name → provider 实例
_registry: dict[str, AbstractLLMProvider] = {}


def get_provider(provider_name: Optional[str] = None) -> AbstractLLMProvider:
    """获取或创建 Provider 实例（进程内单例）

    Args:
        provider_name: 指定 Provider 名称，None 则使用 settings.AI_PROVIDER
    """
    from app.core.config import settings

    name = provider_name or settings.AI_PROVIDER
    if name not in _registry:
        _registry[name] = _build_provider(name)
    return _registry[name]


def _build_provider(name: str) -> AbstractLLMProvider:
    from app.core.config import settings

    if name == "anthropic":
        if not settings.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY 未配置，无法使用 Anthropic Provider")
        from app.ai.providers.anthropic import AnthropicProvider
        return AnthropicProvider(api_key=settings.ANTHROPIC_API_KEY)

    elif name == "openai":
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY 未配置，无法使用 OpenAI Provider")
        from app.ai.providers.openai import OpenAIProvider
        return OpenAIProvider(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL or None,
        )

    elif name == "deepseek":
        if not settings.DEEPSEEK_API_KEY:
            raise RuntimeError("DEEPSEEK_API_KEY 未配置，无法使用 DeepSeek Provider")
        from app.ai.providers.openai import DeepSeekProvider
        return DeepSeekProvider(api_key=settings.DEEPSEEK_API_KEY)

    elif name == "tongyi":
        if not settings.DASHSCOPE_API_KEY:
            raise RuntimeError("DASHSCOPE_API_KEY 未配置，无法使用通义千问 Provider")
        from app.ai.providers.tongyi import TongyiProvider
        return TongyiProvider(api_key=settings.DASHSCOPE_API_KEY)

    else:
        raise ValueError(
            f"未知的 AI Provider: '{name}'。"
            f"支持: anthropic, openai, deepseek, tongyi"
        )


async def json_completion(
    system_prompt: str,
    user_message: str,
    provider_name: Optional[str] = None,
) -> tuple[dict[str, Any], LLMCallResult]:
    """JSON 结构化补全（统一高层入口）

    自动向 system_prompt 追加 JSON 输出指令，清洗并解析 LLM 输出。

    Args:
        system_prompt:  业务 system prompt（不含 JSON 指令，此函数自动追加）
        user_message:   用户消息
        provider_name:  指定 Provider，None 则使用默认配置

    Returns:
        (parsed_dict, LLMCallResult) — 调用方从 LLMCallResult 取 token / latency 等信息

    Raises:
        AIServiceError: API 调用失败或输出不是合法 JSON
    """
    from app.core.config import settings

    provider = get_provider(provider_name)
    full_system = (
        system_prompt
        + "\n\n必须以合法JSON格式输出，不要包含任何markdown代码块或额外文字。"
    )

    call_result = await provider.complete(
        system_prompt=full_system,
        user_message=user_message,
        model=settings.AI_MODEL,
        max_tokens=settings.AI_MAX_TOKENS,
        temperature=settings.AI_TEMPERATURE,
    )

    # 清洗 markdown 包装（部分模型会加 ```json ... ```）
    raw = call_result.content.strip()
    cleaned = raw
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(
            "[LLM] JSON parse failed provider=%s model=%s: %s\nRaw(500): %s",
            call_result.provider,
            call_result.model,
            e,
            raw[:500],
        )
        raise AIServiceError(f"AI 输出不是合法 JSON: {e}") from e

    return parsed, call_result
