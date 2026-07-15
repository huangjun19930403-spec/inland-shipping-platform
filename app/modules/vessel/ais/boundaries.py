"""City and navigation-channel boundary loading, matching, and drilldown snapshots."""

from __future__ import annotations

from app.modules.vessel.ais.common import *


class VesselAisBoundaryMixin:
    async def _city_boundaries(self) -> list[_CityBoundary]:
        now = datetime.utcnow()
        loaded_at = _CITY_BOUNDARY_CACHE.get("loaded_at")
        if loaded_at and (now - loaded_at).total_seconds() < CITY_BOUNDARY_CACHE_TTL_SECONDS:
            return list(_CITY_BOUNDARY_CACHE.get("boundaries") or [])

        rows = (
            await self.db.execute(
                select(AdminRegionBoundary, AdminRegion)
                .join(AdminRegion, AdminRegion.id == AdminRegionBoundary.admin_region_id)
                .where(
                    AdminRegionBoundary.is_current.is_(True),
                    AdminRegion.level == 2,
                    AdminRegion.status == 1,
                )
            )
        ).all()
        boundaries: list[_CityBoundary] = []
        for boundary, region in rows:
            polygons = _extract_geojson_polygons(normalize_boundary_geometry(boundary.geometry_json))
            if not polygons:
                continue
            bbox = _polygons_bbox(polygons)
            if bbox is None:
                continue
            min_x, min_y, max_x, max_y = bbox
            boundary_paths_by_precision = {
                precision: _boundary_paths_for_precision(polygons, precision)
                for precision in CITY_BOUNDARY_SIMPLIFY_TOLERANCE
            }
            boundaries.append(
                _CityBoundary(
                    code=region.code,
                    name=region.name,
                    center_longitude=_to_decimal(boundary.center_longitude if boundary.center_longitude is not None else region.longitude),
                    center_latitude=_to_decimal(boundary.center_latitude if boundary.center_latitude is not None else region.latitude),
                    area_km2=_to_decimal(boundary.area_km2),
                    bbox=bbox,
                    bbox_area=max(0.0, (max_x - min_x) * (max_y - min_y)),
                    polygons=polygons,
                    boundary_paths_by_precision=boundary_paths_by_precision,
                )
            )
        _CITY_BOUNDARY_CACHE["loaded_at"] = now
        _CITY_BOUNDARY_CACHE["boundaries"] = boundaries
        _CITY_BOUNDARY_CACHE["grid_index"] = _build_city_boundary_grid(boundaries)
        return boundaries

    def _city_boundary_paths_by_code(
        self,
        boundaries: list[_CityBoundary],
        precision: str,
    ) -> dict[str, list[list[tuple[float, float]]]]:
        result: dict[str, list[list[tuple[float, float]]]] = {}
        for boundary in boundaries:
            paths = (boundary.boundary_paths_by_precision or {}).get(precision)
            if paths is None:
                paths = _boundary_paths_for_precision(boundary.polygons, precision)
            if paths:
                result[boundary.code] = paths
        return result

    def _city_boundary_version_id(self) -> int | None:
        loaded_at = _CITY_BOUNDARY_CACHE.get("loaded_at")
        return int(loaded_at.timestamp()) if isinstance(loaded_at, datetime) else None

    async def _channel_boundaries(self) -> list[_NavigationChannelBoundary]:
        now = datetime.utcnow()
        loaded_at = _CHANNEL_BOUNDARY_CACHE.get("loaded_at")
        if loaded_at and (now - loaded_at).total_seconds() < CHANNEL_BOUNDARY_CACHE_TTL_SECONDS:
            return list(_CHANNEL_BOUNDARY_CACHE.get("boundaries") or [])

        rows = (
            await self.db.execute(
                select(NavigationChannelBoundary, NavigationChannel)
                .join(NavigationChannel, NavigationChannel.id == NavigationChannelBoundary.channel_id)
                .where(
                    NavigationChannelBoundary.is_current.is_(True),
                    NavigationChannelBoundary.geometry_status_code == "AVAILABLE",
                    NavigationChannel.is_enabled.is_(True),
                    NavigationChannel.ais_scope_code == "INCLUDED",
                )
            )
        ).all()
        boundaries: list[_NavigationChannelBoundary] = []
        for boundary, channel in rows:
            polygons = _extract_geojson_polygons(normalize_boundary_geometry(boundary.geometry_json))
            if not polygons:
                continue
            bbox = _polygons_bbox(polygons)
            if bbox is None:
                continue
            min_x, min_y, max_x, max_y = bbox
            boundary_paths_by_precision = {
                "low": self._paths_from_stored_boundary(boundary.boundary_paths_low),
                "medium": self._paths_from_stored_boundary(boundary.boundary_paths_medium),
                "high": self._paths_from_stored_boundary(boundary.boundary_paths_high),
            }
            boundaries.append(
                _NavigationChannelBoundary(
                    code=channel.channel_code,
                    name=channel.channel_name,
                    parent_channel_code=channel.parent_channel_code,
                    channel_type_code=channel.channel_type_code,
                    planning_level_code=channel.planning_level_code,
                    ais_scope_code=channel.ais_scope_code,
                    center_longitude=_to_decimal(boundary.center_longitude),
                    center_latitude=_to_decimal(boundary.center_latitude),
                    display_center_longitude=_to_decimal(boundary.display_center_longitude),
                    display_center_latitude=_to_decimal(boundary.display_center_latitude),
                    boundary_quality_code=boundary.boundary_quality_code,
                    connectivity_status_code=boundary.connectivity_status_code,
                    repair_status_code=boundary.repair_status_code,
                    geometry_coordinate_system_code=boundary.geometry_coordinate_system_code,
                    boundary_coordinate_system_code=boundary.boundary_coordinate_system_code,
                    shape_area_degree=_to_decimal(boundary.source_shape_area_degree),
                    display_priority=channel.display_priority,
                    bbox=bbox,
                    bbox_area=max(0.0, (max_x - min_x) * (max_y - min_y)),
                    polygons=polygons,
                    boundary_paths_by_precision=boundary_paths_by_precision,
                )
            )
        _CHANNEL_BOUNDARY_CACHE["loaded_at"] = now
        _CHANNEL_BOUNDARY_CACHE["boundaries"] = boundaries
        _CHANNEL_BOUNDARY_CACHE["grid_index"] = _build_channel_boundary_grid(boundaries)
        return boundaries

    def _paths_from_stored_boundary(self, value: Any) -> list[list[tuple[float, float]]]:
        result: list[list[tuple[float, float]]] = []
        if not isinstance(value, list):
            return result
        for raw_ring in value:
            ring: list[tuple[float, float]] = []
            if not isinstance(raw_ring, list):
                continue
            for raw_point in raw_ring:
                if not isinstance(raw_point, (list, tuple)) or len(raw_point) < 2:
                    continue
                try:
                    ring.append((float(raw_point[0]), float(raw_point[1])))
                except (TypeError, ValueError):
                    continue
            if len(ring) >= 4:
                result.append(ring)
        return result

    def _channel_boundary_paths_by_code(
        self,
        boundaries: list[_NavigationChannelBoundary],
        precision: str,
    ) -> dict[str, list[list[tuple[float, float]]]]:
        result: dict[str, list[list[tuple[float, float]]]] = {}
        for boundary in boundaries:
            paths = self._channel_boundary_paths_for_precision(boundary, precision)
            if paths:
                result[boundary.code] = paths
        return result

    def _channel_boundary_paths_for_precision(
        self,
        boundary: _NavigationChannelBoundary,
        precision: str,
    ) -> list[list[tuple[float, float]]]:
        return (
            (boundary.boundary_paths_by_precision or {}).get(precision)
            or _boundary_paths_for_precision(boundary.polygons, precision)
        )

    def _channel_boundary_version_id(self) -> int | None:
        loaded_at = _CHANNEL_BOUNDARY_CACHE.get("loaded_at")
        return int(loaded_at.timestamp()) if isinstance(loaded_at, datetime) else None

    async def _discard_city_situation_snapshot(self, snapshot_id: str) -> None:
        _CITY_SITUATION_SNAPSHOTS.pop(snapshot_id, None)
        if _city_cache_backend_setting() != "redis" or Redis is None:
            return
        try:
            redis_client = await self._city_redis()
            if redis_client is not None:
                await redis_client.delete(CITY_SITUATION_SNAPSHOT_KEY_PREFIX + snapshot_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("city situation redis snapshot discard failed: %s", exc)

    def _resolve_current_city_from_boundaries(
        self,
        longitude: Decimal | None,
        latitude: Decimal | None,
        boundaries: list[_CityBoundary],
        grid_index: dict[tuple[int, int], list[_CityBoundary]] | None = None,
    ) -> _ResolvedCity:
        if not self._valid_longitude_latitude(longitude, latitude):
            return _ResolvedCity(None, UNKNOWN_CITY_NAME, CURRENT_CITY_SOURCE_INVALID_POSITION)
        lon = float(longitude)
        lat = float(latitude)
        candidates = grid_index.get(_grid_key(lon, lat), boundaries) if grid_index else boundaries
        matches = [
            boundary for boundary in candidates
            if _bbox_contains(boundary.bbox, lon, lat)
            and any(_point_in_polygon_with_holes(lon, lat, polygon) for polygon in boundary.polygons)
        ]
        if not matches:
            return _ResolvedCity(None, UNKNOWN_CITY_NAME, CURRENT_CITY_SOURCE_UNKNOWN)
        matches.sort(key=lambda item: (item.area_km2 if item.area_km2 is not None else Decimal("999999999"), Decimal(str(item.bbox_area))))
        selected = matches[0]
        candidates: list[dict[str, Any]] | None = None
        if len(matches) > 1:
            candidates = [
                {
                    "city_code": item.code,
                    "city_name": item.name,
                    "area_km2": str(item.area_km2) if item.area_km2 is not None else None,
                    "bbox_area": item.bbox_area,
                }
                for item in matches
            ]
            logger.warning(
                "vessel position matched multiple city boundaries: longitude=%s latitude=%s candidates=%s selected=%s",
                longitude,
                latitude,
                candidates,
                selected.code,
            )
        return _ResolvedCity(
            selected.code,
            selected.name,
            CURRENT_CITY_SOURCE_ADMIN_BOUNDARY,
            selected.center_longitude,
            selected.center_latitude,
            candidates,
        )

    def _resolve_current_channels_from_boundaries(
        self,
        longitude: Decimal | None,
        latitude: Decimal | None,
        boundaries: list[_NavigationChannelBoundary],
        grid_index: dict[tuple[int, int], list[_NavigationChannelBoundary]] | None = None,
        allowed_codes: set[str] | None = None,
        allow_near_match: bool = True,
    ) -> list[_ResolvedNavigationChannel]:
        if not self._valid_longitude_latitude(longitude, latitude):
            return []
        lon = float(longitude)
        lat = float(latitude)
        if grid_index:
            if allowed_codes is None:
                allowed_codes = {boundary.code for boundary in boundaries}
            candidates = [
                boundary for boundary in grid_index.get(_channel_grid_key(lon, lat), [])
                if boundary.code in allowed_codes
            ]
        else:
            candidates = boundaries
        matches = [
            boundary for boundary in candidates
            if _bbox_contains(boundary.bbox, lon, lat)
            and any(_point_in_polygon_with_holes(lon, lat, polygon) for polygon in boundary.polygons)
        ]
        if not matches:
            if not allow_near_match:
                return []
            near_matches: list[tuple[_NavigationChannelBoundary, Decimal]] = []
            near_candidates = boundaries
            if grid_index:
                candidates_by_code: dict[str, _NavigationChannelBoundary] = {}
                for key in _channel_neighbor_grid_keys(lon, lat):
                    for boundary in grid_index.get(key, []):
                        if allowed_codes is not None and boundary.code not in allowed_codes:
                            continue
                        candidates_by_code.setdefault(boundary.code, boundary)
                near_candidates = list(candidates_by_code.values())
            for boundary in near_candidates:
                if not self._expanded_channel_bbox_contains(boundary.bbox, lon, lat, 0.06):
                    continue
                distance_m = self._channel_boundary_distance_m(lon, lat, boundary)
                if distance_m is not None and distance_m <= Decimal("5000"):
                    near_matches.append((boundary, distance_m))
            if not near_matches:
                return []
            selected, distance_m = min(
                near_matches,
                key=lambda item: (
                    self._channel_boundary_category_rank(item[0]),
                    item[1],
                    item[0].shape_area_degree if item[0].shape_area_degree is not None else Decimal("999999999"),
                    Decimal(str(item[0].bbox_area)),
                ),
            )
            return [
                _ResolvedNavigationChannel(
                    channel_code=selected.code,
                    channel_name=selected.name,
                    current_channel_source=CURRENT_CHANNEL_SOURCE_NEAR_BOUNDARY,
                    boundary=selected,
                    match_distance_m=distance_m.quantize(Decimal("0.1")),
                )
            ]
        selected = min(matches, key=self._channel_boundary_sort_key)
        return [
            _ResolvedNavigationChannel(
                channel_code=selected.code,
                channel_name=selected.name,
                current_channel_source=CURRENT_CHANNEL_SOURCE_BOUNDARY,
                boundary=selected,
                match_distance_m=Decimal("0"),
            )
        ]

    def _channel_boundary_sort_key(self, boundary: _NavigationChannelBoundary) -> tuple[int, Decimal, Decimal]:
        category_rank = self._channel_boundary_category_rank(boundary)
        shape_area = boundary.shape_area_degree if boundary.shape_area_degree is not None else Decimal("999999999")
        return category_rank, Decimal(boundary.display_priority), shape_area + Decimal(str(boundary.bbox_area))

    def _channel_boundary_category_rank(self, boundary: _NavigationChannelBoundary) -> int:
        return {
            "NATIONAL_CORE": 0,
            "NATIONAL_NETWORK": 1,
            "NATIONAL_IMPORTANT": 2,
            "PROVINCIAL_HIGH_GRADE": 3,
            "REGIONAL_IMPORTANT": 4,
            "REVIEW": 8,
            "PLANNED_GAP": 9,
        }.get(boundary.planning_level_code or "", 6)

    def _expanded_channel_bbox_contains(
        self,
        bbox: tuple[float, float, float, float],
        lon: float,
        lat: float,
        margin_degree: float,
    ) -> bool:
        min_lng, min_lat, max_lng, max_lat = bbox
        return (
            min_lng - margin_degree <= lon <= max_lng + margin_degree
            and min_lat - margin_degree <= lat <= max_lat + margin_degree
        )

    def _channel_boundary_distance_m(
        self,
        lon: float,
        lat: float,
        boundary: _NavigationChannelBoundary,
    ) -> Decimal | None:
        distances: list[float] = []
        rings = []
        if boundary.boundary_paths_by_precision:
            rings = boundary.boundary_paths_by_precision.get("low") or []
        if not rings:
            rings = [ring for polygon in boundary.polygons for ring in polygon]
        for ring in rings:
            if len(ring) < 2:
                continue
            for start, end in zip(ring, ring[1:], strict=False):
                distances.append(self._point_segment_distance_m(lon, lat, start, end))
        if not distances:
            return None
        return Decimal(str(min(distances)))

    def _point_segment_distance_m(
        self,
        lon: float,
        lat: float,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> float:
        mean_lat = math.radians((lat + start[1] + end[1]) / 3)
        meters_per_degree_lng = 111320.0 * max(math.cos(mean_lat), 0.000001)
        meters_per_degree_lat = 110540.0
        px, py = lon * meters_per_degree_lng, lat * meters_per_degree_lat
        ax, ay = start[0] * meters_per_degree_lng, start[1] * meters_per_degree_lat
        bx, by = end[0] * meters_per_degree_lng, end[1] * meters_per_degree_lat
        dx = bx - ax
        dy = by - ay
        if dx == 0 and dy == 0:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        projection_x = ax + t * dx
        projection_y = ay + t * dy
        return math.hypot(px - projection_x, py - projection_y)

    def _channel_match_for_position(
        self,
        item: VesselPositionMonitorItemResponse,
        *,
        channel_code: str | None,
        channel_name: str | None,
        boundaries: list[_NavigationChannelBoundary],
    ) -> _ResolvedNavigationChannel | None | bool:
        grid_index = _CHANNEL_BOUNDARY_CACHE.get("grid_index") or {}
        matches = self._resolve_current_channels_from_boundaries(
            _to_decimal(item.longitude),
            _to_decimal(item.latitude),
            boundaries,
            grid_index,
        )
        if channel_code:
            expected = channel_code.strip()
            if expected == UNKNOWN_CHANNEL_CODE:
                return None if not matches else False
            return next((match for match in matches if match.channel_code == expected), False)
        if channel_name:
            expected_name = channel_name.strip()
            if expected_name == UNKNOWN_CHANNEL_NAME:
                return None if not matches else False
            return next((match for match in matches if match.channel_name == expected_name), False)
        return matches[0] if matches else None

    def _channel_matches_position(
        self,
        item: VesselPositionMonitorItemResponse,
        *,
        channel_code: str | None,
        channel_name: str | None,
        boundaries: list[_NavigationChannelBoundary],
    ) -> bool:
        return self._channel_match_for_position(
            item,
            channel_code=channel_code,
            channel_name=channel_name,
            boundaries=boundaries,
        ) is not False

    async def _store_city_situation_snapshot(
        self,
        items: list[VesselPositionMonitorItemResponse],
        *,
        generated_at: datetime,
        partial: bool,
        error_message: str | None,
        snapshot_id: str | None = None,
    ) -> str:
        now = datetime.utcnow()
        ttl_seconds = _city_snapshot_ttl()
        expired = [key for key, value in _CITY_SITUATION_SNAPSHOTS.items() if value.expires_at <= now]
        for key in expired:
            _CITY_SITUATION_SNAPSHOTS.pop(key, None)
        while len(_CITY_SITUATION_SNAPSHOTS) >= CITY_SITUATION_SNAPSHOT_MAX_SIZE:
            oldest_key = min(_CITY_SITUATION_SNAPSHOTS, key=lambda key: _CITY_SITUATION_SNAPSHOTS[key].expires_at)
            _CITY_SITUATION_SNAPSHOTS.pop(oldest_key, None)
        snapshot_id = snapshot_id or uuid.uuid4().hex
        shared_required = _city_shared_cache_required()
        snapshot = _CitySituationSnapshot(
            snapshot_id=snapshot_id,
            expires_at=now + timedelta(seconds=ttl_seconds),
            items=list(items),
            partial=partial,
            error_message=error_message,
            generated_at=generated_at,
            status_code="PARTIAL" if partial else "READY",
        )
        if not shared_required:
            _CITY_SITUATION_SNAPSHOTS[snapshot_id] = snapshot
        if await self._city_cache_backend() == "redis":
            try:
                redis_client = await self._city_redis()
                if redis_client is not None:
                    payload = json.dumps(
                        {
                            "snapshot_id": snapshot.snapshot_id,
                            "expires_at": snapshot.expires_at.isoformat(),
                            "items": [item.model_dump(mode="json") for item in snapshot.items],
                            "partial": snapshot.partial,
                            "error_message": snapshot.error_message,
                            "generated_at": snapshot.generated_at.isoformat(),
                            "status_code": snapshot.status_code,
                        },
                        ensure_ascii=False,
                        default=str,
                    )
                    await redis_client.setex(CITY_SITUATION_SNAPSHOT_KEY_PREFIX + snapshot_id, ttl_seconds, payload)
            except Exception as exc:  # noqa: BLE001
                logger.warning("city situation redis snapshot write failed: %s", exc)
        return snapshot_id

    async def _get_city_situation_snapshot(self, snapshot_id: str | None) -> _CitySituationSnapshot | None:
        if not snapshot_id:
            return None
        shared_required = _city_shared_cache_required()
        if not shared_required:
            snapshot = _CITY_SITUATION_SNAPSHOTS.get(snapshot_id)
            if snapshot is not None:
                if snapshot.expires_at <= datetime.utcnow():
                    _CITY_SITUATION_SNAPSHOTS.pop(snapshot_id, None)
                else:
                    return snapshot
        if await self._city_cache_backend() == "redis":
            try:
                redis_client = await self._city_redis()
                payload = await redis_client.get(CITY_SITUATION_SNAPSHOT_KEY_PREFIX + snapshot_id) if redis_client else None
                if payload:
                    data = json.loads(payload)
                    restored = _CitySituationSnapshot(
                        snapshot_id=str(data["snapshot_id"]),
                        expires_at=datetime.fromisoformat(str(data["expires_at"])),
                        items=[VesselPositionMonitorItemResponse.model_validate(item) for item in data.get("items") or []],
                        partial=bool(data.get("partial")),
                        error_message=data.get("error_message"),
                        generated_at=datetime.fromisoformat(str(data["generated_at"])),
                        status_code=str(data.get("status_code") or ("PARTIAL" if data.get("partial") else "READY")),
                    )
                    if restored.expires_at > datetime.utcnow():
                        if not shared_required:
                            _CITY_SITUATION_SNAPSHOTS[snapshot_id] = restored
                        return restored
                    return _CitySituationSnapshot(
                        snapshot_id=restored.snapshot_id,
                        expires_at=restored.expires_at,
                        items=[],
                        partial=restored.partial,
                        error_message="SNAPSHOT_EXPIRED",
                        generated_at=restored.generated_at,
                        status_code="EXPIRED",
                        refresh_required=True,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("city situation redis snapshot read failed: %s", exc)
        persisted = await self._latest_persisted_ais_snapshot(snapshot_id)
        if persisted is not None:
            generated_at = persisted.generated_at or datetime.utcnow()
            items = await self._position_items_from_persisted_snapshot(
                persisted,
                generated_at=generated_at,
            )
            return _CitySituationSnapshot(
                snapshot_id=persisted.snapshot_id,
                expires_at=persisted.expires_at,
                items=items,
                partial=persisted.status_code == "PARTIAL",
                error_message=persisted.refresh_error,
                generated_at=generated_at,
                status_code="EXPIRED" if persisted.expires_at <= datetime.utcnow() else persisted.status_code,
                refresh_required=False,
            )
        return None

    def _empty_position_response(
        self,
        generated_at: datetime,
        message: str,
        matched_count: int = 0,
    ) -> VesselPositionMonitorResponse:
        return VesselPositionMonitorResponse(
            source_status="EMPTY",
            source_status_name=_source_status_name("EMPTY"),
            generated_at=generated_at,
            message=message,
            summary=VesselPositionMonitorSummary(
                matched_profile_count=matched_count,
                positioned_count=0,
                stale_position_count=0,
                contactable_position_count=0,
            ),
            items=[],
        )

    async def _active_mmsi_holder(self, mmsi: str, *, exclude_vessel_id: int | None = None) -> VesselProfile | None:
        stmt = select(VesselProfile).where(
            VesselProfile.current_mmsi == mmsi,
            VesselProfile.profile_status_code == ACTIVE_PROFILE_STATUS,
            VesselProfile.deleted_at.is_(None),
        )
        if exclude_vessel_id is not None:
            stmt = stmt.where(VesselProfile.id != exclude_vessel_id)
        return await self.db.scalar(stmt.limit(1))

    async def _assert_active_mmsi_available(
        self,
        mmsi: str,
        *,
        exclude_vessel_id: int | None = None,
        attempted_profile_id: int | None = None,
        evidence_source: str = "PROFILE_WRITE",
    ) -> None:
        holder = await self._active_mmsi_holder(mmsi, exclude_vessel_id=exclude_vessel_id)
        if holder is None:
            return
        issue_profile_id = attempted_profile_id or exclude_vessel_id or holder.id
        issue_payload = {
            "issue_type_code": "MMSI_CONFLICT",
            "profile_id": issue_profile_id,
            "object_type": "mmsi",
            "object_id": mmsi,
            "field_name": "current_mmsi",
            "normalized_key": f"mmsi|{mmsi}",
            "evidence_source": evidence_source,
            "severity_code": "HIGH",
            "impact_scope": [
                {"profile_id": holder.id, "ship_name": holder.ship_name, "role": "conflict_holder"},
                {"profile_id": attempted_profile_id or exclude_vessel_id, "role": "attempted_write"},
            ],
        }
        async with AsyncSessionLocal() as issue_db:
            await _upsert_quality_issue_in_session(issue_db, **issue_payload)
            await issue_db.commit()
        raise ConflictError(
            "ACTIVE MMSI 已被其他可用船舶档案占用",
            code="MMSI_ACTIVE_CONFLICT",
            detail={"mmsi": mmsi, "conflict_profile_id": holder.id},
        )
