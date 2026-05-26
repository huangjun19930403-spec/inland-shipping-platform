from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ValidationError
from app.models import NavigationGeometryDraft
from app.models.address import NavigationChannel
from app.modules.navigation.schemas import (
    NavigationGeometryDraftCreateRequest,
    NavigationGeometryDraftResponse,
    NavigationGeometryDraftUpdateRequest,
)
from app.modules.navigation.services.geometry_validation_service import NavigationGeometryValidationService


FINAL_DRAFT_STATUSES = {"PUBLISHED", "REJECTED"}
ARCHIVED_DRAFT_STATUSES = {"ARCHIVED", "DELETED"}


class NavigationGeometryDraftService:
    """Draft CRUD and publishing workflow for navigation geometry production."""

    def __init__(self, session: AsyncSession, helpers: Any) -> None:
        self.session = session
        self.helpers = helpers
        self.validation = NavigationGeometryValidationService(session, helpers)

    async def list_geometry_drafts(
        self,
        *,
        status_code: str | None = None,
        channel_id: int | None = None,
        limit: int = 50,
    ) -> list[NavigationGeometryDraftResponse]:
        stmt = select(NavigationGeometryDraft, NavigationChannel).outerjoin(
            NavigationChannel, NavigationChannel.id == NavigationGeometryDraft.channel_id
        )
        if status_code:
            stmt = stmt.where(NavigationGeometryDraft.status_code == status_code.upper())
        else:
            stmt = stmt.where(NavigationGeometryDraft.status_code.not_in(ARCHIVED_DRAFT_STATUSES))
        if channel_id:
            stmt = stmt.where(NavigationGeometryDraft.channel_id == channel_id)
        rows = list(
            (
                await self.session.execute(
                    stmt.order_by(NavigationGeometryDraft.id.desc()).limit(
                        self.helpers._limit(limit, default=50, max_value=200)
                    )
                )
            ).all()
        )
        return [self.helpers._draft_response(draft, channel) for draft, channel in rows]

    async def create_geometry_draft(
        self,
        body: NavigationGeometryDraftCreateRequest,
        *,
        created_by: int | None,
    ) -> NavigationGeometryDraftResponse:
        draft_type = body.draft_type_code.upper()
        geometry = self.helpers._normalized_geometry(body.geometry_json)
        geometry_type = self.helpers._validate_geometry_for_draft(draft_type, geometry, body.channel_id)
        bbox = self.helpers._geometry_bbox(geometry)
        if body.channel_id is not None:
            await self.helpers._ensure_channel(body.channel_id)
        validation = await self.validation.validate_draft_geometry(
            draft_type=draft_type,
            channel_id=body.channel_id,
            geometry=geometry,
        )
        draft = NavigationGeometryDraft(
            draft_no=self.helpers._draft_no(),
            draft_name=body.draft_name,
            draft_type_code=draft_type,
            geometry_type_code=geometry_type,
            channel_id=body.channel_id,
            target_type_code=body.target_type_code.upper() if body.target_type_code else None,
            target_id=body.target_id,
            geometry_json=geometry,
            source_type_code=body.source_type_code.upper(),
            status_code="DRAFT",
            quality_code=validation.quality_code,
            review_comment=self.helpers._validation_review_comment(validation),
            source_trace_json=self.helpers._source_trace_with_validation_summary(body.source_trace_json, validation),
            created_by=created_by,
            **bbox,
        )
        self.session.add(draft)
        await self.session.commit()
        return await self.helpers._draft_response_by_id(draft.id)

    async def update_geometry_draft(
        self,
        draft_id: int,
        body: NavigationGeometryDraftUpdateRequest,
    ) -> NavigationGeometryDraftResponse:
        draft = await self.helpers._draft(draft_id)
        if draft.status_code in FINAL_DRAFT_STATUSES | ARCHIVED_DRAFT_STATUSES:
            raise ConflictError("已发布或已归档的草稿不能继续编辑")
        if body.channel_id is not None:
            await self.helpers._ensure_channel(body.channel_id)
            draft.channel_id = body.channel_id
        if body.draft_name is not None:
            draft.draft_name = body.draft_name
        if body.target_type_code is not None:
            draft.target_type_code = body.target_type_code.upper()
        if body.target_id is not None:
            draft.target_id = body.target_id
        if body.source_type_code is not None:
            draft.source_type_code = body.source_type_code.upper()
        if body.source_trace_json is not None:
            draft.source_trace_json = body.source_trace_json
        if body.geometry_json is not None:
            geometry = self.helpers._normalized_geometry(body.geometry_json)
            draft.geometry_type_code = self.helpers._validate_geometry_for_draft(
                draft.draft_type_code,
                geometry,
                draft.channel_id,
            )
            draft.geometry_json = geometry
            for key, value in self.helpers._geometry_bbox(geometry).items():
                setattr(draft, key, value)
        validation = await self.validation.validate_draft_geometry(
            draft_type=draft.draft_type_code,
            channel_id=draft.channel_id,
            geometry=draft.geometry_json,
        )
        self.helpers._apply_validation_to_draft(draft, validation)
        if draft.status_code == "PUBLISH_BLOCKED":
            draft.status_code = "DRAFT"
        await self.session.commit()
        return await self.helpers._draft_response_by_id(draft.id)

    async def publish_geometry_draft(
        self,
        draft_id: int,
        *,
        published_by: int | None,
    ) -> NavigationGeometryDraftResponse:
        draft = await self.helpers._draft(draft_id)
        if draft.status_code not in {"DRAFT", "PUBLISH_BLOCKED"}:
            raise ConflictError("只有 DRAFT 或 PUBLISH_BLOCKED 草稿可以发布")
        try:
            if draft.draft_type_code in {"CENTERLINE", "BOUNDARY"}:
                validation = await self.validation.validate_draft_geometry(
                    draft_type=draft.draft_type_code,
                    channel_id=draft.channel_id,
                    geometry=draft.geometry_json,
                )
                self.helpers._apply_validation_to_draft(draft, validation)
                if not validation.publishable:
                    raise self.helpers._publish_validation_response(validation)
            if draft.draft_type_code == "CENTERLINE":
                target_id = await self.helpers._publish_centerline(draft, published_by=published_by)
                draft.publish_target_type_code = "CENTERLINE"
            elif draft.draft_type_code == "BOUNDARY":
                target_id = await self.helpers._publish_boundary(draft, published_by=published_by)
                draft.publish_target_type_code = "BOUNDARY"
            elif draft.draft_type_code == "WATER_AREA":
                target_id = await self.helpers._publish_water_area(draft)
                draft.publish_target_type_code = "WATER_AREA"
            else:
                raise ValidationError(f"Unsupported draft_type_code: {draft.draft_type_code}")
        except ValidationError as exc:
            draft.status_code = "PUBLISH_BLOCKED"
            draft.quality_code = "PUBLISH_BLOCKED"
            draft.review_comment = exc.message[:512]
            if isinstance(exc.detail, dict) and isinstance(exc.detail.get("validation"), dict):
                draft.source_trace_json = {
                    **(draft.source_trace_json or {}),
                    "validation_summary": self.helpers._validation_summary_from_dict(exc.detail["validation"]),
                }
            await self.session.commit()
            raise
        draft.publish_target_id = target_id
        draft.status_code = "PUBLISHED"
        draft.quality_code = "READY"
        draft.published_by = published_by
        draft.published_at = self.helpers._now()
        await self.session.commit()
        return await self.helpers._draft_response_by_id(draft.id)

    async def archive_geometry_draft(self, draft_id: int) -> NavigationGeometryDraftResponse:
        draft = await self.helpers._draft(draft_id)
        if draft.status_code == "PUBLISHED":
            raise ConflictError("已发布草稿不能删除；请通过新版本发布完成替换")
        if draft.status_code in ARCHIVED_DRAFT_STATUSES:
            return await self.helpers._draft_response_by_id(draft.id)
        draft.status_code = "ARCHIVED"
        draft.quality_code = "ARCHIVED"
        await self.session.commit()
        return await self.helpers._draft_response_by_id(draft.id)
