"""Celery task entrypoints for standalone vessel image recognition."""

from __future__ import annotations

import asyncio
from threading import Thread
from typing import Any

from app.core.database import AsyncSessionLocal
from app.modules.vessel.service import VesselService
from app.tasks.celery_app import celery_app


def _run_coro_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: Any = None
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


async def _recognize_certificate_image(recognition_id: int) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        return await VesselService(db).process_certificate_image_recognition(recognition_id)


async def _recognize_person_certificate_image(recognition_id: int) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        return await VesselService(db).process_person_certificate_image_recognition(recognition_id)


async def _recognize_owner_document_image(recognition_id: int) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        return await VesselService(db).process_owner_document_image_recognition(recognition_id)


@celery_app.task(name="vessel.recognize_certificate_image")
def recognize_vessel_certificate_image_task(recognition_id: int) -> dict[str, Any]:
    return _run_coro_sync(_recognize_certificate_image(recognition_id))


@celery_app.task(name="vessel.recognize_person_certificate_image")
def recognize_vessel_person_certificate_image_task(recognition_id: int) -> dict[str, Any]:
    return _run_coro_sync(_recognize_person_certificate_image(recognition_id))


@celery_app.task(name="vessel.recognize_owner_document_image")
def recognize_vessel_owner_document_image_task(recognition_id: int) -> dict[str, Any]:
    return _run_coro_sync(_recognize_owner_document_image(recognition_id))
