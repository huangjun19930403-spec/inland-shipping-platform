"""Shared display conversion helpers for vessel modules."""

from __future__ import annotations

from typing import Any


def data_source_codes(values: list[Any] | None) -> list[str]:
    result: list[str] = []
    for value in values or []:
        code: str | None = None
        if isinstance(value, str):
            code = value
        elif isinstance(value, dict):
            code = next(
                (str(value[key]) for key in ("source_layer", "source_index", "snapshot_id", "ais_snapshot_id", "route_snapshot_id") if value.get(key)),
                None,
            )
        elif value:
            code = str(value)
        if code and code not in result:
            result.append(code)
    return result
