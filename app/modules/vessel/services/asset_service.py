"""Asset-domain service boundary for vessel routes."""

from __future__ import annotations

from typing import Any, Callable, Awaitable

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.vessel.service import VesselService


class VesselAssetService:
    """Explicit facade for asset profile, ledger, summary, and certificate operations."""

    def __init__(self, db: AsyncSession):
        self._facade = VesselService(db)


def _delegate(name: str) -> Callable[..., Awaitable[Any]]:
    async def method(self: VesselAssetService, *args: Any, **kwargs: Any) -> Any:
        return await getattr(self._facade, name)(*args, **kwargs)

    method.__name__ = name
    return method


for _method_name in (
    "asset_summary",
    "list_assets",
    "refresh_vessel_summary",
    "refresh_vessel_summaries_batch",
    "list_vessels",
    "create_vessel",
    "get_profile_card",
    "get_profile_card_evidence",
    "get_detail",
    "update_profile",
    "upsert_registration",
    "upsert_capacity",
    "upsert_build_info",
    "list_person_certificates",
    "replace_person_certificates",
    "create_person_certificate",
    "update_person_certificate",
    "void_person_certificate",
    "upload_person_certificate_file_first",
    "upload_person_certificate_file",
    "void_person_certificate_file",
    "list_certificates",
    "get_certificate_ledger",
    "create_certificate",
    "update_certificate",
    "void_certificate",
    "upload_certificate_file_first",
    "upload_certificate_file",
    "void_certificate_file",
):
    setattr(VesselAssetService, _method_name, _delegate(_method_name))
