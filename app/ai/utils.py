"""AI 相关通用工具函数。"""
import json
from typing import Any


def normalize_corrected_fields(value: Any) -> list[str]:
    """兼容 corrected_fields 在历史数据中的不同存储格式。"""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [str(v) for v in parsed]
        return []
    return []

