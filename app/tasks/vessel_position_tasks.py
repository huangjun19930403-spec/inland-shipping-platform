"""Celery vessel position task entrypoints."""

from __future__ import annotations

import asyncio
import logging
import uuid
from threading import Thread
from typing import Any

from celery.signals import worker_ready

from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.modules.vessel.schemas import (
    VesselPositionCitySituationQuery,
    VesselPositionCityVesselsQuery,
    VesselPositionNavigationChannelSituationQuery,
    VesselPositionNavigationChannelVesselsQuery,
)
from app.modules.vessel.ais.service import VesselAisService as VesselService
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_coro_sync(coro):
    engine.sync_engine.dispose(close=False)
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


def _city_precompute_query() -> VesselPositionCitySituationQuery:
    query = VesselPositionCitySituationQuery(
        reported_within_minutes=1440,
        include_boundary=False,
        boundary_precision="low",
    )
    object.__setattr__(query, "force_refresh", False)
    return query


def _channel_precompute_query() -> VesselPositionNavigationChannelSituationQuery:
    query = VesselPositionNavigationChannelSituationQuery(
        reported_within_minutes=1440,
        include_boundary=False,
        include_empty_channels=False,
        boundary_precision="low",
        channel_type_codes="MAIN_LINE,MAIN_RIVER_CHANNEL,TRIBUTARY_CHANNEL,CANAL,CHANNEL_NETWORK,DELTA_WATERWAY",
        planning_level_codes="NATIONAL_CORE,NATIONAL_NETWORK,NATIONAL_IMPORTANT,PROVINCIAL_HIGH_GRADE,REGIONAL_IMPORTANT,REVIEW",
    )
    object.__setattr__(query, "force_refresh", False)
    return query


