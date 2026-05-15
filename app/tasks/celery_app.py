"""Celery 应用配置。"""

from __future__ import annotations

import asyncio
import logging

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_ready, worker_shutdown

from app.core.config import settings
from app.integrations.external_session_registry import ExternalSessionRegistry

logger = logging.getLogger(__name__)


def _daily_crontab():
    parts = (settings.ANALYSIS_DEFAULT_DAILY_CRON or "20 2 * * *").split()
    if len(parts) < 2:
        return crontab(minute=20, hour=2)
    return crontab(minute=parts[0], hour=parts[1])


celery_app = Celery(
    "inland_shipping_analysis",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.analysis_tasks",
        "app.tasks.freight_ai_tasks",
        "app.tasks.vessel_ai_tasks",
        "app.tasks.vessel_position_tasks",
    ],
)

celery_app.conf.update(
    task_default_queue="analysis",
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=False,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=1200,
    task_soft_time_limit=1140,
    task_always_eager=settings.ANALYSIS_CELERY_EAGER,
    task_eager_propagates=settings.ANALYSIS_CELERY_EAGER,
    task_routes={
        "analysis.run_job": {"queue": "analysis"},
        "freight.parse_wechat_batch": {"queue": "freight_ai"},
        "freight.parse_tms_inbound": {"queue": "freight_ai"},
        "freight.clean_normalization": {"queue": "freight_ai"},
        "vessel.recognize_certificate_image": {"queue": "vessel_ai"},
        "vessel.recognize_person_certificate_image": {"queue": "vessel_ai"},
        "vessel.recognize_owner_document_image": {"queue": "vessel_ai"},
        "vessel.precompute_city_situation": {"queue": "analysis"},
        "vessel.precompute_water_system_situation": {"queue": "analysis"},
        "analysis.precompute_flow_route_cache": {"queue": "analysis"},
    },
)

celery_app.conf.beat_schedule = {
    "analysis-all-daily": {
        "task": "analysis.run_job",
        "schedule": _daily_crontab(),
        "args": ("ANALYSIS_ALL_DAILY", None, None, True, {"triggered_by": "celery_beat"}),
    },
    "vessel-city-situation-precompute": {
        "task": "vessel.precompute_city_situation",
        "schedule": max(30, int(settings.VESSEL_CITY_SITUATION_PRECOMPUTE_SECONDS or 60)),
    },
    "vessel-water-system-situation-precompute": {
        "task": "vessel.precompute_water_system_situation",
        "schedule": max(30, int(settings.VESSEL_WATER_SYSTEM_SITUATION_PRECOMPUTE_SECONDS or 60)),
    },
    "analysis-flow-route-cache-precompute": {
        "task": "analysis.precompute_flow_route_cache",
        "schedule": max(60, int(settings.ANALYSIS_FLOW_ROUTE_PRECOMPUTE_SECONDS or 300)),
        "args": (None, None, ["freight", "ship"], settings.ANALYSIS_FLOW_ROUTE_PRECOMPUTE_LIMIT, False),
    },
}


def _run_external_session_coro(coro) -> None:
    try:
        asyncio.run(coro)
    except Exception as exc:  # noqa: BLE001
        logger.warning("external session lifecycle task failed: %s", exc)


@worker_ready.connect
def warmup_external_sessions_on_worker_ready(sender=None, **_kwargs) -> None:
    _ = sender
    _run_external_session_coro(ExternalSessionRegistry.warmup("hifleet"))


@worker_shutdown.connect
def shutdown_external_sessions_on_worker_shutdown(sender=None, **_kwargs) -> None:
    _ = sender
    _run_external_session_coro(ExternalSessionRegistry.shutdown("hifleet"))
