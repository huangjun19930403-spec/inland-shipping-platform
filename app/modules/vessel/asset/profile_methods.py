"""Vessel profile maintenance methods for the asset domain."""

from __future__ import annotations

from app.modules.vessel.asset.list_methods import VesselAssetListMixin
from app.modules.vessel.shared import base as _base

globals().update({name: getattr(_base, name) for name in dir(_base) if not name.startswith("__")})


class VesselAssetMixin(VesselAssetListMixin):
    """Base vessel profile, detail, and dimension maintenance."""

    async def create_vessel(self, payload, *, operator_id: int | None = None) -> VesselProfileResponse:
        await self._assert_active_mmsi_available(payload.mmsi, evidence_source="CREATE_VESSEL")
        code = await CodeSequenceService(self.db).next_code("VESSEL_PROFILE_CODE")
        entity = await self.repo.create_profile(
            {
                "vessel_profile_code": code,
                "ship_name": payload.ship_name.strip(),
                "current_mmsi": payload.mmsi,
                "profile_status_code": "ACTIVE",
                "identity_status_code": "UNLINKED",
                "source_type_code": payload.source_type_code,
            }
        )
        await self.repo.add_name_history(entity.id, entity.ship_name)
        await self.repo.add_identifier_history(entity.id, "MMSI", entity.current_mmsi)
        await self._add_change_event(entity.id, "CREATE", "新增船舶档案", None, _row_dict(entity), operator_id)
        await self.db.commit()
        await self._refresh_summary_best_effort(entity.id)
        return await self._build_profile_response(entity.id)

    async def update_profile(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselProfileResponse:
        profile = await self._require_profile(vessel_id)
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        before = _row_dict(profile)
        if "ship_name" in updates:
            updates["ship_name"] = updates["ship_name"].strip()
        new_status = updates.get("profile_status_code", profile.profile_status_code)
        new_mmsi = updates.get("current_mmsi", profile.current_mmsi)
        becoming_active = profile.profile_status_code != ACTIVE_PROFILE_STATUS and new_status == ACTIVE_PROFILE_STATUS
        mmsi_changing = "current_mmsi" in updates and new_mmsi != before.get("current_mmsi")
        if new_status == ACTIVE_PROFILE_STATUS and (becoming_active or mmsi_changing):
            await self._assert_active_mmsi_available(
                new_mmsi,
                exclude_vessel_id=vessel_id,
                attempted_profile_id=vessel_id,
                evidence_source="UPDATE_PROFILE",
            )
        row = await self.repo.update_profile(vessel_id, updates)
        if row is None:
            raise NotFoundError("VesselProfile", vessel_id)
        if "ship_name" in updates and updates["ship_name"] != before.get("ship_name"):
            await self.repo.add_name_history(vessel_id, updates["ship_name"])
        if "current_mmsi" in updates and updates["current_mmsi"] != before.get("current_mmsi"):
            await self._close_current_mmsi_history(vessel_id, before.get("current_mmsi"))
            await self.repo.add_identifier_history(vessel_id, "MMSI", updates["current_mmsi"])
        await self._add_change_event(vessel_id, "UPDATE_PROFILE", "更新船舶主档", before, updates, operator_id)
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        return await self._build_profile_response(vessel_id)

    async def get_detail(self, vessel_id: int) -> VesselDetailResponse:
        profile = await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        city_map = await _load_city_map(self.db, [profile.registry_city_code] if profile.registry_city_code else [])
        region_map = await _load_region_map(self.db, [profile.business_region_id] if profile.business_region_id else [])
        owner_rows = await self._effective_profile_rows(VesselOwnerPeriod, vessel_id)
        owner_documents = await self._owner_documents_by_owner(vessel_id, label_map)
        return VesselDetailResponse(
            profile=_profile_response(profile, label_map=label_map, city_map=city_map, region_map=region_map),
            registration=self._maybe(VesselRegistrationResponse, await self.repo.get_one_by_profile(VesselRegistrationInfo, vessel_id)),
            capacity=self._maybe(VesselCapacityResponse, await self.repo.get_one_by_profile(VesselCapacityDimension, vessel_id)),
            build_info=self._maybe(VesselBuildInfoResponse, await self.repo.get_one_by_profile(VesselBuildInfo, vessel_id)),
            owners=[self._owner_response(row, label_map, documents=owner_documents.get(row.id, [])) for row in owner_rows],
            operators=[self._operator_response(row, label_map) for row in await self._effective_profile_rows(VesselOperatorPeriod, vessel_id)],
            contacts=[self._contact_response(row, label_map) for row in await self._effective_profile_rows(VesselContact, vessel_id)],
            crew=[self._crew_response(row, label_map) for row in await self._effective_profile_rows(VesselCrewAssignment, vessel_id)],
            person_certificates=await self._person_certificates_with_files(vessel_id, label_map=label_map),
            certificates=await self._certificates_with_files(vessel_id, label_map=label_map),
            name_history=await self._history_items(VesselNameHistory, VesselNameHistoryResponse, "SOURCE_TYPE", "source_type_code", "source_type_name", vessel_id, label_map),
            identifier_history=await self._history_items(VesselIdentifierHistory, VesselIdentifierHistoryResponse, "SOURCE_TYPE", "source_type_code", "source_type_name", vessel_id, label_map),
            change_events=await self._history_items(VesselChangeEvent, VesselChangeEventResponse, "VESSEL_CHANGE_EVENT_TYPE", "event_type_code", "event_type_name", vessel_id, label_map),
        )

    async def upsert_registration(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselRegistrationResponse:
        await self._require_profile(vessel_id)
        before = await self.repo.get_one_by_profile(VesselRegistrationInfo, vessel_id)
        row = await self.repo.upsert_one_by_profile(VesselRegistrationInfo, vessel_id, payload.model_dump(exclude_none=True))
        profile_updates = {
            key: value
            for key, value in {
                "registry_city_code": row.registry_city_code,
                "home_port_code": row.home_port_code,
                "home_port_name": row.home_port_name,
            }.items()
            if value
        }
        if profile_updates:
            await self.repo.update_profile(vessel_id, profile_updates)
        await self._add_change_event(vessel_id, "UPSERT_REGISTRATION", "维护船籍信息", _row_dict(before) if before else None, _row_dict(row), operator_id)
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        return VesselRegistrationResponse(**_row_dict(row))

    async def upsert_capacity(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselCapacityResponse:
        return await self._upsert_profile_component(vessel_id, payload, VesselCapacityDimension, VesselCapacityResponse, "UPSERT_CAPACITY", "维护船舶尺寸信息", operator_id)

    async def upsert_build_info(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselBuildInfoResponse:
        return await self._upsert_profile_component(vessel_id, payload, VesselBuildInfo, VesselBuildInfoResponse, "UPSERT_BUILD_INFO", "维护建造信息", operator_id)

    async def _upsert_profile_component(self, vessel_id: int, payload: Any, model: type[Any], response_model: type[Any], event_type: str, message: str, operator_id: int | None) -> Any:
        await self._require_profile(vessel_id)
        row = await self.repo.upsert_one_by_profile(model, vessel_id, payload.model_dump(exclude_none=True))
        await self._add_change_event(vessel_id, event_type, message, None, _row_dict(row), operator_id)
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        return response_model(**_row_dict(row))

    async def _effective_profile_rows(self, model: type[Any], vessel_id: int) -> list[Any]:
        return [row for row in await self.repo.list_by_profile(model, vessel_id) if _relation_is_effective(row)]

    async def _history_items(self, model: type[Any], response_model: type[Any], dict_code: str, code_attr: str, name_field: str, vessel_id: int, label_map: dict[str, dict[str, str]]) -> list[Any]:
        return [
            response_model(**_row_dict(row), **{name_field: label_map.get(dict_code, {}).get(getattr(row, code_attr))})
            for row in await self.repo.list_by_profile(model, vessel_id, order_desc=True)
        ]

    async def _build_profile_response(self, vessel_id: int) -> VesselProfileResponse:
        profile = await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        city_map = await _load_city_map(self.db, [profile.registry_city_code] if profile.registry_city_code else [])
        region_map = await _load_region_map(self.db, [profile.business_region_id] if profile.business_region_id else [])
        return _profile_response(profile, label_map=label_map, city_map=city_map, region_map=region_map)
