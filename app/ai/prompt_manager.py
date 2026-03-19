"""DB 化提示词管理

替代原来的硬编码 PROMPT_REGISTRY。
使用 5 分钟 TTL 内存缓存，正常运行不会每次请求打 DB。
管理 API 修改提示词后调用 invalidate_cache(name) 使缓存立即失效。
"""
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# 模块级 TTL 缓存：template_name → (PromptTemplate.__dict__, cached_at)
_cache: dict[str, tuple[dict, float]] = {}
_CACHE_TTL = 300  # 5 分钟


@dataclass
class PromptTemplate:
    id: int
    name: str
    system_prompt: str
    user_template: str
    version: int

    def format_user(self, **kwargs: Any) -> str:
        """将 user_template 中的 {变量名} 替换为实际值。

        使用简单字符串替换而非 str.format()，避免模板中的 JSON 花括号被误解析。
        """
        result = self.user_template
        for key, value in kwargs.items():
            result = result.replace("{" + key + "}", str(value))
        return result


async def get_template(name: str, db: AsyncSession) -> PromptTemplate:
    """获取指定名称的激活版本提示词模板。

    优先读内存缓存，缓存过期后从 DB 加载激活版本。

    Raises:
        KeyError: 未找到模板或激活版本不存在
    """
    now = time.monotonic()
    if name in _cache:
        data, cached_at = _cache[name]
        if now - cached_at < _CACHE_TTL:
            return PromptTemplate(**data)

    from sqlalchemy import select
    from app.models.ai import AiPromptTemplate, AiPromptVersion

    tmpl_result = await db.execute(
        select(AiPromptTemplate).where(
            AiPromptTemplate.name == name,
            AiPromptTemplate.is_active.is_(True),
        )
    )
    tmpl = tmpl_result.scalar_one_or_none()
    if not tmpl:
        raise KeyError(f"未找到激活的提示词模板: '{name}'")

    ver_result = await db.execute(
        select(AiPromptVersion).where(
            AiPromptVersion.template_id == tmpl.id,
            AiPromptVersion.version == tmpl.active_version,
        )
    )
    ver = ver_result.scalar_one_or_none()
    if not ver:
        raise KeyError(
            f"提示词模板 '{name}' 的激活版本 {tmpl.active_version} 不存在"
        )

    data = {
        "id": tmpl.id,
        "name": tmpl.name,
        "system_prompt": ver.system_prompt,
        "user_template": ver.user_template,
        "version": ver.version,
    }
    _cache[name] = (data, now)
    logger.debug("[PromptManager] loaded template='%s' version=%d", name, ver.version)
    return PromptTemplate(**data)


def invalidate_cache(name: Optional[str] = None) -> None:
    """使提示词缓存失效。

    Args:
        name: 指定模板名称；None 则清除所有缓存（慎用）
    """
    if name is None:
        _cache.clear()
        logger.info("[PromptManager] all prompt cache cleared")
    else:
        _cache.pop(name, None)
        logger.info("[PromptManager] prompt cache cleared: '%s'", name)
