"""Registry for shared external integration sessions."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.database import AsyncSessionLocal
from app.integrations.hifleet.session_manager import HifleetSessionManager
from app.modules.system.runtime_config import RuntimeConfigService

logger = logging.getLogger(__name__)


class ExternalSessionRegistry:
    """Small internal registry for provider session lifecycle operations."""

    @staticmethod
    def _normalize(provider_code: str) -> str:
        return (provider_code or "").strip().lower()

    @classmethod
    async def _hifleet_manager(cls):
        db = AsyncSessionLocal()
        manager = HifleetSessionManager(runtime_config=RuntimeConfigService(db))
        return db, manager

    @classmethod
    async def ensure(cls, provider_code: str) -> None:
        provider = cls._normalize(provider_code)
        if provider not in {"hifleet", "amms"}:
            raise ValueError(f"unsupported external session provider: {provider_code}")
        db, manager = await cls._hifleet_manager()
        try:
            await manager.ensure_session()
        finally:
            await db.close()

    @classmethod
    async def warmup(cls, provider_code: str, *, timeout_seconds: float = 10.0) -> None:
        provider = cls._normalize(provider_code)
        if provider not in {"hifleet", "amms"}:
            raise ValueError(f"unsupported external session provider: {provider_code}")
        db, manager = await cls._hifleet_manager()
        try:
            await asyncio.wait_for(manager.warmup(), timeout=max(1.0, float(timeout_seconds)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("external session warmup failed provider=%s error=%s", provider_code, exc)
        finally:
            await db.close()

    @classmethod
    async def shutdown(cls, provider_code: str, *, timeout_seconds: float = 10.0) -> None:
        provider = cls._normalize(provider_code)
        if provider not in {"hifleet", "amms"}:
            raise ValueError(f"unsupported external session provider: {provider_code}")
        db, manager = await cls._hifleet_manager()
        try:
            await asyncio.wait_for(manager.shutdown(), timeout=max(1.0, float(timeout_seconds)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("external session shutdown failed provider=%s error=%s", provider_code, exc)
        finally:
            await db.close()

    @classmethod
    async def status(cls, provider_code: str) -> dict[str, Any]:
        provider = cls._normalize(provider_code)
        if provider not in {"hifleet", "amms"}:
            raise ValueError(f"unsupported external session provider: {provider_code}")
        db, manager = await cls._hifleet_manager()
        try:
            return await manager.status()
        finally:
            await db.close()
