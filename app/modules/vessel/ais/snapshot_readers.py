"""Persisted AIS snapshot fallback readers and realtime error responses."""

from __future__ import annotations

from app.modules.vessel.ais.common import *


class VesselAisSnapshotReaderMixin:
    def _position_query_has_profile_filters(self, query) -> bool:
        return any(
            getattr(query, attr, None) not in (None, "")
            for attr in (
                "keyword",
                "ship_type_code",
                "profile_status_code",
                "deadweight_min",
                "deadweight_max",
                "draft_max",
                "contact_available",
            )
        )

    async def _latest_persisted_ais_snapshot(self, snapshot_id: str | None = None) -> VesselAisSnapshot | None:
        if not hasattr(self, "db") or not hasattr(self.db, "scalar"):
            return None
        stmt = select(VesselAisSnapshot).where(VesselAisSnapshot.status_code.in_(["READY", "PARTIAL"]))
        if snapshot_id:
            stmt = stmt.where(VesselAisSnapshot.snapshot_id == snapshot_id)
        return await self.db.scalar(stmt.order_by(VesselAisSnapshot.generated_at.desc()).limit(1))

    async def _snapshot_should_be_recomputed_from_realtime(self, snapshot: VesselAisSnapshot) -> bool:
        if int(snapshot.matched_position_count or 0) > 0:
            return False
        if int(snapshot.failed_batch_count or 0) <= 0:
            return False
        return bool(await self._realtime_es_host())

    async def _position_items_from_persisted_snapshot(
        self,
        snapshot: VesselAisSnapshot,
        *,
        generated_at: datetime,
        max_rows: int | None = None,
        include_city_center: bool = False,
    ) -> list[VesselPositionMonitorItemResponse]:
        stmt = (
            select(
                VesselLatestPositionSnapshot,
                VesselProfile,
                VesselProfileSummary,
                VesselCapacityDimension,
            )
            .join(
                VesselProfile,
                VesselProfile.id == VesselLatestPositionSnapshot.vessel_profile_id,
            )
            .outerjoin(
                VesselProfileSummary,
                VesselProfileSummary.vessel_profile_id == VesselProfile.id,
            )
            .outerjoin(
                VesselCapacityDimension,
                VesselCapacityDimension.vessel_profile_id == VesselProfile.id,
            )
            .where(
                VesselLatestPositionSnapshot.snapshot_id == snapshot.snapshot_id,
                VesselLatestPositionSnapshot.vessel_profile_id.is_not(None),
                VesselLatestPositionSnapshot.match_status_code.in_(["MATCHED_PROFILE", "MULTI_PROFILE_CONFLICT"]),
                VesselLatestPositionSnapshot.longitude.is_not(None),
                VesselLatestPositionSnapshot.latitude.is_not(None),
            )
            .order_by(VesselLatestPositionSnapshot.position_time.desc().nullslast(), VesselLatestPositionSnapshot.id.desc())
        )
        if max_rows is not None:
            stmt = stmt.limit(max_rows)
        rows = (await self.db.execute(stmt)).all()
        if not rows:
            return []
        label_map = await _load_label_map(
            self.db,
            [
                "SHIP_TYPE",
                "VESSEL_PROFILE_STATUS",
                "VESSEL_IDENTITY_STATUS",
                "SHIP_OPERATION_STATUS",
                "SOURCE_TYPE",
            ],
        )
        boundary_by_code = {}
        if include_city_center:
            boundaries = await self._city_boundaries()
            boundary_by_code = {boundary.code: boundary for boundary in boundaries}
        items: list[VesselPositionMonitorItemResponse] = []
        for row, profile, summary, capacity in rows:
            position_time = row.position_time
            age_minutes = int((generated_at - position_time).total_seconds() // 60) if position_time else None
            boundary = boundary_by_code.get(str(row.city_code or ""))
            city_code = str(row.city_code or "").strip() or None
            city_name = str(row.city_name or "").strip() or (UNKNOWN_CITY_NAME if not city_code else None)
            ship_type_code = (summary.ship_type_code if summary and summary.ship_type_code else profile.ship_type_code)
            profile_status_code = profile.profile_status_code or "ACTIVE"
            identity_status_code = profile.identity_status_code or "UNLINKED"
            operation_status_code = profile.operation_status_code
            source_type_code = profile.source_type_code or "SYSTEM"
            building_year = summary.building_year if summary and summary.building_year is not None else None
            design_draft_m = (
                _to_decimal(summary.design_draft_m)
                if summary and summary.design_draft_m is not None
                else _to_decimal(capacity.design_draft_m if capacity else None)
            )
            deadweight_ton = (
                _to_decimal(summary.deadweight_ton)
                if summary and summary.deadweight_ton is not None
                else _to_decimal(capacity.deadweight_ton if capacity else None)
            )
            length_m = (
                _to_decimal(summary.length_m)
                if summary and summary.length_m is not None
                else _to_decimal(capacity.length_m if capacity else None)
            )
            width_m = (
                _to_decimal(summary.width_m)
                if summary and summary.width_m is not None
                else _to_decimal(capacity.width_m if capacity else None)
            )
            items.append(
                VesselPositionMonitorItemResponse(
                    id=profile.id,
                    vessel_profile_code=profile.vessel_profile_code,
                    vessel_identity_id=profile.vessel_identity_id,
                    ship_name=(summary.ship_name if summary and summary.ship_name else profile.ship_name),
                    ship_name_en=profile.ship_name_en,
                    current_mmsi=(summary.current_mmsi if summary and summary.current_mmsi else profile.current_mmsi),
                    ship_type_code=ship_type_code,
                    ship_type_name=(
                        summary.ship_type_name
                        if summary and summary.ship_type_name
                        else label_map.get("SHIP_TYPE", {}).get(ship_type_code or "")
                    ),
                    profile_status_code=profile_status_code,
                    profile_status_name=label_map.get("VESSEL_PROFILE_STATUS", {}).get(profile_status_code),
                    identity_status_code=identity_status_code,
                    identity_status_name=label_map.get("VESSEL_IDENTITY_STATUS", {}).get(identity_status_code),
                    operation_status_code=operation_status_code,
                    operation_status_name=label_map.get("SHIP_OPERATION_STATUS", {}).get(operation_status_code or ""),
                    home_port_code=profile.home_port_code,
                    home_port_name=profile.home_port_name,
                    registry_city_code=profile.registry_city_code,
                    registry_city_name=profile.home_port_name,
                    business_region_id=profile.business_region_id,
                    business_region_name=None,
                    source_type_code=source_type_code,
                    source_type_name=label_map.get("SOURCE_TYPE", {}).get(source_type_code),
                    remark=profile.remark,
                    created_at=profile.created_at,
                    updated_at=profile.updated_at,
                    building_year=building_year,
                    ship_age=(summary.ship_age if summary and summary.ship_age is not None else _ship_age(building_year)),
                    deadweight_ton=deadweight_ton,
                    length_m=length_m,
                    width_m=width_m,
                    design_draft_m=design_draft_m,
                    size_text=_size_text(capacity),
                    primary_owner_name=summary.primary_owner_name if summary else None,
                    primary_operator_name=summary.primary_operator_name if summary else None,
                    primary_contact_name=summary.primary_contact_name if summary else None,
                    primary_contact_phone=summary.primary_contact_phone_masked if summary else None,
                    contact_available=summary.contact_available if summary else None,
                    longitude=_to_decimal(row.longitude),
                    latitude=_to_decimal(row.latitude),
                    speed_kn=_to_decimal(row.speed_kn),
                    course_deg=_to_decimal(row.course_deg),
                    heading_deg=_to_decimal(row.heading_deg),
                    position_time=position_time,
                    position_age_minutes=age_minutes,
                    city_code=city_code,
                    city_name=city_name,
                    current_city_code=city_code,
                    current_city_name=city_name,
                    current_city_source=(
                        CURRENT_CITY_SOURCE_ADMIN_BOUNDARY
                        if city_code
                        else CURRENT_CITY_SOURCE_INVALID_POSITION
                        if not row.valid_position_flag
                        else CURRENT_CITY_SOURCE_UNKNOWN
                    ),
                    city_center_longitude=boundary.center_longitude if boundary else None,
                    city_center_latitude=boundary.center_latitude if boundary else None,
                    matched_city_candidates=None,
                    location_text=city_name,
                    position_source_name="入库 AIS 快照",
                    source_index=row.source_index,
                    freshness_level=row.freshness_level or _ais_freshness_level(age_minutes),
                    match_status_code=row.match_status_code or "MATCHED_PROFILE",
                    risk_level=summary.risk_level if summary else None,
                    certificate_risk_available=(
                        bool(
                            (summary.certificate_missing_count or 0)
                            + (summary.certificate_expiring_count or 0)
                            + (summary.certificate_expired_count or 0)
                        )
                        if summary
                        else None
                    ),
                )
            )
        return items

    async def _position_monitor_from_latest_snapshot(
        self,
        query,
        *,
        generated_at: datetime,
        message: str,
    ) -> VesselPositionMonitorResponse | None:
        snapshot = await self._latest_persisted_ais_snapshot()
        if snapshot is None:
            return None
        max_items = int(getattr(query, "max_items", None) or 200)
        items = await self._position_items_from_persisted_snapshot(
            snapshot,
            generated_at=generated_at,
            max_rows=max(max_items * 3, max_items),
        )
        reported_within_minutes = query.reported_within_minutes or 1440
        fresh_items = [
            item for item in items
            if not self._is_stale_position(item, generated_at, reported_within_minutes)
        ][:max_items]
        return VesselPositionMonitorResponse(
            source_status="PARTIAL" if message else ("AVAILABLE" if fresh_items else "EMPTY"),
            source_status_name=_source_status_name("PARTIAL" if message else ("AVAILABLE" if fresh_items else "EMPTY")),
            generated_at=generated_at,
            message=message,
            summary=VesselPositionMonitorSummary(
                matched_profile_count=int(snapshot.matched_profile_count or len(items)),
                positioned_count=len(fresh_items),
                stale_position_count=max(0, len(items) - len(fresh_items)),
                contactable_position_count=sum(1 for item in fresh_items if item.contact_available),
                unmatched_mmsi_count=int(snapshot.unmatched_mmsi_count or 0),
                invalid_position_count=int(snapshot.invalid_position_count or 0),
                coverage_rate=_to_decimal(snapshot.coverage_rate) or self._coverage_rate(
                    int(snapshot.matched_position_count or len(items)),
                    int(snapshot.queried_mmsi_count or len(items)),
                ),
                freshness_distribution=snapshot.freshness_distribution_json or self._position_freshness_distribution(items),
            ),
            items=fresh_items,
        )

    async def _city_situation_from_latest_snapshot(
        self,
        query,
        *,
        generated_at: datetime,
        cache_backend: str,
        message: str,
        total_profile_count: int,
        scanned_profile_count: int,
        unscanned_profile_count: int,
    ) -> VesselPositionCitySituationResponse | None:
        snapshot = await self._latest_persisted_ais_snapshot()
        if snapshot is None:
            return None
        if await self._snapshot_should_be_recomputed_from_realtime(snapshot):
            logger.info(
                "ignore failed empty AIS city snapshot and recompute from realtime ES: snapshot_id=%s failed_batch_count=%s",
                snapshot.snapshot_id,
                snapshot.failed_batch_count,
            )
            return None
        items = await self._position_items_from_persisted_snapshot(snapshot, generated_at=generated_at)
        reported_within_minutes = query.reported_within_minutes or 1440
        boundaries = await self._city_boundaries()
        boundary_codes = {boundary.code for boundary in boundaries}
        boundary_paths_by_code = (
            self._city_boundary_paths_by_code(boundaries, query.boundary_precision)
            if query.include_boundary
            else {}
        )
        cities = self._city_situation_items(
            items,
            {},
            generated_at,
            reported_within_minutes,
            int(snapshot.queried_mmsi_count or len(items)),
            int(snapshot.matched_position_count or len(items)),
            max(0, int(snapshot.queried_mmsi_count or len(items)) - int(snapshot.matched_position_count or len(items))),
            int(snapshot.invalid_position_count or 0),
            int(snapshot.unknown_city_count or 0),
            True,
            message,
            boundary_paths_by_code,
            query.boundary_precision if query.include_boundary else None,
            boundary_codes,
            [],
        )
        positioned_items = [
            item for item in items
            if not self._is_stale_position(item, generated_at, reported_within_minutes)
        ]
        missing_boundary_cities = [
            {
                "city_code": city.city_code,
                "city_name": city.city_name,
                "positioned_count": city.positioned_count,
            }
            for city in cities
            if city.city_code and city.positioned_count > 0 and not city.has_boundary
        ]
        computed_unscanned_profile_count = max(
            0,
            (total_profile_count or int(snapshot.matched_profile_count or len(items)))
            - int(snapshot.scanned_profile_count or len(items)),
        )
        snapshot_partial = (
            str(snapshot.status_code or "").upper() != "READY"
            or int(snapshot.failed_batch_count or 0) > 0
            or computed_unscanned_profile_count > 0
        )
        notes = list(snapshot.uncertainty_notes_json or [])
        if "超时" in message or "失败" in message:
            notes.append("实时查询未在预算内完成，当前结果来自最近一次入库 AIS 快照。")
        if computed_unscanned_profile_count > 0:
            notes.append(f"服务端扫描上限外档案 {computed_unscanned_profile_count} 艘未参与本次实时刷新。")
        snapshot_expires_at = snapshot.expires_at
        status = "PARTIAL" if snapshot_partial and cities else ("AVAILABLE" if cities else "EMPTY")
        return VesselPositionCitySituationResponse(
            source_status=status,
            source_status_name=_source_status_name(status),
            generated_at=generated_at,
            message=message,
            cache_status="FALLBACK",
            cache_generated_at=snapshot.generated_at,
            is_stale_cache=snapshot.expires_at <= generated_at,
            snapshot_backend="db_snapshot",
            cache_backend_note=None,
            summary=VesselPositionCitySituationSummary(
                matched_profile_count=total_profile_count or int(snapshot.matched_profile_count or len(items)),
                scanned_profile_count=int(snapshot.scanned_profile_count or scanned_profile_count or len(items)),
                unscanned_profile_count=computed_unscanned_profile_count,
                queried_mmsi_count=int(snapshot.queried_mmsi_count or len(items)),
                matched_position_count=int(snapshot.matched_position_count or len(items)),
                unmatched_mmsi_count=int(snapshot.unmatched_mmsi_count or 0),
                unpositioned_count=max(0, int(snapshot.queried_mmsi_count or len(items)) - int(snapshot.matched_position_count or len(items))),
                invalid_position_count=int(snapshot.invalid_position_count or 0),
                unknown_city_count=int(snapshot.unknown_city_count or 0),
                positioned_count=len(positioned_items),
                stale_position_count=max(0, len(items) - len(positioned_items)),
                contactable_position_count=sum(1 for item in positioned_items if item.contact_available),
                certificate_risk_count=0,
                city_count=sum(1 for city in cities if city.city_code),
                boundary_city_count=sum(1 for city in cities if city.city_code and city.has_boundary),
                missing_boundary_city_count=len(missing_boundary_cities),
                missing_boundary_cities=missing_boundary_cities,
                query_snapshot_id=snapshot.snapshot_id,
                snapshot_status_code=snapshot.status_code,
                snapshot_expires_at=snapshot_expires_at,
                refresh_required=False,
                coverage_rate=_to_decimal(snapshot.coverage_rate) or self._coverage_rate(
                    int(snapshot.matched_position_count or len(items)),
                    int(snapshot.queried_mmsi_count or len(items)),
                ),
                freshness_distribution=snapshot.freshness_distribution_json or self._position_freshness_distribution(items),
                source_indices=snapshot.source_indices_json or [],
                uncertainty_notes=notes,
                failed_batch_count=int(snapshot.failed_batch_count or 0),
                failed_batches=snapshot.failed_batches_json or [],
                is_partial=snapshot_partial,
                error_message=message if snapshot_partial else None,
            ),
            cities=cities,
        )

    def _position_monitor_realtime_error_response(
        self,
        generated_at: datetime,
        message: str,
        *,
        matched_profile_count: int,
    ) -> VesselPositionMonitorResponse:
        return VesselPositionMonitorResponse(
            source_status="ERROR",
            source_status_name=_source_status_name("ERROR"),
            generated_at=generated_at,
            message=message,
            summary=VesselPositionMonitorSummary(
                matched_profile_count=matched_profile_count,
                positioned_count=0,
                stale_position_count=0,
                contactable_position_count=0,
                unmatched_mmsi_count=0,
                invalid_position_count=0,
                coverage_rate=None,
                freshness_distribution={"UNKNOWN": matched_profile_count} if matched_profile_count else {},
            ),
            items=[],
        )

    def _city_situation_realtime_error_response(
        self,
        *,
        generated_at: datetime,
        cache_backend: str,
        message: str,
        total_profile_count: int,
        scanned_profile_count: int,
        unscanned_profile_count: int,
    ) -> VesselPositionCitySituationResponse:
        notes = [message]
        if unscanned_profile_count > 0:
            notes.append(f"服务端扫描上限外档案 {unscanned_profile_count} 艘未参与本次实时刷新。")
        return VesselPositionCitySituationResponse(
            source_status="ERROR",
            source_status_name=_source_status_name("ERROR"),
            generated_at=generated_at,
            message=message,
            cache_status="MISS",
            cache_generated_at=generated_at,
            is_stale_cache=False,
            snapshot_backend=cache_backend,
            cache_backend_note="memory 仅适合本地开发；生产多实例请配置 Redis" if cache_backend == "memory" else None,
            summary=VesselPositionCitySituationSummary(
                matched_profile_count=total_profile_count,
                scanned_profile_count=scanned_profile_count,
                unscanned_profile_count=unscanned_profile_count,
                queried_mmsi_count=0,
                matched_position_count=0,
                unmatched_mmsi_count=0,
                unpositioned_count=scanned_profile_count,
                invalid_position_count=0,
                unknown_city_count=0,
                positioned_count=0,
                stale_position_count=0,
                contactable_position_count=0,
                certificate_risk_count=0,
                city_count=0,
                boundary_city_count=0,
                missing_boundary_city_count=0,
                query_snapshot_id=None,
                snapshot_status_code="FAILED",
                refresh_required=True,
                coverage_rate=None,
                freshness_distribution={"UNKNOWN": scanned_profile_count} if scanned_profile_count else {},
                uncertainty_notes=notes,
                failed_batch_count=0,
                failed_batches=[],
                is_partial=True,
                error_message=message,
            ),
            cities=[],
        )

    async def _channel_situation_from_latest_snapshot(
        self,
        query,
        *,
        generated_at: datetime,
        cache_backend: str,
        message: str,
        total_profile_count: int,
        scanned_profile_count: int,
        unscanned_profile_count: int,
        channel_type_codes: set[str],
        planning_level_codes: set[str],
    ) -> VesselPositionNavigationChannelSituationResponse | None:
        snapshot = await self._latest_persisted_ais_snapshot()
        if snapshot is None:
            return None
        if await self._snapshot_should_be_recomputed_from_realtime(snapshot):
            logger.info(
                "ignore failed empty AIS channel snapshot and recompute from realtime ES: snapshot_id=%s failed_batch_count=%s",
                snapshot.snapshot_id,
                snapshot.failed_batch_count,
            )
            return None
        items = await self._position_items_from_persisted_snapshot(snapshot, generated_at=generated_at)
        risk_by_profile = await self._compliance_risk_by_profile([item.id for item in items])
        summary_risk_by_profile = await self._summary_risk_level_by_profile([item.id for item in items])
        filtered_items = self._filter_channel_situation_items_by_risk(
            items,
            query,
            risk_by_profile,
            summary_risk_by_profile,
        )
        boundaries = await self._channel_boundaries()
        filtered_boundaries = self._filter_channel_boundaries(
            boundaries,
            getattr(query, "channel_name", None),
            channel_type_codes,
            planning_level_codes,
        )
        boundary_paths_by_code = (
            self._channel_boundary_paths_by_code(filtered_boundaries, query.boundary_precision)
            if query.include_boundary
            else {}
        )
        reported_within_minutes = query.reported_within_minutes or 1440
        queried_mmsi_count = int(snapshot.queried_mmsi_count or len(items))
        matched_position_count = int(snapshot.matched_position_count or len(items))
        invalid_position_count = int(snapshot.invalid_position_count or 0)
        unpositioned_count = max(0, queried_mmsi_count - matched_position_count)
        channels = self._channel_situation_items(
            filtered_items,
            risk_by_profile,
            summary_risk_by_profile,
            generated_at,
            reported_within_minutes,
            queried_mmsi_count,
            matched_position_count,
            unpositioned_count,
            invalid_position_count,
            True,
            message,
            filtered_boundaries,
            boundary_paths_by_code,
            query.boundary_precision if query.include_boundary else None,
            bool(getattr(query, "include_empty_channels", True)),
        )
        positioned_items = [
            item for item in filtered_items
            if not self._is_stale_position(item, generated_at, reported_within_minutes)
        ]
        computed_unscanned_profile_count = max(
            0,
            (total_profile_count or int(snapshot.matched_profile_count or len(items)))
            - int(snapshot.scanned_profile_count or scanned_profile_count or len(items)),
        )
        snapshot_partial = (
            str(snapshot.status_code or "").upper() != "READY"
            or int(snapshot.failed_batch_count or 0) > 0
            or computed_unscanned_profile_count > 0
        )
        notes = list(snapshot.uncertainty_notes_json or [])
        if "超时" in message or "失败" in message:
            notes.append("实时查询未在预算内完成，当前航道态势由最近一次入库 AIS 快照反算。")
        if computed_unscanned_profile_count > 0:
            notes.append(f"服务端扫描上限外档案 {computed_unscanned_profile_count} 艘未参与本次实时刷新。")
        snapshot_expires_at = snapshot.expires_at
        status = "PARTIAL" if snapshot_partial and channels else ("AVAILABLE" if channels else "EMPTY")
        return VesselPositionNavigationChannelSituationResponse(
            source_status=status,
            source_status_name=_source_status_name(status),
            generated_at=generated_at,
            message=message,
            cache_status="FALLBACK",
            cache_generated_at=snapshot.generated_at,
            is_stale_cache=snapshot.expires_at <= generated_at,
            snapshot_backend="db_snapshot",
            cache_backend_note=None,
            summary=VesselPositionNavigationChannelSituationSummary(
                matched_profile_count=total_profile_count or int(snapshot.matched_profile_count or len(items)),
                scanned_profile_count=int(snapshot.scanned_profile_count or scanned_profile_count or len(items)),
                unscanned_profile_count=computed_unscanned_profile_count,
                queried_mmsi_count=queried_mmsi_count,
                matched_position_count=matched_position_count,
                unmatched_mmsi_count=int(snapshot.unmatched_mmsi_count or 0),
                unpositioned_count=unpositioned_count,
                invalid_position_count=invalid_position_count,
                unknown_channel_count=sum(item.positioned_count for item in channels if not item.channel_code),
                positioned_count=len(positioned_items),
                stale_position_count=max(0, len(filtered_items) - len(positioned_items)),
                contactable_position_count=sum(1 for item in positioned_items if item.contact_available),
                certificate_risk_count=sum(1 for item in positioned_items if risk_by_profile.get(item.id, {}).get("has_certificate_risk")),
                high_risk_count=sum(1 for item in positioned_items if summary_risk_by_profile.get(item.id) == "HIGH"),
                channel_count=sum(1 for item in channels if item.channel_code),
                boundary_channel_count=sum(1 for item in channels if item.channel_code and item.has_boundary),
                missing_boundary_channel_count=sum(1 for item in channels if item.channel_code and not item.has_boundary),
                query_snapshot_id=snapshot.snapshot_id,
                snapshot_status_code=snapshot.status_code,
                snapshot_expires_at=snapshot_expires_at,
                refresh_required=False,
                coverage_rate=_to_decimal(snapshot.coverage_rate) or self._coverage_rate(matched_position_count, queried_mmsi_count),
                freshness_distribution=snapshot.freshness_distribution_json or self._position_freshness_distribution(filtered_items),
                source_indices=snapshot.source_indices_json or [],
                uncertainty_notes=notes,
                failed_batch_count=int(snapshot.failed_batch_count or 0),
                failed_batches=snapshot.failed_batches_json or [],
                is_partial=snapshot_partial,
                error_message=message if snapshot_partial else None,
            ),
            channels=channels,
        )

    async def _channel_situation_from_precomputed_items(
        self,
        query,
        items: list[VesselPositionMonitorItemResponse],
        snapshot_payload: dict[str, Any],
        *,
        generated_at: datetime,
        cache_backend: str,
        message: str,
        channel_type_codes: set[str],
        planning_level_codes: set[str],
    ) -> VesselPositionNavigationChannelSituationResponse | None:
        snapshot_id = str(snapshot_payload.get("snapshot_id") or self._FULL_AIS_SNAPSHOT_ID)
        snapshot = await self._latest_persisted_ais_snapshot(snapshot_id=snapshot_id)
        if snapshot is None:
            return None
        risk_by_profile = await self._compliance_risk_by_profile([item.id for item in items])
        summary_risk_by_profile = await self._summary_risk_level_by_profile([item.id for item in items])
        filtered_items = self._filter_channel_situation_items_by_risk(
            items,
            query,
            risk_by_profile,
            summary_risk_by_profile,
        )
        boundaries = await self._channel_boundaries()
        filtered_boundaries = self._filter_channel_boundaries(
            boundaries,
            getattr(query, "channel_name", None),
            channel_type_codes,
            planning_level_codes,
        )
        boundary_paths_by_code = (
            self._channel_boundary_paths_by_code(filtered_boundaries, query.boundary_precision)
            if query.include_boundary
            else {}
        )
        reported_within_minutes = query.reported_within_minutes or 1440
        queried_mmsi_count = int(snapshot.queried_mmsi_count or snapshot_payload.get("queried_mmsi_count") or len(items))
        matched_position_count = int(snapshot.matched_position_count or snapshot_payload.get("matched_position_count") or len(items))
        invalid_position_count = int(snapshot.invalid_position_count or snapshot_payload.get("invalid_position_count") or 0)
        unpositioned_count = max(0, queried_mmsi_count - matched_position_count)
        channels = self._channel_situation_items(
            filtered_items,
            risk_by_profile,
            summary_risk_by_profile,
            generated_at,
            reported_within_minutes,
            queried_mmsi_count,
            matched_position_count,
            unpositioned_count,
            invalid_position_count,
            True,
            message,
            filtered_boundaries,
            boundary_paths_by_code,
            query.boundary_precision if query.include_boundary else None,
            bool(getattr(query, "include_empty_channels", True)),
        )
        positioned_items = [
            item for item in filtered_items
            if not self._is_stale_position(item, generated_at, reported_within_minutes)
        ]
        total_profile_count = int(snapshot_payload.get("total_profile_count") or snapshot.matched_profile_count or len(items))
        scanned_profile_count = int(snapshot.scanned_profile_count or snapshot_payload.get("scanned_profile_count") or len(items))
        computed_unscanned_profile_count = max(0, total_profile_count - scanned_profile_count)
        snapshot_partial = (
            str(snapshot.status_code or "").upper() != "READY"
            or int(snapshot.failed_batch_count or 0) > 0
            or computed_unscanned_profile_count > 0
        )
        notes = list(snapshot.uncertainty_notes_json or [])
        if computed_unscanned_profile_count > 0:
            notes.append(f"服务端扫描上限外档案 {computed_unscanned_profile_count} 艘未参与本次实时刷新。")
        status = "PARTIAL" if snapshot_partial and channels else ("AVAILABLE" if channels else "EMPTY")
        response = VesselPositionNavigationChannelSituationResponse(
            source_status=status,
            source_status_name=_source_status_name(status),
            generated_at=generated_at,
            message=message,
            cache_status="FALLBACK",
            cache_generated_at=snapshot.generated_at,
            is_stale_cache=snapshot.expires_at <= generated_at,
            snapshot_backend="db_snapshot",
            cache_backend_note=None,
            summary=VesselPositionNavigationChannelSituationSummary(
                matched_profile_count=total_profile_count,
                scanned_profile_count=scanned_profile_count,
                unscanned_profile_count=computed_unscanned_profile_count,
                queried_mmsi_count=queried_mmsi_count,
                matched_position_count=matched_position_count,
                unmatched_mmsi_count=int(snapshot.unmatched_mmsi_count or 0),
                unpositioned_count=unpositioned_count,
                invalid_position_count=invalid_position_count,
                unknown_channel_count=sum(item.positioned_count for item in channels if not item.channel_code),
                positioned_count=len(positioned_items),
                stale_position_count=max(0, len(filtered_items) - len(positioned_items)),
                contactable_position_count=sum(1 for item in positioned_items if item.contact_available),
                certificate_risk_count=sum(1 for item in positioned_items if risk_by_profile.get(item.id, {}).get("has_certificate_risk")),
                high_risk_count=sum(1 for item in positioned_items if summary_risk_by_profile.get(item.id) == "HIGH"),
                channel_count=sum(1 for item in channels if item.channel_code),
                boundary_channel_count=sum(1 for item in channels if item.channel_code and item.has_boundary),
                missing_boundary_channel_count=sum(1 for item in channels if item.channel_code and not item.has_boundary),
                query_snapshot_id=snapshot.snapshot_id,
                snapshot_status_code=snapshot.status_code,
                snapshot_expires_at=snapshot.expires_at,
                refresh_required=False,
                coverage_rate=_to_decimal(snapshot.coverage_rate) or self._coverage_rate(matched_position_count, queried_mmsi_count),
                freshness_distribution=snapshot.freshness_distribution_json or self._position_freshness_distribution(filtered_items),
                source_indices=snapshot.source_indices_json or [],
                uncertainty_notes=notes,
                failed_batch_count=int(snapshot.failed_batch_count or 0),
                failed_batches=snapshot.failed_batches_json or [],
                is_partial=snapshot_partial,
                error_message=message if snapshot_partial else None,
            ),
            channels=channels,
        )
        await self._store_channel_situation_response_cache(_channel_situation_query_cache_key(query), response)
        return response

    async def _channel_situation_realtime_error_response(
        self,
        query,
        *,
        generated_at: datetime,
        cache_backend: str,
        message: str,
        total_profile_count: int,
        scanned_profile_count: int,
        unscanned_profile_count: int,
        channel_type_codes: set[str],
        planning_level_codes: set[str],
    ) -> VesselPositionNavigationChannelSituationResponse:
        channels: list[VesselPositionNavigationChannelSituationItemResponse] = []
        if bool(getattr(query, "include_empty_channels", True)):
            try:
                filtered_boundaries = self._filter_channel_boundaries(
                    await self._channel_boundaries(),
                    getattr(query, "channel_name", None),
                    channel_type_codes,
                    planning_level_codes,
                )
                channels = self._channel_situation_items(
                    [],
                    {},
                    {},
                    generated_at,
                    query.reported_within_minutes or 1440,
                    0,
                    0,
                    scanned_profile_count,
                    0,
                    True,
                    message,
                    filtered_boundaries,
                    {},
                    None,
                    True,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("build empty channel situation after realtime AIS failure failed: %s", exc)
        notes = [message]
        if unscanned_profile_count > 0:
            notes.append(f"服务端扫描上限外档案 {unscanned_profile_count} 艘未参与本次实时刷新。")
        return VesselPositionNavigationChannelSituationResponse(
            source_status="ERROR",
            source_status_name=_source_status_name("ERROR"),
            generated_at=generated_at,
            message=message,
            cache_status="MISS",
            cache_generated_at=generated_at,
            is_stale_cache=False,
            snapshot_backend=cache_backend,
            cache_backend_note="memory 仅适合本地开发；生产多实例请配置 Redis" if cache_backend == "memory" else None,
            summary=VesselPositionNavigationChannelSituationSummary(
                matched_profile_count=total_profile_count,
                scanned_profile_count=scanned_profile_count,
                unscanned_profile_count=unscanned_profile_count,
                queried_mmsi_count=0,
                matched_position_count=0,
                unmatched_mmsi_count=0,
                unpositioned_count=scanned_profile_count,
                invalid_position_count=0,
                unknown_channel_count=0,
                positioned_count=0,
                stale_position_count=0,
                contactable_position_count=0,
                certificate_risk_count=0,
                high_risk_count=0,
                channel_count=sum(1 for item in channels if item.channel_code),
                boundary_channel_count=sum(1 for item in channels if item.channel_code and item.has_boundary),
                missing_boundary_channel_count=sum(1 for item in channels if item.channel_code and not item.has_boundary),
                query_snapshot_id=None,
                snapshot_status_code="FAILED",
                refresh_required=True,
                coverage_rate=None,
                freshness_distribution={"UNKNOWN": scanned_profile_count} if scanned_profile_count else {},
                uncertainty_notes=notes,
                failed_batch_count=0,
                failed_batches=[],
                is_partial=True,
                error_message=message,
            ),
            channels=channels,
        )
