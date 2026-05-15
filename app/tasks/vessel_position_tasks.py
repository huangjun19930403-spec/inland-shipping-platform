"""Celery vessel position task entrypoints."""

from __future__ import annotations

import asyncio
import logging
from threading import Thread
from typing import Any

from celery.signals import worker_ready

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.modules.vessel.schemas import (
    VesselPositionCitySituationQuery,
    VesselPositionCityVesselsQuery,
    VesselPositionNavigationChannelSituationQuery,
    VesselPositionNavigationChannelVesselsQuery,
)
from app.modules.vessel.service import VesselService
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_coro_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] | None = None
    error: BaseException | None = None

    def runner() -> None:
        nonlocal result, error
        try:
            result = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - defensive bridge for eager mode
            error = exc

    thread = Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if error is not None:
        raise error
    return result


async def _precompute_city_situation() -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        drilldown_limit = max(1, int(settings.VESSEL_SITUATION_PRECOMPUTE_DRILLDOWN_LIMIT or 100))
        drilldown_page_size = max(1, min(100, drilldown_limit))
        service = VesselService(db)
        query = VesselPositionCitySituationQuery(
            reported_within_minutes=1440,
            include_boundary=False,
            boundary_precision="low",
        )
        object.__setattr__(query, "force_refresh", True)
        response = await service.position_city_situation(query)
        drilldown_count = 0
        snapshot_id = response.summary.query_snapshot_id
        if snapshot_id:
            base_drilldown_query = query.model_dump()
            for city in response.cities:
                if city.positioned_count <= 0:
                    continue
                page = 1
                total = 0
                while page == 1 or (page - 1) * drilldown_page_size < min(total, drilldown_limit):
                    drilldown_query = VesselPositionCityVesselsQuery(
                        **base_drilldown_query,
                        city_code=city.city_code,
                        city_name=None if city.city_code else city.city_name,
                        query_snapshot_id=snapshot_id,
                        page=page,
                        page_size=drilldown_page_size,
                    )
                    drilldown_response = await service.position_city_vessels(drilldown_query)
                    total = int(getattr(drilldown_response, "total", 0) or 0)
                    drilldown_count += 1
                    if total <= page * drilldown_page_size:
                        break
                    page += 1
        return {
            "source_status": response.source_status,
            "generated_at": response.generated_at.isoformat(),
            "positioned_count": response.summary.positioned_count,
            "city_count": response.summary.city_count,
            "drilldown_count": drilldown_count,
            "is_partial": response.summary.is_partial,
            "snapshot_backend": response.snapshot_backend,
        }


async def _precompute_channel_situation() -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        drilldown_limit = max(1, int(settings.VESSEL_SITUATION_PRECOMPUTE_DRILLDOWN_LIMIT or 100))
        drilldown_page_size = max(1, min(100, drilldown_limit))
        service = VesselService(db)
        query = VesselPositionNavigationChannelSituationQuery(
            reported_within_minutes=1440,
            include_boundary=False,
            include_empty_channels=False,
            boundary_precision="low",
            planning_level_codes="NATIONAL_CORE,NATIONAL_NETWORK,NATIONAL_IMPORTANT,PROVINCIAL_HIGH_GRADE,REGIONAL_IMPORTANT,REVIEW",
        )
        object.__setattr__(query, "force_refresh", True)
        response = await service.position_channel_situation(query)
        drilldown_count = 0
        snapshot_id = response.summary.query_snapshot_id
        if snapshot_id:
            base_drilldown_query = query.model_dump()
            base_drilldown_query.pop("channel_name", None)
            for channel in response.channels:
                if channel.positioned_count <= 0:
                    continue
                page = 1
                total = 0
                while page == 1 or (page - 1) * drilldown_page_size < min(total, drilldown_limit):
                    drilldown_query = VesselPositionNavigationChannelVesselsQuery(
                        **base_drilldown_query,
                        channel_code=channel.channel_code,
                        channel_name=None if channel.channel_code else channel.channel_name,
                        query_snapshot_id=snapshot_id,
                        page=page,
                        page_size=drilldown_page_size,
                    )
                    drilldown_response = await service.position_channel_vessels(drilldown_query)
                    total = int(getattr(drilldown_response, "total", 0) or 0)
                    drilldown_count += 1
                    if total <= page * drilldown_page_size:
                        break
                    page += 1
        return {
            "source_status": response.source_status,
            "generated_at": response.generated_at.isoformat(),
            "positioned_count": response.summary.positioned_count,
            "channel_count": response.summary.channel_count,
            "drilldown_count": drilldown_count,
            "is_partial": response.summary.is_partial,
            "snapshot_backend": response.snapshot_backend,
        }


@celery_app.task(name="vessel.precompute_city_situation")
def precompute_city_situation_task() -> dict[str, Any]:
    return _run_coro_sync(_precompute_city_situation())


@celery_app.task(name="vessel.precompute_channel_situation")
def precompute_channel_situation_task() -> dict[str, Any]:
    return _run_coro_sync(_precompute_channel_situation())


@worker_ready.connect
def precompute_situations_on_worker_ready(sender=None, **_kwargs) -> None:
    if not bool(settings.VESSEL_SITUATION_PRECOMPUTE_ON_WORKER_START):
        return
    try:
        precompute_city_situation_task.apply_async(queue="analysis")
        precompute_channel_situation_task.apply_async(queue="analysis")
        logger.info("queued vessel situation precompute tasks on celery worker ready")
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to queue vessel situation precompute tasks on worker ready: %s", exc)
