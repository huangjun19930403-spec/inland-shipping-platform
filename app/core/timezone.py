"""Timezone helpers for business-facing timestamps."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

APP_TIMEZONE = ZoneInfo("Asia/Shanghai")


def now_shanghai_naive() -> datetime:
    """Return current Asia/Shanghai wall-clock time for business-facing calculations."""
    return datetime.now(APP_TIMEZONE).replace(tzinfo=None)


def to_shanghai_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(APP_TIMEZONE).replace(tzinfo=None)


def utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
