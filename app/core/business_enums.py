"""业务枚举过渡承载。

说明：
1. 本文件仅用于存放少量过渡期代码枚举/校验工具。
2. 凡可穷举且应业务化维护的正式枚举，后续均应迁移至
   std_dict / std_dict_item + seed 体系。
3. 新模块禁止继续扩大本文件职责。
"""

from __future__ import annotations

from typing import Iterable


def ensure_enum_values(values: Iterable[str], allowed: set[str], field: str) -> list[str]:
    """通用枚举值校验与去重。"""
    normalized: list[str] = []
    for item in values:
        value = (item or "").strip().upper()
        if not value:
            continue
        if value not in allowed:
            raise ValueError(f"{field} 包含不支持的枚举值: {item}")
        if value not in normalized:
            normalized.append(value)
    return normalized

