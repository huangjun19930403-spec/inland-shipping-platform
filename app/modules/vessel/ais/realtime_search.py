"""Realtime ES lookup and position item construction."""

from __future__ import annotations

from app.modules.vessel.ais.common import *


class VesselAisRealtimeSearchMixin:
    async def _mmsi_values_for_loaded_profiles(
        self,
        ids: list[int],
        profiles: list[VesselProfile],
    ) -> dict[int, list[str]]:
        matcher = self._mmsi_values_by_profile
        if "profiles" in inspect.signature(matcher).parameters:
            return await matcher(ids, profiles=profiles)
        return await matcher(ids)

    async def _mmsi_values_by_profile(
        self,
        ids: list[int],
        *,
        profiles: list[VesselProfile] | None = None,
    ) -> dict[int, list[str]]:
        rows = (
            await self.db.execute(
                select(VesselIdentifierHistory)
                .where(
                    VesselIdentifierHistory.vessel_profile_id.in_(ids),
                    VesselIdentifierHistory.identifier_type_code == "MMSI",
                    or_(VesselIdentifierHistory.end_date.is_(None), VesselIdentifierHistory.end_date >= date.today()),
                )
            )
        ).scalars().all()
        result: dict[int, list[str]] = defaultdict(list)
        profile_ids = set(ids)
        profiles_by_id = (
            {
                int(profile.id): profile
                for profile in profiles
                if getattr(profile, "id", None) in profile_ids
            }
            if profiles is not None
            else await self._profiles_by_ids(ids)
        )
        for profile_id, profile in profiles_by_id.items():
            if profile.current_mmsi:
                result[profile_id].append(profile.current_mmsi)
        for row in rows:
            if row.identifier_value and row.identifier_value not in result[row.vessel_profile_id]:
                result[row.vessel_profile_id].append(row.identifier_value)
        return result

    async def _search_realtime_positions(
        self,
        mmsi_values: list[str],
        *,
        max_hits: int,
        reported_within_minutes: int | None = None,
    ) -> dict[str, dict[str, Any]]:
        terms: list[Any] = []
        for value in mmsi_values:
            text_value = str(value).strip()
            if not text_value:
                continue
            terms.append(text_value)
        terms = list(dict.fromkeys(terms))
        time_fields = ["posTime", "updateTime"]
        source_fields = [
            "shipMmsi",
            "lon",
            "lat",
            "speed",
            "cog",
            "head",
            "posTime",
            "updateTime",
            "shipName",
            "shipEnName",
            "shipType",
        ]
        filters: list[dict[str, Any]] = [{"terms": {"shipMmsi": terms}}]
        if reported_within_minutes:
            earliest = (datetime.utcnow() - timedelta(minutes=reported_within_minutes)).strftime("%Y-%m-%d %H:%M:%S")
            filters.append({"range": {"posTime": {"gte": earliest}}})
        query_body = {
            "size": min(max_hits, 5000),
            "track_total_hits": False,
            "_source": source_fields,
            "sort": [
                {field: {"order": "desc", "unmapped_type": "date", "missing": "_last"}}
                for field in time_fields
            ],
            "query": {"bool": {"filter": filters}},
        }
        client = RealtimeEsClient(
            runtime_config=self.runtime_config,
            max_retries=0,
            timeout_seconds=await self._ais_es_request_timeout_seconds(),
        )
        index = (
            await self.runtime_config.get_value(
                ES_R_INDEX,
                settings.ES_R_INDEX or "ship_positions",
                profile_code=ES_REALTIME_CONFIG_PROFILE,
            )
            or "ship_positions"
        ).strip()
        try:
            payload = await client.search(index, query_body)
        except Exception:
            query_body.pop("sort", None)
            payload = await client.search(index, query_body)
        hits = ((payload.get("hits") or {}).get("hits") or []) if isinstance(payload, dict) else []
        result: dict[str, dict[str, Any]] = {}
        for hit in hits:
            source = hit.get("_source") if isinstance(hit, dict) else None
            if not isinstance(source, dict):
                continue
            mmsi_raw = _first_value(source, ["shipMmsi", "mmsi", "ship_mmsi", "MMSI", "ais", "ship_ais"])
            if mmsi_raw is None:
                continue
            mmsi = str(mmsi_raw).strip()
            longitude = _to_decimal(_first_value(source, ["lon", "lng", "longitude", "x", "longitude_gcj02"]))
            latitude = _to_decimal(_first_value(source, ["lat", "latitude", "y", "latitude_gcj02"]))
            position_time = _parse_position_time(
                _first_value(source, ["posTime", "updateTime", "timestamp", "location_time", "update_time", "position_time", "time", "@timestamp"])
            )
            existing = result.get(mmsi)
            if existing and existing.get("position_time") and position_time and existing["position_time"] >= position_time:
                continue
            result[mmsi] = {
                "mmsi": mmsi,
                "source_index": hit.get("_index") if isinstance(hit, dict) else None,
                "longitude": longitude,
                "latitude": latitude,
                "speed_kn": _first_value(source, ["speed", "sog", "speed_kn"]),
                "course_deg": _first_value(source, ["course", "cog", "course_deg"]),
                "heading_deg": _first_value(source, ["heading", "head", "hdg", "heading_deg"]),
                "position_time": position_time,
                "location_text": _first_value(source, ["location_text", "address", "area_name", "city_name"]),
                "raw_city_code": _first_value(source, ["city_code", "cityCode", "adcode", "city_adcode", "region_code"]),
                "raw_city_name": _first_value(source, ["city_name", "city", "area_name"]),
            }
        return result

    async def _search_recent_realtime_positions(self, *, reported_within_minutes: int, max_hits: int) -> dict[str, dict[str, Any]]:
        time_fields = ["posTime"]
        source_fields = [
            "shipMmsi", "lon", "lat", "speed", "cog", "head", "posTime", "updateTime", "shipName", "shipEnName", "shipType",
        ]
        earliest = (datetime.utcnow() - timedelta(minutes=reported_within_minutes)).strftime("%Y-%m-%d %H:%M:%S")
        query_body = {
            "size": min(max_hits, 10000),
            "track_total_hits": False,
            "_source": source_fields,
            "sort": [
                {field: {"order": "desc", "unmapped_type": "date", "missing": "_last"}}
                for field in time_fields
            ],
            "query": {"range": {"posTime": {"gte": earliest}}},
        }
        client = RealtimeEsClient(
            runtime_config=self.runtime_config,
            max_retries=0,
            timeout_seconds=await self._ais_es_request_timeout_seconds(),
        )
        index = (
            await self.runtime_config.get_value(
                ES_R_INDEX,
                settings.ES_R_INDEX or "ship_positions",
                profile_code=ES_REALTIME_CONFIG_PROFILE,
            )
            or "ship_positions"
        ).strip()
        try:
            payload = await client.search(index, query_body)
        except Exception:
            query_body.pop("sort", None)
            payload = await client.search(index, query_body)
        hits = ((payload.get("hits") or {}).get("hits") or []) if isinstance(payload, dict) else []
        result: dict[str, dict[str, Any]] = {}
        for hit in hits:
            source = hit.get("_source") if isinstance(hit, dict) else None
            if not isinstance(source, dict):
                continue
            mmsi_raw = _first_value(source, ["shipMmsi", "mmsi", "ship_mmsi", "MMSI", "ais", "ship_ais"])
            if mmsi_raw is None:
                continue
            mmsi = str(mmsi_raw).strip()
            if not mmsi:
                continue
            position_time = _parse_position_time(
                _first_value(source, ["posTime", "updateTime", "timestamp", "location_time", "update_time", "position_time", "time", "@timestamp"])
            )
            existing = result.get(mmsi)
            if existing and existing.get("position_time") and position_time and existing["position_time"] >= position_time:
                continue
            result[mmsi] = {
                "mmsi": mmsi,
                "source_index": hit.get("_index") if isinstance(hit, dict) else None,
                "longitude": _to_decimal(_first_value(source, ["lon", "lng", "longitude", "x", "longitude_gcj02"])),
                "latitude": _to_decimal(_first_value(source, ["lat", "latitude", "y", "latitude_gcj02"])),
                "speed_kn": _first_value(source, ["speed", "sog", "speed_kn"]),
                "course_deg": _first_value(source, ["course", "cog", "course_deg"]),
                "heading_deg": _first_value(source, ["heading", "head", "hdg", "heading_deg"]),
                "position_time": position_time,
                "location_text": _first_value(source, ["location_text", "address", "area_name", "city_name"]),
                "raw_city_code": _first_value(source, ["city_code", "cityCode", "adcode", "city_adcode", "region_code"]),
                "raw_city_name": _first_value(source, ["city_name", "city", "area_name"]),
            }
        return result

    async def _search_realtime_positions_batched(
        self,
        mmsi_values: list[str],
        *,
        batch_size: int,
        max_concurrency: int,
        reported_within_minutes: int | None = None,
    ) -> tuple[dict[str, dict[str, Any]], bool, str | None, int, list[dict[str, Any]]]:
        positions: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        unique_values = [value for value in dict.fromkeys(mmsi_values) if value]
        batches = [unique_values[start:start + batch_size] for start in range(0, len(unique_values), batch_size)]
        semaphore = asyncio.Semaphore(max(1, max_concurrency))

        async def run_batch(batch_index: int, batch: list[str]) -> tuple[int, list[str], dict[str, dict[str, Any]], str | None]:
            async with semaphore:
                try:
                    return batch_index, batch, await self._search_realtime_positions(
                        batch,
                        max_hits=max(len(batch) * 3, 200),
                        reported_within_minutes=reported_within_minutes,
                    ), None
                except Exception as exc:  # noqa: BLE001
                    return batch_index, batch, {}, str(exc)

        failed_batches: list[dict[str, Any]] = []
        for batch_index, batch, batch_positions, error in await asyncio.gather(
            *(run_batch(batch_index, batch) for batch_index, batch in enumerate(batches, start=1))
        ):
            if batch_positions:
                positions.update(batch_positions)
            if error:
                public_error = _public_ais_error_message(error) or "部分实时 AIS 数据暂不可用，请稍后刷新"
                logger.warning("realtime AIS batch search failed: batch_index=%s mmsi_count=%s error=%s", batch_index, len(batch), error)
                errors.append(public_error)
                failed_batches.append({
                    "batch_index": batch_index,
                    "mmsi_count": len(batch),
                    "sample_mmsi": batch[:5],
                    "error_message": public_error,
                })
        unique_errors = list(dict.fromkeys(errors))
        return positions, bool(errors), "；".join(unique_errors[:3]) if unique_errors else None, len(errors), failed_batches

    async def _position_monitor_items_for_profiles(
        self,
        profiles: list[VesselProfile],
        *,
        generated_at: datetime,
        reported_within_minutes: int,
        es_batch_size: int,
        es_max_concurrency: int,
        include_stale: bool,
        include_unmatched: bool = False,
        unmatched_scan_limit: int = 0,
        resolve_city: bool = True,
        resolve_channel: bool = False,
        mmsi_by_profile: dict[int, list[str]] | None = None,
    ) -> _PositionBuildResult:
        if mmsi_by_profile is None:
            mmsi_by_profile = await self._mmsi_values_for_loaded_profiles(
                [row.id for row in profiles],
                profiles,
            )
        mmsi_values = sorted({item for values in mmsi_by_profile.values() for item in values if item})
        if not mmsi_values:
            return _PositionBuildResult([], False, None, 0, 0, 0, 0, 0, 0)
        positions, partial, error_message, failed_batch_count, failed_batches = await self._search_realtime_positions_batched(
            mmsi_values,
            batch_size=es_batch_size,
            max_concurrency=es_max_concurrency,
            reported_within_minutes=reported_within_minutes,
        )
        if include_unmatched and unmatched_scan_limit > 0:
            try:
                recent_positions = await self._search_recent_realtime_positions(
                    reported_within_minutes=reported_within_minutes,
                    max_hits=unmatched_scan_limit,
                )
                for mmsi, position in recent_positions.items():
                    positions.setdefault(mmsi, position)
            except Exception as exc:  # noqa: BLE001
                partial = True
                failed_batch_count += 1
                logger.warning("realtime AIS unmatched MMSI scan failed: %s", exc)
                public_error = "部分实时 AIS 数据暂不可用，请稍后刷新"
                error_message = "；".join(part for part in [error_message, public_error] if part)
                failed_batches.append({
                    "batch_index": "unmatched_scan",
                    "mmsi_count": 0,
                    "sample_mmsi": [],
                    "error_message": public_error,
                })
        if not positions:
            return _PositionBuildResult(
                items=[],
                partial=partial,
                error_message=error_message,
                failed_batch_count=failed_batch_count,
                queried_mmsi_count=len(mmsi_values),
                matched_position_count=0,
                unpositioned_count=len(mmsi_values),
                invalid_position_count=0,
                unknown_city_count=0,
                failed_batches=failed_batches,
            )
        boundaries = await self._city_boundaries() if resolve_city else []
        boundary_grid = _CITY_BOUNDARY_CACHE.get("grid_index") or {}
        channel_boundaries = await self._channel_boundaries() if resolve_channel else []
        channel_grid = _CHANNEL_BOUNDARY_CACHE.get("grid_index") or {}
        profiles_by_mmsi: dict[str, list[VesselProfile]] = defaultdict(list)
        for profile in profiles:
            for mmsi in mmsi_by_profile.get(profile.id, [profile.current_mmsi]):
                if mmsi:
                    profiles_by_mmsi[mmsi].append(profile)
        position_by_profile: dict[int, dict[str, Any]] = {}
        match_status_by_profile: dict[int, str] = {}
        freshness_limit = generated_at - timedelta(minutes=reported_within_minutes)
        unmatched_positions: list[dict[str, Any]] = []
        invalid_positions: list[dict[str, Any]] = []
        for mmsi, position in positions.items():
            matched_profiles = profiles_by_mmsi.get(mmsi) or []
            if not matched_profiles:
                longitude = _to_decimal(position.get("longitude"))
                latitude = _to_decimal(position.get("latitude"))
                position_time = position.get("position_time")
                age_minutes = int((generated_at - position_time).total_seconds() // 60) if position_time else None
                valid_position = self._valid_longitude_latitude(longitude, latitude)
                if resolve_city and valid_position:
                    resolved_city = self._resolve_current_city_from_boundaries(longitude, latitude, boundaries, boundary_grid)
                else:
                    resolved_city = _ResolvedCity(None, UNKNOWN_CITY_NAME, CURRENT_CITY_SOURCE_INVALID_POSITION if not valid_position else CURRENT_CITY_SOURCE_UNKNOWN)
                unmatched_positions.append({
                    **position,
                    "mmsi": mmsi,
                    "longitude": longitude,
                    "latitude": latitude,
                    "position_age_minutes": age_minutes,
                    "freshness_level": _ais_freshness_level(age_minutes),
                    "match_status_code": "UNMATCHED_MMSI" if valid_position else "INVALID_POSITION",
                    "valid_position_flag": valid_position,
                    "city_code": resolved_city.city_code,
                    "city_name": resolved_city.city_name,
                    "current_city_source": resolved_city.current_city_source,
                })
                if not valid_position:
                    invalid_positions.append(unmatched_positions[-1])
                continue
            profile = matched_profiles[0]
            if profile.id in position_by_profile:
                continue
            position_time = position.get("position_time")
            if not include_stale and position_time and position_time < freshness_limit:
                continue
            position_by_profile[profile.id] = position
            match_status_by_profile[profile.id] = "MULTI_PROFILE_CONFLICT" if len(matched_profiles) > 1 else "MATCHED_PROFILE"
        positioned_profiles = [profile for profile in profiles if profile.id in position_by_profile]
        list_items = await self._build_list_items(positioned_profiles)
        items: list[VesselPositionMonitorItemResponse] = []
        invalid_position_count = 0
        unknown_city_count = 0
        for item in list_items:
            position = position_by_profile.get(item.id)
            if position is None:
                continue
            longitude = _to_decimal(position.get("longitude"))
            latitude = _to_decimal(position.get("latitude"))
            if longitude is None or latitude is None or not self._valid_longitude_latitude(longitude, latitude):
                invalid_position_count += 1
                invalid_positions.append({**position, "mmsi": item.current_mmsi, "vessel_profile_id": item.id, "match_status_code": "INVALID_POSITION", "valid_position_flag": False})
                continue
            if resolve_city:
                resolved_city = self._resolve_current_city_from_boundaries(longitude, latitude, boundaries, boundary_grid)
            else:
                resolved_city = _ResolvedCity(None, UNKNOWN_CITY_NAME, CURRENT_CITY_SOURCE_UNKNOWN)
            if resolved_city.current_city_source != CURRENT_CITY_SOURCE_ADMIN_BOUNDARY:
                unknown_city_count += 1
            resolved_channel = None
            if resolve_channel:
                channel_matches = self._resolve_current_channels_from_boundaries(
                    longitude,
                    latitude,
                    channel_boundaries,
                    channel_grid,
                    None,
                    allow_near_match=bool(settings.VESSEL_CHANNEL_SITUATION_NEAR_MATCH),
                )
                resolved_channel = channel_matches[0] if channel_matches else None
            position_time = position.get("position_time")
            age_minutes = int((generated_at - position_time).total_seconds() // 60) if position_time else None
            freshness_level = _ais_freshness_level(age_minutes)
            items.append(
                VesselPositionMonitorItemResponse(
                    **item.model_dump(),
                    longitude=longitude,
                    latitude=latitude,
                    speed_kn=_to_decimal(position.get("speed_kn")),
                    course_deg=_to_decimal(position.get("course_deg")),
                    heading_deg=_to_decimal(position.get("heading_deg")),
                    position_time=position_time,
                    position_age_minutes=age_minutes,
                    city_code=resolved_city.city_code,
                    city_name=resolved_city.city_name,
                    current_city_code=resolved_city.city_code,
                    current_city_name=resolved_city.city_name,
                    current_city_source=resolved_city.current_city_source,
                    current_channel_code=resolved_channel.channel_code if resolved_channel else None,
                    current_channel_name=resolved_channel.channel_name if resolved_channel else None,
                    current_channel_source=resolved_channel.current_channel_source if resolved_channel else None,
                    city_center_longitude=resolved_city.city_center_longitude,
                    city_center_latitude=resolved_city.city_center_latitude,
                    matched_city_candidates=resolved_city.matched_city_candidates,
                    location_text=position.get("location_text"),
                    position_source_name="实时 ES",
                    source_index=position.get("source_index"),
                    freshness_level=freshness_level,
                    match_status_code=match_status_by_profile.get(item.id, "MATCHED_PROFILE"),
                )
            )
        matched_position_count = len(items)
        source_indices = sorted({str(position.get("source_index")) for position in positions.values() if position.get("source_index")})
        return _PositionBuildResult(
            items=items,
            partial=partial,
            error_message=error_message,
            failed_batch_count=failed_batch_count,
            queried_mmsi_count=len(mmsi_values),
            matched_position_count=matched_position_count,
            unpositioned_count=max(0, len(mmsi_values) - matched_position_count - invalid_position_count),
            invalid_position_count=invalid_position_count,
            unknown_city_count=unknown_city_count,
            unmatched_positions=unmatched_positions,
            invalid_positions=invalid_positions,
            source_indices=source_indices,
            failed_batches=failed_batches,
        )

    async def _position_monitor_items_from_recent_positions(
        self,
        query,
        *,
        generated_at: datetime,
        reported_within_minutes: int,
        max_hits: int,
        include_stale: bool,
    ) -> _PositionBuildResult:
        positions = await self._search_recent_realtime_positions(
            reported_within_minutes=reported_within_minutes,
            max_hits=max_hits,
        )
        if not positions:
            return _PositionBuildResult([], False, None, 0, 0, 0, 0, 0, 0)

        mmsi_values = sorted(positions)
        profiles_by_mmsi: dict[str, list[VesselProfile]] = defaultdict(list)
        profile_by_id: dict[int, VesselProfile] = {}
        chunk_size = 500
        for start in range(0, len(mmsi_values), chunk_size):
            chunk = mmsi_values[start:start + chunk_size]
            stmt = (
                self._position_monitor_profile_base_stmt(query)
                .where(VesselProfile.current_mmsi.in_(chunk))
                .group_by(VesselProfile.id)
            )
            rows = (await self.db.execute(stmt)).scalars().all()
            for profile in rows:
                profile_by_id[profile.id] = profile
                if profile.current_mmsi:
                    profiles_by_mmsi[str(profile.current_mmsi).strip()].append(profile)

        boundaries = await self._city_boundaries()
        boundary_grid = _CITY_BOUNDARY_CACHE.get("grid_index") or {}
        position_by_profile: dict[int, dict[str, Any]] = {}
        match_status_by_profile: dict[int, str] = {}
        freshness_limit = generated_at - timedelta(minutes=reported_within_minutes)
        unmatched_positions: list[dict[str, Any]] = []
        invalid_positions: list[dict[str, Any]] = []
        for mmsi, position in positions.items():
            longitude = _to_decimal(position.get("longitude"))
            latitude = _to_decimal(position.get("latitude"))
            position_time = position.get("position_time")
            valid_position = self._valid_longitude_latitude(longitude, latitude)
            matched_profiles = profiles_by_mmsi.get(mmsi) or []
            if not matched_profiles:
                age_minutes = int((generated_at - position_time).total_seconds() // 60) if position_time else None
                resolved_city = (
                    self._resolve_current_city_from_boundaries(longitude, latitude, boundaries, boundary_grid)
                    if valid_position
                    else _ResolvedCity(None, UNKNOWN_CITY_NAME, CURRENT_CITY_SOURCE_INVALID_POSITION)
                )
                unmatched_positions.append({
                    **position,
                    "mmsi": mmsi,
                    "longitude": longitude,
                    "latitude": latitude,
                    "position_age_minutes": age_minutes,
                    "freshness_level": _ais_freshness_level(age_minutes),
                    "match_status_code": "UNMATCHED_MMSI" if valid_position else "INVALID_POSITION",
                    "valid_position_flag": valid_position,
                    "city_code": resolved_city.city_code,
                    "city_name": resolved_city.city_name,
                    "current_city_source": resolved_city.current_city_source,
                })
                if not valid_position:
                    invalid_positions.append(unmatched_positions[-1])
                continue
            profile = matched_profiles[0]
            if profile.id in position_by_profile:
                continue
            if not include_stale and position_time and position_time < freshness_limit:
                continue
            position_by_profile[profile.id] = position
            match_status_by_profile[profile.id] = "MULTI_PROFILE_CONFLICT" if len(matched_profiles) > 1 else "MATCHED_PROFILE"

        positioned_profiles = [profile for profile_id, profile in profile_by_id.items() if profile_id in position_by_profile]
        list_items = await self._build_list_items(positioned_profiles)
        items: list[VesselPositionMonitorItemResponse] = []
        invalid_position_count = 0
        unknown_city_count = 0
        for item in list_items:
            position = position_by_profile.get(item.id)
            if position is None:
                continue
            longitude = _to_decimal(position.get("longitude"))
            latitude = _to_decimal(position.get("latitude"))
            if longitude is None or latitude is None or not self._valid_longitude_latitude(longitude, latitude):
                invalid_position_count += 1
                invalid_positions.append({**position, "mmsi": item.current_mmsi, "vessel_profile_id": item.id, "match_status_code": "INVALID_POSITION", "valid_position_flag": False})
                continue
            resolved_city = self._resolve_current_city_from_boundaries(longitude, latitude, boundaries, boundary_grid)
            if resolved_city.current_city_source != CURRENT_CITY_SOURCE_ADMIN_BOUNDARY:
                unknown_city_count += 1
            position_time = position.get("position_time")
            age_minutes = int((generated_at - position_time).total_seconds() // 60) if position_time else None
            freshness_level = _ais_freshness_level(age_minutes)
            items.append(
                VesselPositionMonitorItemResponse(
                    **item.model_dump(),
                    longitude=longitude,
                    latitude=latitude,
                    speed_kn=_to_decimal(position.get("speed_kn")),
                    course_deg=_to_decimal(position.get("course_deg")),
                    heading_deg=_to_decimal(position.get("heading_deg")),
                    position_time=position_time,
                    position_age_minutes=age_minutes,
                    city_code=resolved_city.city_code,
                    city_name=resolved_city.city_name,
                    current_city_code=resolved_city.city_code,
                    current_city_name=resolved_city.city_name,
                    current_city_source=resolved_city.current_city_source,
                    city_center_longitude=resolved_city.city_center_longitude,
                    city_center_latitude=resolved_city.city_center_latitude,
                    matched_city_candidates=resolved_city.matched_city_candidates,
                    location_text=position.get("location_text"),
                    position_source_name="实时 ES",
                    source_index=position.get("source_index"),
                    freshness_level=freshness_level,
                    match_status_code=match_status_by_profile.get(item.id, "MATCHED_PROFILE"),
                )
            )
        source_indices = sorted({str(position.get("source_index")) for position in positions.values() if position.get("source_index")})
        return _PositionBuildResult(
            items=items,
            partial=False,
            error_message=None,
            failed_batch_count=0,
            queried_mmsi_count=len(positions),
            matched_position_count=len(items),
            unpositioned_count=max(0, len(positions) - len(items) - invalid_position_count),
            invalid_position_count=invalid_position_count,
            unknown_city_count=unknown_city_count,
            unmatched_positions=unmatched_positions,
            invalid_positions=invalid_positions,
            source_indices=source_indices,
            failed_batches=[],
        )
