"""Profile selection, merge helpers, and snapshot precompute persistence."""

from __future__ import annotations

from app.modules.vessel.ais.common import *


class VesselAisProfileQueryMixin:
    def _position_monitor_profile_base_stmt(self, query):
        stmt = select(VesselProfile).where(VesselProfile.deleted_at.is_(None))
        joined_capacity = False
        joined_contact = False
        joined_owner = False
        joined_operator = False

        def join_capacity():
            nonlocal stmt, joined_capacity
            if not joined_capacity:
                stmt = stmt.outerjoin(VesselCapacityDimension, VesselCapacityDimension.vessel_profile_id == VesselProfile.id)
                joined_capacity = True

        def join_contact():
            nonlocal stmt, joined_contact
            if not joined_contact:
                stmt = stmt.outerjoin(VesselContact, VesselContact.vessel_profile_id == VesselProfile.id)
                joined_contact = True

        def join_owner():
            nonlocal stmt, joined_owner
            if not joined_owner:
                stmt = stmt.outerjoin(
                    VesselOwnerPeriod,
                    and_(VesselOwnerPeriod.vessel_profile_id == VesselProfile.id, VesselOwnerPeriod.is_current.is_(True)),
                )
                joined_owner = True

        def join_operator():
            nonlocal stmt, joined_operator
            if not joined_operator:
                stmt = stmt.outerjoin(
                    VesselOperatorPeriod,
                    and_(VesselOperatorPeriod.vessel_profile_id == VesselProfile.id, VesselOperatorPeriod.is_current.is_(True)),
                )
                joined_operator = True

        if query.keyword:
            join_contact()
            join_owner()
            join_operator()
            like_value = f"%{query.keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    VesselProfile.vessel_profile_code.ilike(like_value),
                    VesselProfile.ship_name.ilike(like_value),
                    VesselProfile.current_mmsi.ilike(like_value),
                    VesselOwnerPeriod.party_name.ilike(like_value),
                    VesselOperatorPeriod.operator_name.ilike(like_value),
                    VesselContact.contact_name.ilike(like_value),
                    VesselContact.mobile_phone.ilike(like_value),
                )
            )
        if query.ship_type_code:
            stmt = stmt.where(VesselProfile.ship_type_code == query.ship_type_code)
        if query.profile_status_code:
            stmt = stmt.where(VesselProfile.profile_status_code == query.profile_status_code)
        else:
            stmt = stmt.where(~VesselProfile.profile_status_code.in_(["INACTIVE", "TRANSFERRED", "ARCHIVED", "DECOMMISSIONED"]))
        if query.deadweight_min is not None:
            join_capacity()
            stmt = stmt.where(VesselCapacityDimension.deadweight_ton >= query.deadweight_min)
        if query.deadweight_max is not None:
            join_capacity()
            stmt = stmt.where(VesselCapacityDimension.deadweight_ton <= query.deadweight_max)
        if query.draft_max is not None:
            join_capacity()
            stmt = stmt.where(VesselCapacityDimension.design_draft_m <= query.draft_max)
        if query.contact_available is not None:
            join_contact()
            stmt = stmt.where(VesselContact.is_available.is_(query.contact_available))
        return stmt

    async def _position_monitor_profile_count(self, query) -> int:
        subquery = self._position_monitor_profile_base_stmt(query).with_only_columns(VesselProfile.id).group_by(VesselProfile.id).subquery()
        return int((await self.db.execute(select(func.count()).select_from(subquery))).scalar_one() or 0)

    async def _position_monitor_profiles(self, query, *, limit: int | None = None) -> list[VesselProfile]:
        stmt = self._position_monitor_profile_base_stmt(query)
        stmt = stmt.group_by(VesselProfile.id).order_by(VesselProfile.updated_at.desc(), VesselProfile.id.desc())
        if limit is not None:
            stmt = stmt.limit(limit)
        elif hasattr(query, "max_items"):
            stmt = stmt.limit(max(query.max_items * 3, query.max_items))
        rows = (await self.db.execute(stmt)).scalars().all()
        return list(rows)

    async def _position_monitor_profiles_page(self, query, *, offset: int, limit: int) -> list[VesselProfile]:
        stmt = self._position_monitor_profile_base_stmt(query)
        stmt = (
            stmt.group_by(VesselProfile.id)
            .order_by(VesselProfile.updated_at.desc(), VesselProfile.id.desc())
            .offset(max(0, offset))
            .limit(max(1, limit))
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return list(rows)

    def _merge_position_build_results(self, results: list[_PositionBuildResult]) -> _PositionBuildResult:
        items: list[VesselPositionMonitorItemResponse] = []
        unmatched_positions: list[dict[str, Any]] = []
        invalid_positions: list[dict[str, Any]] = []
        failed_batches: list[dict[str, Any]] = []
        errors: list[str] = []
        source_indices: set[str] = set()
        queried_mmsi_count = 0
        matched_position_count = 0
        unpositioned_count = 0
        invalid_position_count = 0
        unknown_city_count = 0
        failed_batch_count = 0
        partial = False
        for result in results:
            items.extend(result.items)
            unmatched_positions.extend(result.unmatched_positions)
            invalid_positions.extend(result.invalid_positions)
            failed_batches.extend(result.failed_batches)
            queried_mmsi_count += int(result.queried_mmsi_count or 0)
            matched_position_count += int(result.matched_position_count or 0)
            unpositioned_count += int(result.unpositioned_count or 0)
            invalid_position_count += int(result.invalid_position_count or 0)
            unknown_city_count += int(result.unknown_city_count or 0)
            failed_batch_count += int(result.failed_batch_count or 0)
            partial = partial or bool(result.partial)
            if result.error_message:
                errors.append(result.error_message)
            source_indices.update(result.source_indices or [])
        unique_errors = list(dict.fromkeys(errors))
        return _PositionBuildResult(
            items=items,
            partial=partial,
            error_message="；".join(unique_errors[:3]) if unique_errors else None,
            failed_batch_count=failed_batch_count,
            queried_mmsi_count=queried_mmsi_count,
            matched_position_count=matched_position_count,
            unpositioned_count=unpositioned_count,
            invalid_position_count=invalid_position_count,
            unknown_city_count=unknown_city_count,
            unmatched_positions=unmatched_positions,
            invalid_positions=invalid_positions,
            source_indices=sorted(source_indices),
            failed_batches=failed_batches,
        )

    async def precompute_full_ais_position_snapshot(self, query, *, snapshot_id: str | None = None) -> dict[str, Any]:
        generated_at = datetime.utcnow()
        limits = await self._ais_runtime_limits()
        page_size = _safe_int(
            int(settings.VESSEL_AIS_PRECOMPUTE_PROFILE_PAGE_SIZE or 5000),
            5000,
            minimum=500,
            maximum=10000,
        )
        max_profiles = max(0, int(settings.VESSEL_AIS_PRECOMPUTE_MAX_PROFILES or 0))
        total_profile_count = await self._position_monitor_profile_count(query)
        target_profile_count = min(total_profile_count, max_profiles) if max_profiles else total_profile_count
        results: list[_PositionBuildResult] = []
        scanned_profile_count = 0
        offset = 0
        while scanned_profile_count < target_profile_count:
            limit = min(page_size, target_profile_count - scanned_profile_count)
            profiles = await self._position_monitor_profiles_page(query, offset=offset, limit=limit)
            if not profiles:
                break
            result = await self._position_monitor_items_for_profiles(
                profiles,
                generated_at=generated_at,
                reported_within_minutes=query.reported_within_minutes or 1440,
                es_batch_size=limits["es_batch_size"],
                es_max_concurrency=limits["es_max_concurrency"],
                include_stale=True,
                include_unmatched=False,
                unmatched_scan_limit=0,
                resolve_city=True,
                resolve_channel=True,
            )
            results.append(result)
            scanned_profile_count += len(profiles)
            offset += len(profiles)
        merged = self._merge_position_build_results(results)
        unscanned_profile_count = max(0, total_profile_count - scanned_profile_count)
        if unscanned_profile_count > 0:
            merged.partial = True
            note = f"后台全量预计算达到扫描上限，未扫描档案 {unscanned_profile_count} 艘"
            merged.error_message = "；".join(part for part in [merged.error_message, note] if part)
        snapshot_id = snapshot_id or self._FULL_AIS_SNAPSHOT_ID
        await self._persist_ais_position_snapshot(
            snapshot_id,
            query,
            merged,
            generated_at=generated_at,
            total_profile_count=total_profile_count,
            scanned_profile_count=scanned_profile_count,
            unscanned_profile_count=unscanned_profile_count,
        )
        await self._clear_ais_situation_response_caches()
        self._last_full_ais_position_items = merged.items
        self._last_full_ais_position_generated_at = generated_at
        return {
            "snapshot_id": snapshot_id,
            "generated_at": generated_at.isoformat(),
            "total_profile_count": total_profile_count,
            "scanned_profile_count": scanned_profile_count,
            "unscanned_profile_count": unscanned_profile_count,
            "queried_mmsi_count": merged.queried_mmsi_count,
            "matched_position_count": merged.matched_position_count,
            "failed_batch_count": merged.failed_batch_count,
            "is_partial": merged.partial,
            "source_indices": merged.source_indices,
        }

    async def _persist_ais_position_snapshot(
        self,
        snapshot_id: str,
        query,
        result: _PositionBuildResult,
        *,
        generated_at: datetime,
        total_profile_count: int,
        scanned_profile_count: int,
        unscanned_profile_count: int,
    ) -> None:
        query_params = query.model_dump(mode="json") if hasattr(query, "model_dump") else dict(getattr(query, "__dict__", {}))
        query_params["scan_mode"] = "FULL_PROFILE_PRECOMPUTE"
        query_params["snapshot_id"] = snapshot_id
        query_hash = hashlib.sha256(json.dumps(query_params, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        status_code = "PARTIAL" if result.partial or unscanned_profile_count > 0 else "READY"
        freshness_distribution = self._position_freshness_distribution(result.items, result.unmatched_positions)
        coverage_rate = self._coverage_rate(result.matched_position_count, result.queried_mmsi_count)
        notes: list[str] = [
            f"后台任务已按生产船舶档案全量扫描 {scanned_profile_count} 艘。",
        ]
        if result.source_indices:
            notes.append(f"实时 ES 来源索引：{', '.join(result.source_indices[:5])}")
        if unscanned_profile_count > 0:
            notes.append(f"后台扫描上限外档案 {unscanned_profile_count} 艘未参与本次快照。")
        if result.partial and result.error_message:
            notes.append(result.error_message)
        snapshot = await self.db.scalar(select(VesselAisSnapshot).where(VesselAisSnapshot.snapshot_id == snapshot_id))
        now = datetime.utcnow()
        snapshot_values = {
            "query_hash": query_hash,
            "query_params_json": query_params,
            "status_code": status_code,
            "generated_at": generated_at,
            "expires_at": generated_at + timedelta(seconds=_city_snapshot_ttl()),
            "cache_backend_code": "db_snapshot",
            "scanned_profile_count": scanned_profile_count,
            "queried_mmsi_count": result.queried_mmsi_count,
            "matched_profile_count": total_profile_count,
            "matched_position_count": result.matched_position_count,
            "unmatched_mmsi_count": len([item for item in result.unmatched_positions if item.get("match_status_code") == "UNMATCHED_MMSI"]),
            "invalid_position_count": len(result.invalid_positions),
            "unknown_city_count": result.unknown_city_count,
            "failed_batch_count": result.failed_batch_count,
            "failed_batches_json": result.failed_batches,
            "coverage_rate": coverage_rate,
            "freshness_distribution_json": freshness_distribution,
            "source_indices_json": result.source_indices,
            "uncertainty_notes_json": notes,
            "refresh_error": result.error_message,
            "updated_at": now,
        }
        if snapshot is None:
            snapshot = VesselAisSnapshot(
                snapshot_id=snapshot_id,
                created_at=now,
                **snapshot_values,
            )
            self.db.add(snapshot)
            await self.db.flush()
        else:
            for key, value in snapshot_values.items():
                setattr(snapshot, key, value)
        await self.db.execute(delete(VesselLatestPositionSnapshot).where(VesselLatestPositionSnapshot.snapshot_id == snapshot_id))
        await self.db.execute(delete(VesselAisCitySnapshotItem).where(VesselAisCitySnapshotItem.snapshot_id == snapshot_id))
        boundaries = await self._city_boundaries()
        boundary_codes = {boundary.code for boundary in boundaries}
        city_items = self._city_situation_items(
            result.items,
            {},
            generated_at,
            query.reported_within_minutes or 1440,
            result.queried_mmsi_count,
            result.matched_position_count,
            result.unpositioned_count,
            result.invalid_position_count,
            result.unknown_city_count,
            result.partial,
            result.error_message,
            {},
            None,
            boundary_codes,
            result.unmatched_positions,
        )
        for city in city_items:
            self.db.add(
                VesselAisCitySnapshotItem(
                    snapshot_id=snapshot_id,
                    city_code=city.city_code,
                    city_name=city.city_name,
                    positioned_count=city.positioned_count,
                    matched_position_count=city.matched_position_count,
                    unmatched_mmsi_count=city.unmatched_mmsi_count,
                    invalid_position_count=city.invalid_position_count,
                    stale_position_count=city.stale_position_count,
                    freshness_distribution_json=city.freshness_distribution,
                    boundary_status_code=city.boundary_status_code,
                    has_boundary=city.has_boundary,
                    boundary_precision=city.boundary_precision,
                    latest_position_time=city.latest_position_time,
                    created_at=now,
                )
            )
        for item in result.items:
            self.db.add(
                VesselLatestPositionSnapshot(
                    snapshot_id=snapshot_id,
                    vessel_profile_id=item.id,
                    mmsi=str(item.current_mmsi or ""),
                    longitude=item.longitude,
                    latitude=item.latitude,
                    speed_kn=item.speed_kn,
                    course_deg=item.course_deg,
                    heading_deg=item.heading_deg,
                    position_time=item.position_time,
                    source_index=item.source_index,
                    freshness_level=item.freshness_level or "UNKNOWN",
                    match_status_code=item.match_status_code or "MATCHED_PROFILE",
                    city_code=item.current_city_code or item.city_code,
                    city_name=item.current_city_name or item.city_name,
                    valid_position_flag=True,
                    created_at=now,
                )
            )
        await self.db.commit()
