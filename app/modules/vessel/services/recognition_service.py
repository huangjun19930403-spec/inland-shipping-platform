"""Recognition-domain service boundary for vessel routes."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.vessel.service import VesselService


class VesselRecognitionService:
    """Explicit facade for OCR queues, field diffs, and adoption records."""

    def __init__(self, db: AsyncSession):
        self._facade = VesselService(db)


def _delegate(name: str) -> Callable[..., Awaitable[Any]]:
    async def method(self: VesselRecognitionService, *args: Any, **kwargs: Any) -> Any:
        return await getattr(self._facade, name)(*args, **kwargs)

    method.__name__ = name
    return method


for _method_name in (
    "list_recognition_queue",
    "unified_recognition_field_diff",
    "unified_recognition_adoption",
    "confirm_owner_document_image_recognition",
    "owner_document_recognition_field_diff",
    "adopt_owner_document_recognition",
    "create_person_certificate_image_recognition",
    "list_person_certificate_image_recognitions",
    "confirm_person_certificate_image_recognition",
    "person_certificate_recognition_field_diff",
    "adopt_person_certificate_recognition",
    "create_certificate_image_recognition",
    "list_certificate_image_recognitions",
    "confirm_certificate_image_recognition",
    "certificate_recognition_field_diff",
    "adopt_certificate_recognition",
    "list_owner_document_image_recognitions",
):
    setattr(VesselRecognitionService, _method_name, _delegate(_method_name))