async def _precompute_ais_situation() -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        drilldown_limit = max(1, int(settings.VESSEL_SITUATION_PRECOMPUTE_DRILLDOWN_LIMIT or 100))
        city_group_limit = max(
            0,
            int(
                settings.VESSEL_CITY_SITUATION_PRECOMPUTE_GROUP_LIMIT
                if settings.VESSEL_CITY_SITUATION_PRECOMPUTE_GROUP_LIMIT is not None
                else settings.VESSEL_SITUATION_PRECOMPUTE_GROUP_LIMIT
                or 0
            ),
        )
        channel_group_limit = max(
            0,
            int(
                settings.VESSEL_CHANNEL_SITUATION_PRECOMPUTE_GROUP_LIMIT
                if settings.VESSEL_CHANNEL_SITUATION_PRECOMPUTE_GROUP_LIMIT is not None
                else settings.VESSEL_SITUATION_PRECOMPUTE_GROUP_LIMIT
                or 0
            ),
        )
        drilldown_page_size = max(1, min(100, drilldown_limit))
        service = VesselService(db)
        lock_token = uuid.uuid4().hex
        lock_acquired = False
        redis_client = None
        try:
            redis_client = await service._city_redis()  # noqa: SLF001 - reuse the AIS shared Redis client.
            if redis_client is not None:
                lock_acquired = bool(await redis_client.set("vessel:ais_situation:full_precompute_lock", lock_token, ex=1200, nx=True))
                if not lock_acquired:
                    return {"status": "SKIPPED", "reason": "full AIS situation precompute is already running"}
        except Exception as exc:  # noqa: BLE001
            logger.warning("AIS full precompute lock unavailable; continuing without distributed lock: %s", exc)
        city_query = _city_precompute_query()
        channel_query = _channel_precompute_query()
        try:
            snapshot = await service.precompute_full_ais_position_snapshot(city_query)
            city_response = await service.position_city_situation(city_query)
            precomputed_items = getattr(service, "_last_full_ais_position_items", None)
            precomputed_generated_at = getattr(service, "_last_full_ais_position_generated_at", None)
            channel_response = None
            if precomputed_items is not None and precomputed_generated_at is not None:
                channel_response = await service._channel_situation_from_precomputed_items(  # noqa: SLF001 - precompute avoids a second polygon scan.
                    channel_query,
                    precomputed_items,
                    snapshot,
                    generated_at=precomputed_generated_at,
                    cache_backend=await service._city_cache_backend(),  # noqa: SLF001
                    message="已返回最近一次入库 AIS 航道快照；后台任务会持续刷新全量船位。",
                    channel_type_codes=service._channel_query_code_set(channel_query, "channel_type_codes"),  # noqa: SLF001
                    planning_level_codes=service._channel_query_code_set(channel_query, "planning_level_codes"),  # noqa: SLF001
                )
            if channel_response is None:
                channel_response = await service.position_channel_situation(channel_query)
            city_drilldown_count = 0
            city_snapshot_id = city_response.summary.query_snapshot_id
            if city_snapshot_id:
                base_drilldown_query = city_query.model_dump()
                cities = sorted(
                    city_response.cities,
                    key=lambda item: int(getattr(item, "positioned_count", 0) or 0),
                    reverse=True,
                )
                cities = cities[:city_group_limit] if city_group_limit else []
                for city in cities:
                    if city.positioned_count <= 0:
                        continue
                    page = 1
                    total = 0
                    while page == 1 or (page - 1) * drilldown_page_size < min(total, drilldown_limit):
                        drilldown_query = VesselPositionCityVesselsQuery(
                            **base_drilldown_query,
                            city_code=city.city_code,
                            city_name=None if city.city_code else city.city_name,
                            query_snapshot_id=city_snapshot_id,
                            page=page,
                            page_size=drilldown_page_size,
                        )
                        drilldown_response = await service.position_city_vessels(drilldown_query)
                        total = int(getattr(drilldown_response, "total", 0) or 0)
                        city_drilldown_count += 1
                        if total <= page * drilldown_page_size:
                            break
                        page += 1
            channel_drilldown_count = 0
            channel_snapshot_id = channel_response.summary.query_snapshot_id
            if channel_snapshot_id:
                base_drilldown_query = channel_query.model_dump()
                base_drilldown_query.pop("channel_name", None)
                channels = sorted(
                    channel_response.channels,
                    key=lambda item: int(getattr(item, "positioned_count", 0) or 0),
                    reverse=True,
                )
                channels = channels[:channel_group_limit] if channel_group_limit else []
                for channel in channels:
                    if channel.positioned_count <= 0:
                        continue
                    page = 1
                    total = 0
                    while page == 1 or (page - 1) * drilldown_page_size < min(total, drilldown_limit):
                        drilldown_query = VesselPositionNavigationChannelVesselsQuery(
                            **base_drilldown_query,
                            channel_code=channel.channel_code,
                            channel_name=None if channel.channel_code else channel.channel_name,
                            query_snapshot_id=channel_snapshot_id,
                            page=page,
                            page_size=drilldown_page_size,
                        )
                        drilldown_response = await service.position_channel_vessels(drilldown_query)
                        total = int(getattr(drilldown_response, "total", 0) or 0)
                        channel_drilldown_count += 1
                        if total <= page * drilldown_page_size:
                            break
                        page += 1
            return {
                "snapshot": snapshot,
                "city": {
                    "source_status": city_response.source_status,
                    "generated_at": city_response.generated_at.isoformat(),
                    "positioned_count": city_response.summary.positioned_count,
                    "city_count": city_response.summary.city_count,
                    "drilldown_count": city_drilldown_count,
                    "is_partial": city_response.summary.is_partial,
                    "snapshot_backend": city_response.snapshot_backend,
                },
                "channel": {
                    "source_status": channel_response.source_status,
                    "generated_at": channel_response.generated_at.isoformat(),
                    "positioned_count": channel_response.summary.positioned_count,
                    "channel_count": channel_response.summary.channel_count,
                    "drilldown_count": channel_drilldown_count,
                    "is_partial": channel_response.summary.is_partial,
                    "snapshot_backend": channel_response.snapshot_backend,
                },
            }
        finally:
            if redis_client is not None and lock_acquired:
                try:
                    if await redis_client.get("vessel:ais_situation:full_precompute_lock") == lock_token:
                        await redis_client.delete("vessel:ais_situation:full_precompute_lock")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("failed to release AIS full precompute lock: %s", exc)


async def _precompute_city_situation() -> dict[str, Any]:
    result = await _precompute_ais_situation()
    if "city" not in result:
        return result
    return result["city"]


async def _precompute_channel_situation() -> dict[str, Any]:
    result = await _precompute_ais_situation()
    if "channel" not in result:
        return result
    return result["channel"]


@celery_app.task(name="vessel.precompute_ais_situation")
def precompute_ais_situation_task() -> dict[str, Any]:
    return _run_coro_sync(_precompute_ais_situation())


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
        precompute_ais_situation_task.apply_async(queue="analysis")
        logger.info("queued vessel AIS situation full precompute task on celery worker ready")
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to queue vessel situation precompute tasks on worker ready: %s", exc)
