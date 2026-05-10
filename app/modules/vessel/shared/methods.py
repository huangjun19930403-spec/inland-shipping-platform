"""Implementation methods for the vessel core domain."""

from __future__ import annotations

from app.modules.vessel.shared import base as _base

globals().update({name: getattr(_base, name) for name in dir(_base) if not name.startswith("__")})


class VesselCoreMixin:
    """Implementation methods for the vessel core domain."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = VesselRepository(db)
        self.runtime_config = RuntimeConfigService(db)

    def _latest_datetime(self, *values: datetime | None) -> datetime | None:
        filtered = [item for item in values if item is not None]
        return max(filtered) if filtered else None

    async def _require_profile(self, vessel_id: int) -> VesselProfile:
        profile = await self.repo.get_profile(vessel_id)
        if profile is None:
            raise NotFoundError("VesselProfile", vessel_id)
        return profile

    async def _map_by_profile(self, model, ids: list[int]) -> dict[int, Any]:
        rows = (await self.db.execute(select(model).where(model.vessel_profile_id.in_(ids)))).scalars().all()
        return {row.vessel_profile_id: row for row in rows}

    async def _first_by_profile(self, model, ids: list[int]) -> dict[int, Any]:
        rows = (
            await self.db.execute(
                select(model)
                .where(model.vessel_profile_id.in_(ids))
                .order_by(model.vessel_profile_id.asc(), model.is_primary.desc(), model.id.asc())
            )
        ).scalars().all()
        result: dict[int, Any] = {}
        for row in rows:
            result.setdefault(row.vessel_profile_id, row)
        return result

    async def _profiles_by_ids(self, ids: list[int]) -> dict[int, VesselProfile]:
        if not ids:
            return {}
        rows = (await self.db.execute(select(VesselProfile).where(VesselProfile.id.in_(ids)))).scalars().all()
        return {row.id: row for row in rows}

    def _ensure_revision(self, row: Any, revision: int | None) -> None:
        if revision is None:
            raise ValidationError("revision is required")
        if int(getattr(row, "revision", 1)) != int(revision):
            raise ConflictError(
                "记录 revision 已变化，请刷新后重试",
                code="REVISION_CONFLICT",
                detail={"id": getattr(row, "id", None), "current_revision": getattr(row, "revision", None)},
            )

    async def _close_current_mmsi_history(self, vessel_id: int, old_mmsi: str | None) -> None:
        if not old_mmsi:
            return
        rows = (
            await self.db.execute(
                select(VesselIdentifierHistory).where(
                    VesselIdentifierHistory.vessel_profile_id == vessel_id,
                    VesselIdentifierHistory.identifier_type_code == "MMSI",
                    VesselIdentifierHistory.identifier_value == old_mmsi,
                    VesselIdentifierHistory.end_date.is_(None),
                )
            )
        ).scalars().all()
        for row in rows:
            row.end_date = date.today()
            row.status_code = "HISTORICAL"

    @staticmethod
    def _maybe(response_cls, row):
        return response_cls(**_row_dict(row)) if row is not None else None

    async def _add_change_event(
        self,
        vessel_id: int,
        event_type_code: str,
        event_title: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        operator_id: int | None,
        *,
        object_type: str | None = None,
        object_id: str | int | None = None,
        changed_fields: list[str] | None = None,
        reason: str | None = None,
    ) -> int:
        row = VesselChangeEvent(
            vessel_profile_id=vessel_id,
            event_type_code=event_type_code,
            event_title=event_title,
            object_type=object_type,
            object_id=str(object_id) if object_id is not None else None,
            before_json=_jsonable(before),
            after_json=_jsonable(after),
            changed_fields_json=changed_fields if changed_fields is not None else _changed_fields(before, after),
            reason=reason,
            operator_id=operator_id,
            created_at=datetime.utcnow(),
        )
        self.db.add(row)
        await self.db.flush()
        return int(row.id)

    async def _copy_singletons(self, source_id: int, target_id: int) -> None:
        for model in [VesselRegistrationInfo, VesselCapacityDimension, VesselBuildInfo]:
            row = await self.repo.get_one_by_profile(model, source_id)
            if row is None:
                continue
            data = _row_dict(row)
            data.pop("id", None)
            data["vessel_profile_id"] = target_id
            if "updated_at" in data:
                data["updated_at"] = datetime.utcnow()
            self.db.add(model(**data))
        await self.db.flush()

    async def _copy_history(self, source_id: int, target_id: int) -> None:
        for model in [VesselNameHistory, VesselIdentifierHistory]:
            rows = await self.repo.list_by_profile(model, source_id)
            for row in rows:
                data = _row_dict(row)
                data.pop("id", None)
                data["vessel_profile_id"] = target_id
                self.db.add(model(**data))
        await self.db.flush()
