"""AIS freshness distributions and city/channel response assembly."""

from __future__ import annotations

from app.modules.vessel.ais.common import *


class VesselAisResponseBuilderMixin:
    def _is_stale_position(self, item: VesselPositionMonitorItemResponse, generated_at: datetime, reported_within_minutes: int) -> bool:
        return bool(item.position_time and item.position_time < generated_at - timedelta(minutes=reported_within_minutes))

    def _position_freshness_distribution(self, items: list[VesselPositionMonitorItemResponse], unmatched: list[dict[str, Any]] | None = None) -> dict[str, int]:
        result = {"FRESH": 0, "RECENT": 0, "STALE": 0, "EXPIRED": 0, "UNKNOWN": 0}
        for item in items:
            level = getattr(item, "freshness_level", None)
            if not level:
                position_time = getattr(item, "position_time", None)
                age_minutes = int((datetime.utcnow() - position_time).total_seconds() // 60) if position_time else None
                level = _ais_freshness_level(age_minutes)
            result[level or "UNKNOWN"] = result.get(level or "UNKNOWN", 0) + 1
        for item in unmatched or []:
            level = str(item.get("freshness_level") or "UNKNOWN")
            result[level] = result.get(level, 0) + 1
        return result

    def _coverage_rate(self, matched_position_count: int, queried_mmsi_count: int) -> Decimal | None:
        if queried_mmsi_count <= 0:
            return None
        return (Decimal(matched_position_count) / Decimal(queried_mmsi_count) * Decimal("100")).quantize(Decimal("0.01"))

    def _position_city_code(self, item: VesselPositionMonitorItemResponse | None) -> str:
        if item is None:
            return UNKNOWN_CITY_CODE
        return (item.current_city_code or item.city_code or "").strip() or UNKNOWN_CITY_CODE

    def _position_city_name(self, item: VesselPositionMonitorItemResponse | None) -> str:
        if item is None:
            return UNKNOWN_CITY_NAME
        return (item.current_city_name or item.city_name or "").strip() or UNKNOWN_CITY_NAME

    def _city_matches(self, item: VesselPositionMonitorItemResponse, *, city_code: str | None, city_name: str | None) -> bool:
        if city_code:
            expected = city_code.strip()
            actual = self._position_city_code(item)
            if expected == UNKNOWN_CITY_CODE:
                return actual == UNKNOWN_CITY_CODE
            return actual == expected
        if city_name:
            return self._position_city_name(item) == city_name.strip()
        return True

    async def _summary_risk_level_by_profile(self, ids: list[int]) -> dict[int, str]:
        profile_ids = sorted({item for item in ids if item})
        if not profile_ids:
            return {}
        rows = []
        for start in range(0, len(profile_ids), 900):
            chunk = profile_ids[start:start + 900]
            rows.extend((
                await self.db.execute(
                    select(VesselProfileSummary.vessel_profile_id, VesselProfileSummary.risk_level).where(
                        VesselProfileSummary.vessel_profile_id.in_(chunk)
                    )
                )
            ).all())
        return {int(profile_id): str(risk_level or "UNKNOWN") for profile_id, risk_level in rows}

    def _filter_channel_situation_items_by_risk(
        self,
        items: list[VesselPositionMonitorItemResponse],
        query,
        risk_by_profile: dict[int, dict[str, Any]],
        summary_risk_by_profile: dict[int, str],
    ) -> list[VesselPositionMonitorItemResponse]:
        filtered = list(items)
        certificate_risk_available = getattr(query, "certificate_risk_available", None)
        if certificate_risk_available is not None:
            expected = bool(certificate_risk_available)
            filtered = [
                item for item in filtered
                if bool(risk_by_profile.get(item.id, {}).get("has_certificate_risk")) is expected
            ]
        risk_level = getattr(query, "risk_level", None)
        if risk_level:
            filtered = [item for item in filtered if summary_risk_by_profile.get(item.id, "UNKNOWN") == risk_level]
        return filtered

    def _channel_query_code_set(self, query, attr_name: str) -> set[str]:
        raw = getattr(query, attr_name, None)
        if not raw:
            return set()
        return {part.strip() for part in str(raw).split(",") if part.strip()}

    def _filter_channel_boundaries(
        self,
        boundaries: list[_NavigationChannelBoundary],
        keyword: str | None,
        channel_type_codes: set[str] | None = None,
        planning_level_codes: set[str] | None = None,
    ) -> list[_NavigationChannelBoundary]:
        result = list(boundaries)
        if channel_type_codes:
            result = [boundary for boundary in result if (boundary.channel_type_code or "") in channel_type_codes]
        if planning_level_codes:
            result = [boundary for boundary in result if (boundary.planning_level_code or "") in planning_level_codes]
        if keyword:
            text = keyword.strip()
            result = [boundary for boundary in result if text in boundary.name or text in boundary.code]
        return result

    def _channel_situation_items(
        self,
        items: list[VesselPositionMonitorItemResponse],
        risk_by_profile: dict[int, dict[str, Any]],
        summary_risk_by_profile: dict[int, str],
        generated_at: datetime,
        reported_within_minutes: int,
        queried_mmsi_count: int,
        matched_position_count: int,
        unpositioned_count: int,
        invalid_position_count: int,
        partial: bool,
        error_message: str | None,
        boundaries: list[_NavigationChannelBoundary],
        boundary_paths_by_code: dict[str, list[list[tuple[float, float]]]] | None = None,
        boundary_precision: str | None = None,
        include_empty_channels: bool = True,
    ) -> list[VesselPositionNavigationChannelSituationItemResponse]:
        boundary_paths_by_code = boundary_paths_by_code or {}
        boundary_by_code = {boundary.code: boundary for boundary in boundaries}
        grouped: dict[str, list[VesselPositionMonitorItemResponse]] = defaultdict(list)
        unmatched_items: list[VesselPositionMonitorItemResponse] = []
        grid_index = _CHANNEL_BOUNDARY_CACHE.get("grid_index") or {}
        allowed_codes = set(boundary_by_code.keys())
        allow_near_match = bool(settings.VESSEL_CHANNEL_SITUATION_NEAR_MATCH)
        for item in items:
            precomputed_channel_code = str(getattr(item, "current_channel_code", "") or "").strip()
            if precomputed_channel_code:
                if precomputed_channel_code in boundary_by_code:
                    grouped[precomputed_channel_code].append(item)
                else:
                    unmatched_items.append(item)
                continue
            matches = self._resolve_current_channels_from_boundaries(
                _to_decimal(item.longitude),
                _to_decimal(item.latitude),
                boundaries,
                grid_index,
                allowed_codes,
                allow_near_match=allow_near_match,
            )
            if not matches:
                unmatched_items.append(item)
                continue
            for match in matches:
                if match.channel_code:
                    grouped[match.channel_code].append(item)
        result: list[VesselPositionNavigationChannelSituationItemResponse] = []
        for code, system_items in grouped.items():
            boundary = boundary_by_code.get(code)
            if boundary is None:
                continue
            result.append(
                self._channel_situation_response_item(
                    boundary,
                    system_items,
                    risk_by_profile,
                    summary_risk_by_profile,
                    generated_at,
                    reported_within_minutes,
                    partial,
                    error_message,
                    boundary_paths_by_code.get(code),
                    boundary_precision,
                )
            )
        if include_empty_channels:
            for boundary in boundaries:
                if boundary.code in grouped:
                    continue
                result.append(
                    self._channel_situation_response_item(
                        boundary,
                        [],
                        risk_by_profile,
                        summary_risk_by_profile,
                        generated_at,
                        reported_within_minutes,
                        partial,
                        error_message,
                        boundary_paths_by_code.get(boundary.code),
                        boundary_precision,
                    )
                )
        if unmatched_items:
            fresh_items = [item for item in unmatched_items if not self._is_stale_position(item, generated_at, reported_within_minutes)]
            longitudes = [_to_decimal(item.longitude) for item in fresh_items]
            latitudes = [_to_decimal(item.latitude) for item in fresh_items]
            longitudes = [value for value in longitudes if value is not None]
            latitudes = [value for value in latitudes if value is not None]
            result.append(
                VesselPositionNavigationChannelSituationItemResponse(
                    channel_code=None,
                    channel_name=UNKNOWN_CHANNEL_NAME,
                    boundary_paths=None,
                    has_boundary=False,
                    boundary_precision=None,
                    heat_center_longitude=(sum(longitudes, Decimal("0")) / Decimal(len(longitudes))).quantize(Decimal("0.000001")) if longitudes else None,
                    heat_center_latitude=(sum(latitudes, Decimal("0")) / Decimal(len(latitudes))).quantize(Decimal("0.000001")) if latitudes else None,
                    positioned_count=len(fresh_items),
                    contactable_position_count=sum(1 for item in fresh_items if item.contact_available),
                    total_deadweight_ton=self._sum_deadweight(fresh_items),
                    ship_type_distribution=self._ship_type_distribution(fresh_items),
                    stale_position_count=len(unmatched_items) - len(fresh_items),
                    certificate_risk_count=sum(1 for item in fresh_items if risk_by_profile.get(item.id, {}).get("has_certificate_risk")),
                    high_risk_count=sum(1 for item in fresh_items if summary_risk_by_profile.get(item.id) == "HIGH"),
                    freshness_distribution=self._position_freshness_distribution(unmatched_items),
                    boundary_status_code="UNKNOWN_CHANNEL",
                    latest_position_time=max([item.position_time for item in unmatched_items if item.position_time], default=None),
                    mmsi_count=queried_mmsi_count,
                    matched_position_count=matched_position_count,
                    unpositioned_count=unpositioned_count + invalid_position_count,
                    is_partial=partial,
                    error_message=error_message,
                )
            )
        return sorted(result, key=lambda item: (item.positioned_count, item.total_deadweight_ton or Decimal("0")), reverse=True)

    def _channel_situation_response_item(
        self,
        boundary: _NavigationChannelBoundary,
        system_items: list[VesselPositionMonitorItemResponse],
        risk_by_profile: dict[int, dict[str, Any]],
        summary_risk_by_profile: dict[int, str],
        generated_at: datetime,
        reported_within_minutes: int,
        partial: bool,
        error_message: str | None,
        paths: list[list[tuple[float, float]]] | None,
        boundary_precision: str | None,
    ) -> VesselPositionNavigationChannelSituationItemResponse:
        fresh_items = [item for item in system_items if not self._is_stale_position(item, generated_at, reported_within_minutes)]
        stats_items = fresh_items or system_items
        longitudes = [_to_decimal(item.longitude) for item in stats_items]
        latitudes = [_to_decimal(item.latitude) for item in stats_items]
        longitudes = [value for value in longitudes if value is not None]
        latitudes = [value for value in latitudes if value is not None]
        heat_longitude = (sum(longitudes, Decimal("0")) / Decimal(len(longitudes))).quantize(Decimal("0.000001")) if longitudes else None
        heat_latitude = (sum(latitudes, Decimal("0")) / Decimal(len(latitudes))).quantize(Decimal("0.000001")) if latitudes else None
        serialized_paths = _serialize_boundary_paths(paths)
        has_boundary = bool(
            boundary.polygons
            or any((boundary.boundary_paths_by_precision or {}).values())
        )
        return VesselPositionNavigationChannelSituationItemResponse(
            channel_code=boundary.code,
            channel_name=boundary.name,
            parent_channel_code=boundary.parent_channel_code,
            channel_type_code=boundary.channel_type_code,
            channel_type_name=_channel_type_name(boundary.channel_type_code),
            planning_level_code=boundary.planning_level_code,
            planning_level_name=_channel_planning_level_name(boundary.planning_level_code),
            ais_scope_code=boundary.ais_scope_code,
            ais_scope_name=_channel_ais_scope_name(boundary.ais_scope_code),
            center_longitude=boundary.center_longitude,
            center_latitude=boundary.center_latitude,
            display_center_longitude=boundary.display_center_longitude,
            display_center_latitude=boundary.display_center_latitude,
            heat_center_longitude=heat_longitude or boundary.display_center_longitude or boundary.center_longitude,
            heat_center_latitude=heat_latitude or boundary.display_center_latitude or boundary.center_latitude,
            boundary_paths=serialized_paths,
            has_boundary=has_boundary,
            boundary_precision=boundary_precision if serialized_paths else None,
            boundary_quality_code=boundary.boundary_quality_code,
            boundary_quality_name=_channel_boundary_quality_name(boundary.boundary_quality_code),
            connectivity_status_code=boundary.connectivity_status_code,
            connectivity_status_name=_channel_connectivity_status_name(boundary.connectivity_status_code),
            repair_status_code=boundary.repair_status_code,
            repair_status_name=_channel_repair_status_name(boundary.repair_status_code),
            geometry_coordinate_system_code=boundary.geometry_coordinate_system_code,
            boundary_coordinate_system_code=boundary.boundary_coordinate_system_code,
            positioned_count=len(fresh_items),
            contactable_position_count=sum(1 for item in fresh_items if item.contact_available),
            total_deadweight_ton=self._sum_deadweight(stats_items),
            ship_type_distribution=self._ship_type_distribution(stats_items),
            stale_position_count=len(system_items) - len(fresh_items),
            certificate_risk_count=sum(1 for item in fresh_items if risk_by_profile.get(item.id, {}).get("has_certificate_risk")),
            high_risk_count=sum(1 for item in fresh_items if summary_risk_by_profile.get(item.id) == "HIGH"),
            freshness_distribution=self._position_freshness_distribution(system_items),
            boundary_status_code="AVAILABLE" if has_boundary else "MISSING",
            latest_position_time=max([item.position_time for item in system_items if item.position_time], default=None),
            mmsi_count=len(system_items),
            matched_position_count=len(system_items),
            unpositioned_count=0,
            is_partial=partial,
            error_message=error_message,
        )

    def _sum_deadweight(self, items: list[VesselPositionMonitorItemResponse]) -> Decimal:
        values = [_to_decimal(item.deadweight_ton) for item in items if item.deadweight_ton is not None]
        values = [value for value in values if value is not None]
        return sum(values, Decimal("0")).quantize(Decimal("0.01")) if values else Decimal("0")

    def _ship_type_distribution(self, items: list[VesselPositionMonitorItemResponse]) -> list[VesselShipTypeDistributionItemResponse]:
        type_counts: dict[str | None, int] = defaultdict(int)
        type_names: dict[str | None, str | None] = {}
        for item in items:
            type_counts[item.ship_type_code] += 1
            type_names[item.ship_type_code] = item.ship_type_name
        return [
            VesselShipTypeDistributionItemResponse(
                ship_type_code=code,
                ship_type_name=type_names.get(code),
                count=count,
            )
            for code, count in sorted(type_counts.items(), key=lambda item: item[1], reverse=True)
        ]

    def _city_situation_items(
        self,
        items: list[VesselPositionMonitorItemResponse],
        risk_by_profile: dict[int, dict[str, Any]],
        generated_at: datetime,
        reported_within_minutes: int,
        queried_mmsi_count: int,
        matched_position_count: int,
        unpositioned_count: int,
        invalid_position_count: int,
        unknown_city_count: int,
        partial: bool,
        error_message: str | None,
        boundary_paths_by_code: dict[str, list[list[tuple[float, float]]]] | None = None,
        boundary_precision: str | None = None,
        boundary_codes: set[str] | None = None,
        unmatched_positions: list[dict[str, Any]] | None = None,
    ) -> list[VesselPositionCitySituationItemResponse]:
        boundary_paths_by_code = boundary_paths_by_code or {}
        boundary_codes = boundary_codes or set(boundary_paths_by_code.keys())
        unmatched_positions = unmatched_positions or []
        grouped: dict[str, list[VesselPositionMonitorItemResponse]] = defaultdict(list)
        for item in items:
            grouped[self._position_city_code(item)].append(item)
        unmatched_grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for position in unmatched_positions:
            city_code = str(position.get("city_code") or UNKNOWN_CITY_CODE)
            unmatched_grouped[city_code].append(position)
            grouped.setdefault(city_code, [])
        result: list[VesselPositionCitySituationItemResponse] = []
        for city_code, city_items in grouped.items():
            fresh_items = [item for item in city_items if not self._is_stale_position(item, generated_at, reported_within_minutes)]
            stats_items = fresh_items or city_items
            city_unmatched = unmatched_grouped.get(city_code, [])
            ages = [Decimal(item.ship_age) for item in stats_items if item.ship_age is not None]
            deadweights = [_to_decimal(item.deadweight_ton) for item in stats_items if item.deadweight_ton is not None]
            deadweights = [value for value in deadweights if value is not None]
            type_counts: dict[str | None, int] = defaultdict(int)
            type_names: dict[str | None, str | None] = {}
            for item in stats_items:
                type_counts[item.ship_type_code] += 1
                type_names[item.ship_type_code] = item.ship_type_name
            longitudes = [_to_decimal(item.longitude) for item in stats_items]
            latitudes = [_to_decimal(item.latitude) for item in stats_items]
            longitudes = [value for value in longitudes if value is not None]
            latitudes = [value for value in latitudes if value is not None]
            is_unknown_city = city_code == UNKNOWN_CITY_CODE
            heat_longitude = (sum(longitudes, Decimal("0")) / Decimal(len(longitudes))).quantize(Decimal("0.000001")) if longitudes and not is_unknown_city else None
            heat_latitude = (sum(latitudes, Decimal("0")) / Decimal(len(latitudes))).quantize(Decimal("0.000001")) if latitudes and not is_unknown_city else None
            first_item = stats_items[0] if stats_items else None
            serialized_boundary_paths = None if is_unknown_city else _serialize_boundary_paths(boundary_paths_by_code.get(city_code))
            has_boundary = False if is_unknown_city else city_code in boundary_codes
            freshness_distribution = self._position_freshness_distribution(city_items, city_unmatched)
            result.append(
                VesselPositionCitySituationItemResponse(
                    city_code=None if is_unknown_city else city_code,
                    city_name=self._position_city_name(first_item) if first_item else str(city_unmatched[0].get("city_name") or UNKNOWN_CITY_NAME) if city_unmatched else UNKNOWN_CITY_NAME,
                    longitude=None if is_unknown_city else getattr(first_item, "city_center_longitude", None),
                    latitude=None if is_unknown_city else getattr(first_item, "city_center_latitude", None),
                    city_center_longitude=None if is_unknown_city else getattr(first_item, "city_center_longitude", None),
                    city_center_latitude=None if is_unknown_city else getattr(first_item, "city_center_latitude", None),
                    heat_center_longitude=heat_longitude,
                    heat_center_latitude=heat_latitude,
                    boundary_paths=serialized_boundary_paths,
                    has_boundary=has_boundary,
                    boundary_precision=None if is_unknown_city or not serialized_boundary_paths else boundary_precision,
                    positioned_count=len(fresh_items),
                    contactable_position_count=sum(1 for item in fresh_items if item.contact_available),
                    average_ship_age=(sum(ages, Decimal("0")) / Decimal(len(ages))).quantize(Decimal("0.1")) if ages else None,
                    total_deadweight_ton=sum(deadweights, Decimal("0")).quantize(Decimal("0.01")) if deadweights else Decimal("0"),
                    ship_type_distribution=[
                        VesselShipTypeDistributionItemResponse(
                            ship_type_code=code,
                            ship_type_name=type_names.get(code),
                            count=count,
                        )
                        for code, count in sorted(type_counts.items(), key=lambda item: item[1], reverse=True)
                    ],
                    stale_position_count=len(city_items) - len(fresh_items),
                    certificate_risk_count=sum(1 for item in fresh_items if risk_by_profile.get(item.id, {}).get("has_certificate_risk")),
                    unmatched_mmsi_count=len(city_unmatched),
                    invalid_position_count=sum(1 for item in city_unmatched if not item.get("valid_position_flag", True)),
                    freshness_distribution=freshness_distribution,
                    boundary_status_code="UNKNOWN_CITY" if is_unknown_city else ("AVAILABLE" if has_boundary else "MISSING"),
                    latest_position_time=max([item.position_time for item in city_items if item.position_time], default=None),
                    mmsi_count=(queried_mmsi_count + len(city_unmatched)) if is_unknown_city else len(city_items) + len(city_unmatched),
                    matched_position_count=matched_position_count if is_unknown_city else len(city_items),
                    unpositioned_count=(unpositioned_count + invalid_position_count) if is_unknown_city else 0,
                    is_partial=partial,
                    error_message=error_message,
                )
            )
        missing_position_count = unpositioned_count + invalid_position_count
        if missing_position_count and UNKNOWN_CITY_CODE not in grouped:
            result.append(
                VesselPositionCitySituationItemResponse(
                    city_code=None,
                    city_name=UNKNOWN_CITY_NAME,
                    longitude=None,
                    latitude=None,
                    city_center_longitude=None,
                    city_center_latitude=None,
                    heat_center_longitude=None,
                    heat_center_latitude=None,
                    positioned_count=0,
                    contactable_position_count=0,
                    average_ship_age=None,
                    total_deadweight_ton=Decimal("0"),
                    ship_type_distribution=[],
                    stale_position_count=0,
                    certificate_risk_count=0,
                    unmatched_mmsi_count=0,
                    invalid_position_count=invalid_position_count,
                    freshness_distribution={},
                    boundary_status_code="UNKNOWN_CITY",
                    latest_position_time=None,
                    mmsi_count=queried_mmsi_count,
                    matched_position_count=matched_position_count,
                    unpositioned_count=missing_position_count,
                    is_partial=partial,
                    error_message=error_message,
                )
            )
        return sorted(result, key=lambda item: (item.positioned_count, item.total_deadweight_ton or Decimal("0")), reverse=True)

    @staticmethod
    def _valid_longitude_latitude(longitude: Decimal | None, latitude: Decimal | None) -> bool:
        if longitude is None or latitude is None:
            return False
        return Decimal("-180") <= longitude <= Decimal("180") and Decimal("-90") <= latitude <= Decimal("90")
