"""Shared imports and helpers for vessel AIS services."""

from __future__ import annotations

import math
import inspect

from app.modules.vessel.shared import base as _base
from app.integrations.config_keys import ES_TIMEOUT_SECONDS

globals().update({name: getattr(_base, name) for name in dir(_base) if not name.startswith("__")})


def _public_ais_error_message(error: Any) -> str | None:
    if error in (None, ""):
        return None
    text = str(error)
    lowered = text.lower()
    technical_markers = [
        "parse_exception",
        "failed to parse",
        "status=",
        "body=",
        "realtime es 请求失败",
        "traceback",
        "exception",
    ]
    if any(marker in lowered for marker in technical_markers):
        return "部分实时 AIS 数据暂不可用，请稍后刷新或检查实时数据源配置"
    if len(text) > 120:
        return text[:117] + "..."
    return text




__all__ = [name for name in globals() if not name.startswith("__")]
