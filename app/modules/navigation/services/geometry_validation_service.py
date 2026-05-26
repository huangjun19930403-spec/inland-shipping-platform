from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NavigationGeometryDraft
from app.modules.navigation.schemas import (
    NavigationGeometryDraftValidateRequest,
    NavigationGeometryDraftValidationResponse,
)


class NavigationGeometryValidationService:
    """Validation facade for geometry draft production.

    The detailed geometric checks still reuse the shared workbench helper
    methods so route/API behavior stays unchanged while public validation flow
    is no longer embedded in the workbench facade.
    """

    def __init__(self, session: AsyncSession, helpers: Any) -> None:
        self.session = session
        self.helpers = helpers

    async def validate_geometry_draft(
        self,
        body: NavigationGeometryDraftValidateRequest,
    ) -> NavigationGeometryDraftValidationResponse:
        draft_type = body.draft_type_code.upper()
        geometry = self.helpers._normalized_geometry(body.geometry_json)
        self.helpers._validate_geometry_for_draft(draft_type, geometry, body.channel_id, require_channel=False)
        if body.channel_id is not None:
            await self.helpers._ensure_channel(body.channel_id)
        return await self.validate_draft_geometry(
            draft_type=draft_type,
            channel_id=body.channel_id,
            geometry=geometry,
        )

    async def validate_draft_geometry(
        self,
        *,
        draft_type: str,
        channel_id: int | None,
        geometry: dict[str, Any],
    ) -> NavigationGeometryDraftValidationResponse:
        return await self.helpers._validate_draft_geometry(
            draft_type=draft_type,
            channel_id=channel_id,
            geometry=geometry,
        )

    async def validate_centerline_publish(self, draft: NavigationGeometryDraft) -> None:
        validation = await self.validate_draft_geometry(
            draft_type="CENTERLINE",
            channel_id=draft.channel_id,
            geometry=draft.geometry_json,
        )
        if not validation.publishable:
            raise self.helpers._publish_validation_response(validation)

    async def validate_boundary_publish(self, draft: NavigationGeometryDraft) -> None:
        validation = await self.validate_draft_geometry(
            draft_type="BOUNDARY",
            channel_id=draft.channel_id,
            geometry=draft.geometry_json,
        )
        if not validation.publishable:
            raise self.helpers._publish_validation_response(validation)
