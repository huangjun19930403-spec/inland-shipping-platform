"""Celery vessel position task entrypoints."""

from __future__ import annotations

import asyncio
from threading import Thread
from typing import Any

from app.core.database import AsyncSessionLocal
from app.modules.vessel.schemas import VesselPositionCitySituationQuery
from app.modules.vessel.service import VesselService
from app.tasks.celery_app import celery_app


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
        response = await VesselService(db).position_city_situation(
            VesselPositionCitySituationQuery(
                reported_within_minutes=1440,
                es_batch_size=500,
                es_max_concurrency=4,
                include_boundary=True,
                boundary_precision="low",
                force_refresh=True,
            )
        )
        return {
            "source_status": response.source_status,
            "generated_at": response.generated_at.isoformat(),
            "positioned_count": response.summary.positioned_count,
            "city_count": response.summary.city_count,
            "is_partial": response.summary.is_partial,
            "snapshot_backend": response.snapshot_backend,
        }


@celery_app.task(name="vessel.precompute_city_situation")
def precompute_city_situation_task() -> dict[str, Any]:
    return _run_coro_sync(_precompute_city_situation())
