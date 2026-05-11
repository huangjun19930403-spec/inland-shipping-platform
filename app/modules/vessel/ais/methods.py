"""Implementation methods for the vessel ais domain."""

from __future__ import annotations

import math

from app.modules.vessel.shared import base as _base

globals().update({name: getattr(_base, name) for name in dir(_base) if not name.startswith("__")})


def _public_ais_error_message(error: Any) -> str | None:
    if error in (None, ""):
        return None
    text = str(error)
    lowered = text.lower()
    technical_markers = [
        "parse_exception",
        "failed to parse",
        "status=",
        "body=",
        "traceback",
        "exception",
    ]
    if any(marker in lowered for marker in technical_markers):
        return "部分实时 AIS 数据暂不可用，请稍后刷新或检查实时数据源配置"
    if len(text) > 120:
        return text[:117] + "..."
    return text


class VesselAisMixin:
    """Implementation methods for the vessel ais domain."""

    async def _realtime_es_host(self) -> str:
        value = await self.runtime_config.get_value(
            ES_R_HOST,
            settings.ES_R_HOST or "",
            profile_code=ES_REALTIME_CONFIG_PROFILE,
        )
        return (value or "").strip()

    async def _ais_runtime_limits(self) -> dict[str, int]:
        profile_limit = await self.runtime_config.get_int(
            VESSEL_AIS_PROFILE_LIMIT,
            int(settings.VESSEL_AIS_PROFILE_LIMIT or 2000),
            profile_code=ES_REALTIME_CONFIG_PROFILE,
        )
        batch_size = await self.runtime_config.get_int(
            VESSEL_AIS_ES_BATCH_SIZE,
            int(settings.VESSEL_AIS_ES_BATCH_SIZE or 500),
            profile_code=ES_REALTIME_CONFIG_PROFILE,
        )
        max_concurrency = await self.runtime_config.get_int(
            VESSEL_AIS_ES_MAX_CONCURRENCY,
            int(settings.VESSEL_AIS_ES_MAX_CONCURRENCY or 4),
            profile_code=ES_REALTIME_CONFIG_PROFILE,
        )
        unmatched_scan_limit = await self.runtime_config.get_int(
            VESSEL_AIS_UNMATCHED_SCAN_LIMIT,
            int(settings.VESSEL_AIS_UNMATCHED_SCAN_LIMIT or 1000),
            profile_code=ES_REALTIME_CONFIG_PROFILE,
        )
        return {
            "profile_limit": _safe_int(profile_limit, 2000, minimum=1, maximum=20000),
            "es_batch_size": _safe_int(batch_size, 500, minimum=1, maximum=2000),
            "es_max_concurrency": _safe_int(max_concurrency, 4, minimum=1, maximum=16),
            "unmatched_scan_limit": _safe_int(unmatched_scan_limit, 1000, minimum=1, maximum=10000),
        }

    async def _city_cache_backend(self) -> str:
        setting = _city_cache_backend_setting()
        if setting not in {"memory", "redis"}:
            raise AppException(
                "AIS 城市态势缓存配置非法，仅支持 redis 或 memory",
                code="VESSEL_AIS_CACHE_BACKEND_INVALID",
                status_code=503,
                detail={"cache_backend": setting},
            )
        shared_required = _city_shared_cache_required()
        if setting == "memory":
            if shared_required:
                raise AppException(
                    "生产环境 AIS 城市态势必须配置 Redis 快照缓存，禁止使用 memory",
                    code="VESSEL_AIS_MEMORY_CACHE_FORBIDDEN",
                    status_code=503,
                    detail={
                        "cache_backend": setting,
                        "app_env": getattr(settings, "APP_ENV", None),
                        "debug": getattr(settings, "DEBUG", None),
                    },
                )
            return "memory"
        if Redis is None:
            if shared_required:
                raise AppException(
                    "生产环境 AIS 城市态势 Redis 客户端不可用",
                    code="VESSEL_AIS_REDIS_UNAVAILABLE",
                    status_code=503,
                    detail={"cache_backend": setting},
                )
            logger.warning("city situation redis client unavailable; falling back to memory cache")
            return "memory"
        try:
            redis_client = await self._city_redis()
            if redis_client is not None:
                await redis_client.ping()
                return "redis"
        except Exception as exc:  # noqa: BLE001
            if shared_required:
                raise AppException(
                    "生产环境 AIS 城市态势 Redis 不可用",
                    code="VESSEL_AIS_REDIS_UNAVAILABLE",
                    status_code=503,
                    detail={"cache_backend": setting, "error": str(exc)},
                ) from exc
            logger.warning("city situation redis unavailable; falling back to memory cache: %s", exc)
        return "memory"

    async def _city_redis(self) -> Any | None:
        global _CITY_SITUATION_REDIS_CLIENT
        if Redis is None:
            return None
        if _CITY_SITUATION_REDIS_CLIENT is None:
            _CITY_SITUATION_REDIS_CLIENT = Redis.from_url(
                settings.CELERY_BROKER_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=0.25,
                socket_timeout=0.8,
            )
        return _CITY_SITUATION_REDIS_CLIENT

    async def _get_city_situation_response_cache(
        self,
        cache_key: str,
    ) -> tuple[VesselPositionCitySituationResponse, str] | None:
        now = datetime.utcnow()
        shared_required = _city_shared_cache_required()
        if await self._city_cache_backend() == "redis":
            try:
                redis_client = await self._city_redis()
                payload = await redis_client.get(CITY_SITUATION_CACHE_KEY_PREFIX + cache_key) if redis_client else None
                if payload:
                    return VesselPositionCitySituationResponse.model_validate_json(payload), "redis"
            except Exception as exc:  # noqa: BLE001
                logger.warning("city situation redis cache read failed: %s", exc)
            if shared_required:
                return None
        if shared_required:
            return None
        cached = _CITY_SITUATION_RESPONSE_CACHE.get(cache_key)
        if cached is None:
            return None
        if cached.expires_at <= now:
            _CITY_SITUATION_RESPONSE_CACHE.pop(cache_key, None)
            return None
        return cached.response.model_copy(deep=True), "memory"

    async def _store_city_situation_response_cache(
        self,
        cache_key: str,
        response: VesselPositionCitySituationResponse,
    ) -> None:
        ttl = _city_situation_cache_ttl()
        shared_required = _city_shared_cache_required()
        if await self._city_cache_backend() == "redis":
            try:
                redis_client = await self._city_redis()
                if redis_client is not None:
                    await redis_client.setex(CITY_SITUATION_CACHE_KEY_PREFIX + cache_key, ttl, response.model_dump_json())
                    return
            except Exception as exc:  # noqa: BLE001
                logger.warning("city situation redis cache write failed: %s", exc)
            if shared_required:
                return
        if shared_required:
            return
        _CITY_SITUATION_RESPONSE_CACHE[cache_key] = _CitySituationResponseCacheEntry(
            expires_at=datetime.utcnow() + timedelta(seconds=ttl),
            response=response.model_copy(deep=True),
        )

    async def _get_water_system_situation_response_cache(
        self,
        cache_key: str,
    ) -> tuple[VesselPositionWaterSystemSituationResponse, str] | None:
        now = datetime.utcnow()
        shared_required = _city_shared_cache_required()
        if await self._city_cache_backend() == "redis":
            try:
                redis_client = await self._city_redis()
                payload = await redis_client.get(WATER_SYSTEM_SITUATION_CACHE_KEY_PREFIX + cache_key) if redis_client else None
                if payload:
                    return VesselPositionWaterSystemSituationResponse.model_validate_json(payload), "redis"
            except Exception as exc:  # noqa: BLE001
                logger.warning("water system situation redis cache read failed: %s", exc)
            if shared_required:
                return None
        if shared_required:
            return None
        cached = _WATER_SYSTEM_SITUATION_RESPONSE_CACHE.get(cache_key)
        if cached is None:
            return None
        if cached.expires_at <= now:
            _WATER_SYSTEM_SITUATION_RESPONSE_CACHE.pop(cache_key, None)
            return None
        return cached.response.model_copy(deep=True), "memory"

    async def _store_water_system_situation_response_cache(
        self,
        cache_key: str,
        response: VesselPositionWaterSystemSituationResponse,
    ) -> None:
        ttl = _water_system_situation_cache_ttl()
        shared_required = _city_shared_cache_required()
        if await self._city_cache_backend() == "redis":
            try:
                redis_client = await self._city_redis()
                if redis_client is not None:
                    await redis_client.setex(WATER_SYSTEM_SITUATION_CACHE_KEY_PREFIX + cache_key, ttl, response.model_dump_json())
                    return
            except Exception as exc:  # noqa: BLE001
                logger.warning("water system situation redis cache write failed: %s", exc)
            if shared_required:
                return
        if shared_required:
            return
        _WATER_SYSTEM_SITUATION_RESPONSE_CACHE[cache_key] = _WaterSystemSituationResponseCacheEntry(
            expires_at=datetime.utcnow() + timedelta(seconds=ttl),
            response=response.model_copy(deep=True),
        )

    async def _get_city_vessels_response_cache(
        self,
        cache_key: str,
    ) -> tuple[VesselPositionCityVesselsResponse, str] | None:
        now = datetime.utcnow()
        shared_required = _city_shared_cache_required()
        if await self._city_cache_backend() == "redis":
            try:
                redis_client = await self._city_redis()
                payload = await redis_client.get(CITY_SITUATION_VESSELS_CACHE_KEY_PREFIX + cache_key) if redis_client else None
                if payload:
                    return VesselPositionCityVesselsResponse.model_validate_json(payload), "redis"
            except Exception as exc:  # noqa: BLE001
                logger.warning("city situation vessels redis cache read failed: %s", exc)
            if shared_required:
                return None
        if shared_required:
            return None
        cached = _CITY_SITUATION_VESSELS_RESPONSE_CACHE.get(cache_key)
        if cached is None:
            return None
        if cached.expires_at <= now:
            _CITY_SITUATION_VESSELS_RESPONSE_CACHE.pop(cache_key, None)
            return None
        return cached.response.model_copy(deep=True), "memory"

    async def _store_city_vessels_response_cache(
        self,
        cache_key: str,
        response: VesselPositionCityVesselsResponse,
    ) -> None:
        ttl = _city_snapshot_ttl()
        shared_required = _city_shared_cache_required()
        if await self._city_cache_backend() == "redis":
            try:
                redis_client = await self._city_redis()
                if redis_client is not None:
                    await redis_client.setex(CITY_SITUATION_VESSELS_CACHE_KEY_PREFIX + cache_key, ttl, response.model_dump_json())
                    return
            except Exception as exc:  # noqa: BLE001
                logger.warning("city situation vessels redis cache write failed: %s", exc)
            if shared_required:
                return
        if shared_required:
            return
        _CITY_SITUATION_VESSELS_RESPONSE_CACHE[cache_key] = _CitySituationVesselsResponseCacheEntry(
            expires_at=datetime.utcnow() + timedelta(seconds=ttl),
            response=response.model_copy(deep=True),
        )

    async def _get_water_system_vessels_response_cache(
        self,
        cache_key: str,
    ) -> tuple[VesselPositionWaterSystemVesselsResponse, str] | None:
        now = datetime.utcnow()
        shared_required = _city_shared_cache_required()
        if await self._city_cache_backend() == "redis":
            try:
                redis_client = await self._city_redis()
                payload = await redis_client.get(WATER_SYSTEM_SITUATION_VESSELS_CACHE_KEY_PREFIX + cache_key) if redis_client else None
                if payload:
                    return VesselPositionWaterSystemVesselsResponse.model_validate_json(payload), "redis"
            except Exception as exc:  # noqa: BLE001
                logger.warning("water system situation vessels redis cache read failed: %s", exc)
            if shared_required:
                return None
        if shared_required:
            return None
        cached = _WATER_SYSTEM_SITUATION_VESSELS_RESPONSE_CACHE.get(cache_key)
        if cached is None:
            return None
        if cached.expires_at <= now:
            _WATER_SYSTEM_SITUATION_VESSELS_RESPONSE_CACHE.pop(cache_key, None)
            return None
        return cached.response.model_copy(deep=True), "memory"

    async def _store_water_system_vessels_response_cache(
        self,
        cache_key: str,
        response: VesselPositionWaterSystemVesselsResponse,
    ) -> None:
        ttl = _city_snapshot_ttl()
        shared_required = _city_shared_cache_required()
        if await self._city_cache_backend() == "redis":
            try:
                redis_client = await self._city_redis()
                if redis_client is not None:
                    await redis_client.setex(WATER_SYSTEM_SITUATION_VESSELS_CACHE_KEY_PREFIX + cache_key, ttl, response.model_dump_json())
                    return
            except Exception as exc:  # noqa: BLE001
                logger.warning("water system situation vessels redis cache write failed: %s", exc)
            if shared_required:
                return
        if shared_required:
            return
        _WATER_SYSTEM_SITUATION_VESSELS_RESPONSE_CACHE[cache_key] = _WaterSystemSituationVesselsResponseCacheEntry(
            expires_at=datetime.utcnow() + timedelta(seconds=ttl),
            response=response.model_copy(deep=True),
        )

    async def _city_situation_allows_seed_snapshot(self) -> bool:
        return not bool(await self._realtime_es_host())

    async def _summary_ais_payload(self, profile: VesselProfile, now: datetime) -> dict[str, Any]:
        if not profile.current_mmsi:
            return {
                "latest_position_time": None,
                "latest_city_code": None,
                "latest_city_name": None,
                "ais_freshness_level": "UNKNOWN",
                "ais_unavailable_reason": "无 MMSI，无法查询实时 AIS",
            }
        if not await self._realtime_es_host():
            return {
                "latest_position_time": None,
                "latest_city_code": None,
                "latest_city_name": None,
                "ais_freshness_level": "UNKNOWN",
                "ais_unavailable_reason": "实时 ES 未配置，AIS 新鲜度未知",
            }
        try:
            positions, partial, error_message, _, _ = await self._search_realtime_positions_batched(
                [profile.current_mmsi],
                batch_size=1,
                max_concurrency=1,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "latest_position_time": None,
                "latest_city_code": None,
                "latest_city_name": None,
                "ais_freshness_level": "UNKNOWN",
                "ais_unavailable_reason": f"实时 AIS 查询失败：{str(exc)[:160]}",
            }
        position = positions.get(profile.current_mmsi)
        if not position:
            reason = error_message if partial and error_message else "暂无实时船位"
            return {
                "latest_position_time": None,
                "latest_city_code": None,
                "latest_city_name": None,
                "ais_freshness_level": "UNKNOWN",
                "ais_unavailable_reason": reason,
            }
        position_time = position.get("position_time")
        age_minutes = int((now - position_time).total_seconds() // 60) if position_time else None
        latest_city_code = None
        latest_city_name = None
        longitude = _to_decimal(position.get("longitude"))
        latitude = _to_decimal(position.get("latitude"))
        if longitude is not None and latitude is not None and self._valid_longitude_latitude(longitude, latitude):
            boundaries = await self._city_boundaries()
            resolved_city = self._resolve_current_city_from_boundaries(longitude, latitude, boundaries, _CITY_BOUNDARY_CACHE.get("grid_index") or {})
            latest_city_code = resolved_city.city_code
            latest_city_name = resolved_city.city_name
        return {
            "latest_position_time": position_time,
            "latest_city_code": latest_city_code,
            "latest_city_name": latest_city_name,
            "ais_freshness_level": _ais_freshness_level(age_minutes),
            "ais_unavailable_reason": error_message if partial and error_message else None,
        }

    async def position_monitor(self, query) -> VesselPositionMonitorResponse:
        generated_at = datetime.utcnow()
        profiles = await self._position_monitor_profiles(query)
        if not profiles:
            return self._empty_position_response(generated_at, "未匹配到符合条件的船舶档案")
        if not await self._realtime_es_host():
            return VesselPositionMonitorResponse(
                source_status="UNCONFIGURED",
                source_status_name=_source_status_name("UNCONFIGURED"),
                generated_at=generated_at,
                message="实时 ES 未配置，暂无可展示船位",
                summary=VesselPositionMonitorSummary(
                    matched_profile_count=len(profiles),
                    positioned_count=0,
                    stale_position_count=0,
                    contactable_position_count=0,
                ),
                items=[],
            )
        mmsi_by_profile = await self._mmsi_values_by_profile([row.id for row in profiles])
        mmsi_values = sorted({item for values in mmsi_by_profile.values() for item in values if item})
        if not mmsi_values:
            return self._empty_position_response(generated_at, "匹配船舶缺少可用于实时查询的 MMSI", len(profiles))
        limits = await self._ais_runtime_limits()
        result = await self._position_monitor_items_for_profiles(
            profiles,
            generated_at=generated_at,
            reported_within_minutes=query.reported_within_minutes or 1440,
            es_batch_size=limits["es_batch_size"],
            es_max_concurrency=limits["es_max_concurrency"],
            include_stale=True,
        )
        if not result.items and not result.partial:
            return self._empty_position_response(generated_at, "实时 ES 未返回匹配船位", len(profiles))
        fresh_items = [
            item for item in result.items
            if not self._is_stale_position(item, generated_at, query.reported_within_minutes or 1440)
        ][:query.max_items]
        return VesselPositionMonitorResponse(
            source_status="ERROR" if result.partial and not fresh_items else ("AVAILABLE" if fresh_items else "EMPTY"),
            source_status_name=_source_status_name("ERROR" if result.partial and not fresh_items else ("AVAILABLE" if fresh_items else "EMPTY")),
            generated_at=generated_at,
            message=result.error_message if result.partial else (None if fresh_items else "实时 ES 暂无符合筛选条件的船位"),
            summary=VesselPositionMonitorSummary(
                matched_profile_count=len(profiles),
                positioned_count=len(fresh_items),
                stale_position_count=max(0, len(result.items) - len(fresh_items)),
                contactable_position_count=sum(1 for item in fresh_items if item.contact_available),
                unmatched_mmsi_count=0,
                invalid_position_count=len(result.invalid_positions),
                coverage_rate=self._coverage_rate(result.matched_position_count, result.queried_mmsi_count),
                freshness_distribution=self._position_freshness_distribution(result.items),
            ),
            items=fresh_items,
        )

    async def position_city_situation(self, query) -> VesselPositionCitySituationResponse:
        generated_at = datetime.utcnow()
        cache_key = _city_situation_query_cache_key(query)
        cache_backend = await self._city_cache_backend()
        force_refresh = bool(getattr(query, "force_refresh", False))
        if not force_refresh:
            cached = await self._get_city_situation_response_cache(cache_key)
            if cached is not None:
                cached_response, cache_backend = cached
                cached_snapshot_backend = str(cached_response.snapshot_backend or "").lower()
                if cached_snapshot_backend == "seed" and not await self._city_situation_allows_seed_snapshot():
                    logger.info("ignore seed AIS city situation cache because realtime ES is configured")
                else:
                    return cached_response.model_copy(
                        update={
                            "cache_status": "HIT",
                            "cache_generated_at": cached_response.generated_at,
                            "is_stale_cache": False,
                            "snapshot_backend": cache_backend,
                            "cache_backend_note": "memory 仅适合本地开发；生产多实例请配置 Redis" if cache_backend == "memory" else None,
                        },
                        deep=True,
                    )
        limits = await self._ais_runtime_limits()
        profile_limit = limits["profile_limit"]
        es_batch_size = limits["es_batch_size"]
        es_max_concurrency = limits["es_max_concurrency"]
        unmatched_scan_limit = limits["unmatched_scan_limit"]
        total_profile_count = await self._position_monitor_profile_count(query)
        profiles = await self._position_monitor_profiles(query, limit=profile_limit)
        unscanned_profile_count = max(0, (total_profile_count or len(profiles)) - len(profiles))
        if not profiles:
            return VesselPositionCitySituationResponse(
                source_status="EMPTY",
                source_status_name=_source_status_name("EMPTY"),
                generated_at=generated_at,
                message="未匹配到符合条件的船舶档案",
                cache_status="MISS",
                cache_generated_at=generated_at,
                is_stale_cache=False,
                snapshot_backend=cache_backend,
                cache_backend_note="memory 仅适合本地开发；生产多实例请配置 Redis" if cache_backend == "memory" else None,
                summary=VesselPositionCitySituationSummary(
                    matched_profile_count=0,
                    scanned_profile_count=0,
                    unscanned_profile_count=0,
                    queried_mmsi_count=0,
                    matched_position_count=0,
                    unpositioned_count=0,
                    invalid_position_count=0,
                    unknown_city_count=0,
                    positioned_count=0,
                    stale_position_count=0,
                    contactable_position_count=0,
                    certificate_risk_count=0,
                    city_count=0,
                    query_snapshot_id=None,
                ),
                cities=[],
            )
        if not await self._realtime_es_host():
            return VesselPositionCitySituationResponse(
                source_status="UNCONFIGURED",
                source_status_name=_source_status_name("UNCONFIGURED"),
                generated_at=generated_at,
                message="实时 ES 未配置，暂无城市态势",
                cache_status="MISS",
                cache_generated_at=generated_at,
                is_stale_cache=False,
                snapshot_backend=cache_backend,
                cache_backend_note="memory 仅适合本地开发；生产多实例请配置 Redis" if cache_backend == "memory" else None,
                summary=VesselPositionCitySituationSummary(
                    matched_profile_count=total_profile_count or len(profiles),
                    scanned_profile_count=len(profiles),
                    unscanned_profile_count=unscanned_profile_count,
                    queried_mmsi_count=0,
                    matched_position_count=0,
                    unpositioned_count=0,
                    invalid_position_count=0,
                    unknown_city_count=0,
                    positioned_count=0,
                    stale_position_count=0,
                    contactable_position_count=0,
                    certificate_risk_count=0,
                    city_count=0,
                    query_snapshot_id=None,
                ),
                cities=[],
            )
        result = await self._position_monitor_items_for_profiles(
            profiles,
            generated_at=generated_at,
            reported_within_minutes=query.reported_within_minutes or 1440,
            es_batch_size=es_batch_size,
            es_max_concurrency=es_max_concurrency,
            include_stale=True,
            include_unmatched=False,
            unmatched_scan_limit=0,
        )
        partial = result.partial
        error_message = _public_ais_error_message(result.error_message)
        if unscanned_profile_count > 0:
            partial = True
            error_parts = [part for part in [error_message, f"服务端按扫描上限统计，未扫描档案 {unscanned_profile_count} 艘"] if part]
            error_message = "；".join(error_parts) or None
        risk_by_profile = await self._compliance_risk_by_profile([item.id for item in result.items])
        boundaries = await self._city_boundaries()
        boundary_codes = {boundary.code for boundary in boundaries}
        boundary_paths_by_code = self._city_boundary_paths_by_code(boundaries, query.boundary_precision) if query.include_boundary else {}
        cities = self._city_situation_items(
            result.items,
            risk_by_profile,
            generated_at,
            query.reported_within_minutes or 1440,
            result.queried_mmsi_count,
            result.matched_position_count,
            result.unpositioned_count,
            result.invalid_position_count,
            result.unknown_city_count,
            partial,
            error_message,
            boundary_paths_by_code,
            query.boundary_precision if query.include_boundary else None,
            boundary_codes,
            result.unmatched_positions,
        )
        missing_boundary_cities = [
            {
                "city_code": city.city_code,
                "city_name": city.city_name,
                "positioned_count": city.positioned_count,
            }
            for city in cities
            if city.city_code and city.positioned_count > 0 and not city.has_boundary
        ]
        snapshot_id = await self._store_city_situation_snapshot(
            result.items,
            generated_at=generated_at,
            partial=partial,
            error_message=error_message,
        )
        positioned_items = [item for item in result.items if not self._is_stale_position(item, generated_at, query.reported_within_minutes or 1440)]
        freshness_distribution = self._position_freshness_distribution(result.items, result.unmatched_positions)
        coverage_rate = self._coverage_rate(result.matched_position_count, result.queried_mmsi_count)
        uncertainty_notes: list[str] = []
        if cache_backend == "memory":
            uncertainty_notes.append("当前城市态势快照使用本机内存缓存，多实例部署时建议使用 Redis")
        if partial:
            uncertainty_notes.append("本次 AIS 态势为部分结果")
        if result.unmatched_positions:
            uncertainty_notes.append(f"发现未匹配 MMSI {len(result.unmatched_positions)} 个")
        if result.invalid_positions:
            uncertainty_notes.append(f"发现无效点位 {len(result.invalid_positions)} 条")
        if result.source_indices:
            uncertainty_notes.append(f"实时 ES 来源索引：{', '.join(result.source_indices[:5])}")
        snapshot_expires_at = generated_at + timedelta(seconds=_city_snapshot_ttl())
        response_status = "PARTIAL" if partial and cities else ("ERROR" if partial and not cities else ("AVAILABLE" if cities else "EMPTY"))
        response = VesselPositionCitySituationResponse(
            source_status=response_status,
            source_status_name=_source_status_name(response_status),
            generated_at=generated_at,
            message=error_message if partial else (None if cities else "实时 ES 暂无符合筛选条件的城市态势"),
            cache_status="MISS",
            cache_generated_at=generated_at,
            is_stale_cache=False,
            snapshot_backend=cache_backend,
            cache_backend_note="memory 仅适合本地开发；生产多实例请配置 Redis" if cache_backend == "memory" else None,
            summary=VesselPositionCitySituationSummary(
                matched_profile_count=total_profile_count or len(profiles),
                scanned_profile_count=len(profiles),
                unscanned_profile_count=unscanned_profile_count,
                queried_mmsi_count=result.queried_mmsi_count,
                matched_position_count=result.matched_position_count,
                unmatched_mmsi_count=len([item for item in result.unmatched_positions if item.get("match_status_code") == "UNMATCHED_MMSI"]),
                unpositioned_count=result.unpositioned_count,
                invalid_position_count=len(result.invalid_positions),
                unknown_city_count=result.unknown_city_count + len([item for item in result.unmatched_positions if not item.get("city_code")]),
                positioned_count=len(positioned_items),
                stale_position_count=len(result.items) - len(positioned_items),
                contactable_position_count=sum(1 for item in positioned_items if item.contact_available),
                certificate_risk_count=sum(1 for item in positioned_items if risk_by_profile.get(item.id)),
                city_count=sum(1 for city in cities if city.city_code),
                boundary_city_count=sum(1 for city in cities if city.city_code and city.has_boundary),
                missing_boundary_city_count=len(missing_boundary_cities),
                missing_boundary_cities=missing_boundary_cities,
                query_snapshot_id=snapshot_id,
                snapshot_status_code="PARTIAL" if partial else "READY",
                snapshot_expires_at=snapshot_expires_at,
                refresh_required=False,
                coverage_rate=coverage_rate,
                freshness_distribution=freshness_distribution,
                source_indices=result.source_indices,
                uncertainty_notes=uncertainty_notes,
                failed_batch_count=result.failed_batch_count,
                failed_batches=getattr(result, "failed_batches", []),
                is_partial=partial,
                error_message=error_message,
            ),
            cities=cities,
        )
        await self._store_city_situation_response_cache(cache_key, response)
        return response

    async def position_city_vessels(self, query) -> VesselPositionCityVesselsResponse:
        if not query.query_snapshot_id:
            return VesselPositionCityVesselsResponse(
                total=0,
                page=query.page,
                page_size=query.page_size,
                items=[],
                query_snapshot_id=None,
                snapshot_hit=False,
                refresh_required=True,
                snapshot_status_code="MISSING",
                is_partial=False,
                error_message="城市下钻必须带 query_snapshot_id，请先刷新 AIS 城市态势",
            )
        cache_key = _situation_vessels_query_cache_key(query)
        cached = await self._get_city_vessels_response_cache(cache_key)
        if cached is not None:
            cached_response, _cache_backend = cached
            return cached_response.model_copy(
                update={"snapshot_hit": True, "refresh_required": False},
                deep=True,
            )
        snapshot = await self._get_city_situation_snapshot(query.query_snapshot_id)
        snapshot_hit = snapshot is not None
        if not snapshot or snapshot.refresh_required or snapshot.status_code == "EXPIRED":
            return VesselPositionCityVesselsResponse(
                total=0,
                page=query.page,
                page_size=query.page_size,
                items=[],
                query_snapshot_id=query.query_snapshot_id,
                snapshot_hit=False,
                refresh_required=True,
                snapshot_status_code="EXPIRED",
                is_partial=False,
                error_message="SNAPSHOT_EXPIRED",
            )
        items = [
            item for item in snapshot.items
            if not self._is_stale_position(item, snapshot.generated_at, query.reported_within_minutes or 1440)
        ]
        partial = snapshot.partial
        error_message = snapshot.error_message
        snapshot_id = snapshot.snapshot_id
        filtered = [
            item for item in items
            if self._city_matches(item, city_code=query.city_code, city_name=query.city_name)
        ]
        start = (query.page - 1) * query.page_size
        response = VesselPositionCityVesselsResponse(
            total=len(filtered),
            page=query.page,
            page_size=query.page_size,
            items=filtered[start:start + query.page_size],
            query_snapshot_id=snapshot_id,
            snapshot_hit=snapshot_hit,
            refresh_required=False,
            snapshot_status_code=snapshot.status_code,
            is_partial=partial,
            error_message=error_message,
        )
        await self._store_city_vessels_response_cache(cache_key, response)
        return response

    async def ais_city_boundaries(self, query) -> VesselAisCityBoundaryResponse:
        precision = getattr(query, "precision", "low") or "low"
        requested_codes: set[str] = set()
        city_code = getattr(query, "city_code", None)
        city_codes = getattr(query, "city_codes", None)
        if city_code:
            requested_codes.add(str(city_code).strip())
        if city_codes:
            requested_codes.update(code.strip() for code in str(city_codes).split(",") if code.strip())
        boundaries = await self._city_boundaries()
        items: list[VesselAisCityBoundaryItemResponse] = []
        for boundary in boundaries:
            if requested_codes and boundary.code not in requested_codes:
                continue
            paths = (boundary.boundary_paths_by_precision or {}).get(precision) or _boundary_paths_for_precision(boundary.polygons, precision)
            items.append(
                VesselAisCityBoundaryItemResponse(
                    city_code=boundary.code,
                    city_name=boundary.name,
                    boundary_paths=_serialize_boundary_paths(paths) or [],
                    has_boundary=bool(paths),
                    boundary_precision=precision,
                    boundary_status_code="AVAILABLE" if paths else "MISSING",
                    city_center_longitude=boundary.center_longitude,
                    city_center_latitude=boundary.center_latitude,
                )
            )
        missing = sorted(requested_codes - {item.city_code for item in items})
        return VesselAisCityBoundaryResponse(
            generated_at=datetime.utcnow(),
            boundary_version_id=self._city_boundary_version_id(),
            precision=precision,
            total=len(items),
            items=items,
            uncertainty_notes=[f"缺少城市边界：{', '.join(missing)}"] if missing else [],
        )

    async def position_water_system_situation(self, query) -> VesselPositionWaterSystemSituationResponse:
        generated_at = datetime.utcnow()
        cache_key = _water_system_situation_query_cache_key(query)
        cache_backend = await self._city_cache_backend()
        force_refresh = bool(getattr(query, "force_refresh", False))
        if not force_refresh:
            cached = await self._get_water_system_situation_response_cache(cache_key)
            if cached is not None:
                cached_response, cache_backend = cached
                return cached_response.model_copy(
                    update={
                        "cache_status": "HIT",
                        "cache_generated_at": cached_response.generated_at,
                        "is_stale_cache": False,
                        "snapshot_backend": cache_backend,
                        "cache_backend_note": "memory 仅适合本地开发；生产多实例请配置 Redis" if cache_backend == "memory" else None,
                    },
                    deep=True,
                )
        levels = self._water_system_query_levels(query)
        navigation_scope_codes = self._water_system_query_code_set(query, "navigation_scope_codes")
        navigation_category_codes = self._water_system_query_code_set(query, "navigation_category_codes")
        limits = await self._ais_runtime_limits()
        profile_limit = limits["profile_limit"]
        es_batch_size = limits["es_batch_size"]
        es_max_concurrency = limits["es_max_concurrency"]
        total_profile_count = await self._position_monitor_profile_count(query)
        profiles = await self._position_monitor_profiles(query, limit=profile_limit)
        unscanned_profile_count = max(0, (total_profile_count or len(profiles)) - len(profiles))
        if not profiles:
            water_systems: list[VesselPositionWaterSystemSituationItemResponse] = []
            if bool(getattr(query, "include_empty_water_systems", True)):
                filtered_boundaries = self._filter_water_boundaries(
                    await self._water_system_boundaries(),
                    levels,
                    getattr(query, "water_system_name", None),
                    navigation_scope_codes,
                    navigation_category_codes,
                )
                water_systems = self._water_system_situation_items(
                    [],
                    {},
                    {},
                    generated_at,
                    query.reported_within_minutes or 1440,
                    0,
                    0,
                    0,
                    0,
                    False,
                    None,
                    filtered_boundaries,
                    {},
                    None,
                    True,
                )
            return VesselPositionWaterSystemSituationResponse(
                source_status="EMPTY",
                source_status_name=_source_status_name("EMPTY"),
                generated_at=generated_at,
                message="未匹配到符合条件的船舶档案",
                cache_status="MISS",
                cache_generated_at=generated_at,
                is_stale_cache=False,
                snapshot_backend=cache_backend,
                cache_backend_note="memory 仅适合本地开发；生产多实例请配置 Redis" if cache_backend == "memory" else None,
                summary=VesselPositionWaterSystemSituationSummary(
                    matched_profile_count=0,
                    scanned_profile_count=0,
                    unscanned_profile_count=0,
                    queried_mmsi_count=0,
                    matched_position_count=0,
                    unpositioned_count=0,
                    positioned_count=0,
                    stale_position_count=0,
                    contactable_position_count=0,
                    certificate_risk_count=0,
                    water_system_count=sum(1 for item in water_systems if item.water_system_code),
                    boundary_water_system_count=sum(1 for item in water_systems if item.water_system_code and item.has_boundary),
                    missing_boundary_water_system_count=sum(1 for item in water_systems if item.water_system_code and not item.has_boundary),
                ),
                water_systems=water_systems,
            )
        if not await self._realtime_es_host():
            water_systems: list[VesselPositionWaterSystemSituationItemResponse] = []
            if bool(getattr(query, "include_empty_water_systems", True)):
                filtered_boundaries = self._filter_water_boundaries(
                    await self._water_system_boundaries(),
                    levels,
                    getattr(query, "water_system_name", None),
                    navigation_scope_codes,
                    navigation_category_codes,
                )
                water_systems = self._water_system_situation_items(
                    [],
                    {},
                    {},
                    generated_at,
                    query.reported_within_minutes or 1440,
                    0,
                    0,
                    0,
                    0,
                    False,
                    None,
                    filtered_boundaries,
                    {},
                    None,
                    True,
                )
            return VesselPositionWaterSystemSituationResponse(
                source_status="UNCONFIGURED",
                source_status_name=_source_status_name("UNCONFIGURED"),
                generated_at=generated_at,
                message="实时 ES 未配置，暂无水系态势",
                cache_status="MISS",
                cache_generated_at=generated_at,
                is_stale_cache=False,
                snapshot_backend=cache_backend,
                cache_backend_note="memory 仅适合本地开发；生产多实例请配置 Redis" if cache_backend == "memory" else None,
                summary=VesselPositionWaterSystemSituationSummary(
                    matched_profile_count=total_profile_count or len(profiles),
                    scanned_profile_count=len(profiles),
                    unscanned_profile_count=unscanned_profile_count,
                    queried_mmsi_count=0,
                    matched_position_count=0,
                    unpositioned_count=0,
                    positioned_count=0,
                    stale_position_count=0,
                    contactable_position_count=0,
                    certificate_risk_count=0,
                    water_system_count=sum(1 for item in water_systems if item.water_system_code),
                    boundary_water_system_count=sum(1 for item in water_systems if item.water_system_code and item.has_boundary),
                    missing_boundary_water_system_count=sum(1 for item in water_systems if item.water_system_code and not item.has_boundary),
                ),
                water_systems=water_systems,
            )
        result = await self._position_monitor_items_for_profiles(
            profiles,
            generated_at=generated_at,
            reported_within_minutes=query.reported_within_minutes or 1440,
            es_batch_size=es_batch_size,
            es_max_concurrency=es_max_concurrency,
            include_stale=True,
            include_unmatched=False,
            unmatched_scan_limit=0,
        )
        partial = result.partial
        error_message = _public_ais_error_message(result.error_message)
        if unscanned_profile_count > 0:
            partial = True
            parts = [part for part in [error_message, f"服务端按扫描上限统计，未扫描档案 {unscanned_profile_count} 艘"] if part]
            error_message = "；".join(parts) or None
        risk_by_profile = await self._compliance_risk_by_profile([item.id for item in result.items])
        summary_risk_by_profile = await self._summary_risk_level_by_profile([item.id for item in result.items])
        items = self._filter_water_situation_items_by_risk(result.items, query, risk_by_profile, summary_risk_by_profile)
        boundaries = await self._water_system_boundaries()
        filtered_boundaries = self._filter_water_boundaries(
            boundaries,
            levels,
            getattr(query, "water_system_name", None),
            navigation_scope_codes,
            navigation_category_codes,
        )
        boundary_paths_by_code = (
            self._water_boundary_paths_by_code(filtered_boundaries, query.boundary_precision)
            if query.include_boundary
            else {}
        )
        water_systems = self._water_system_situation_items(
            items,
            risk_by_profile,
            summary_risk_by_profile,
            generated_at,
            query.reported_within_minutes or 1440,
            result.queried_mmsi_count,
            result.matched_position_count,
            result.unpositioned_count,
            result.invalid_position_count,
            partial,
            error_message,
            filtered_boundaries,
            boundary_paths_by_code,
            query.boundary_precision if query.include_boundary else None,
            bool(getattr(query, "include_empty_water_systems", True)),
        )
        snapshot_id = await self._store_city_situation_snapshot(
            result.items,
            generated_at=generated_at,
            partial=partial,
            error_message=error_message,
        )
        positioned_items = [item for item in items if not self._is_stale_position(item, generated_at, query.reported_within_minutes or 1440)]
        freshness_distribution = self._position_freshness_distribution(items)
        coverage_rate = self._coverage_rate(result.matched_position_count, result.queried_mmsi_count)
        uncertainty_notes: list[str] = []
        if cache_backend == "memory":
            uncertainty_notes.append("当前水系态势快照使用本机内存缓存，多实例部署时建议使用 Redis")
        if partial:
            uncertainty_notes.append("本次 AIS 水系态势为部分结果")
        if result.invalid_positions:
            uncertainty_notes.append(f"发现无效点位 {len(result.invalid_positions)} 条")
        if result.source_indices:
            uncertainty_notes.append(f"实时 ES 来源索引：{', '.join(result.source_indices[:5])}")
        snapshot_expires_at = generated_at + timedelta(seconds=_city_snapshot_ttl())
        response_status = "PARTIAL" if partial and water_systems else ("ERROR" if partial and not water_systems else ("AVAILABLE" if water_systems else "EMPTY"))
        response = VesselPositionWaterSystemSituationResponse(
            source_status=response_status,
            source_status_name=_source_status_name(response_status),
            generated_at=generated_at,
            message=error_message if partial else (None if water_systems else "实时 ES 暂无符合筛选条件的水系态势"),
            cache_status="MISS",
            cache_generated_at=generated_at,
            is_stale_cache=False,
            snapshot_backend=cache_backend,
            cache_backend_note="memory 仅适合本地开发；生产多实例请配置 Redis" if cache_backend == "memory" else None,
            summary=VesselPositionWaterSystemSituationSummary(
                matched_profile_count=total_profile_count or len(profiles),
                scanned_profile_count=len(profiles),
                unscanned_profile_count=unscanned_profile_count,
                queried_mmsi_count=result.queried_mmsi_count,
                matched_position_count=result.matched_position_count,
                unmatched_mmsi_count=0,
                unpositioned_count=result.unpositioned_count,
                invalid_position_count=len(result.invalid_positions),
                unknown_water_system_count=sum(item.positioned_count for item in water_systems if not item.water_system_code),
                positioned_count=len(positioned_items),
                stale_position_count=len(items) - len(positioned_items),
                contactable_position_count=sum(1 for item in positioned_items if item.contact_available),
                certificate_risk_count=sum(1 for item in positioned_items if risk_by_profile.get(item.id, {}).get("has_certificate_risk")),
                high_risk_count=sum(1 for item in positioned_items if summary_risk_by_profile.get(item.id) == "HIGH"),
                water_system_count=sum(1 for item in water_systems if item.water_system_code),
                boundary_water_system_count=sum(1 for item in water_systems if item.water_system_code and item.has_boundary),
                missing_boundary_water_system_count=sum(1 for item in water_systems if item.water_system_code and not item.has_boundary),
                query_snapshot_id=snapshot_id,
                snapshot_status_code="PARTIAL" if partial else "READY",
                snapshot_expires_at=snapshot_expires_at,
                refresh_required=False,
                coverage_rate=coverage_rate,
                freshness_distribution=freshness_distribution,
                source_indices=result.source_indices,
                uncertainty_notes=uncertainty_notes,
                failed_batch_count=result.failed_batch_count,
                failed_batches=getattr(result, "failed_batches", []),
                is_partial=partial,
                error_message=error_message,
            ),
            water_systems=water_systems,
        )
        await self._store_water_system_situation_response_cache(cache_key, response)
        return response

    async def position_water_system_vessels(self, query) -> VesselPositionWaterSystemVesselsResponse:
        if not query.query_snapshot_id:
            return VesselPositionWaterSystemVesselsResponse(
                total=0,
                page=query.page,
                page_size=query.page_size,
                items=[],
                query_snapshot_id=None,
                snapshot_hit=False,
                refresh_required=True,
                snapshot_status_code="MISSING",
                is_partial=False,
                error_message="水系下钻必须带 query_snapshot_id，请先刷新 AIS 水系态势",
            )
        cache_key = _situation_vessels_query_cache_key(query)
        cached = await self._get_water_system_vessels_response_cache(cache_key)
        if cached is not None:
            cached_response, _cache_backend = cached
            return cached_response.model_copy(
                update={"snapshot_hit": True, "refresh_required": False},
                deep=True,
            )
        snapshot = await self._get_city_situation_snapshot(query.query_snapshot_id)
        snapshot_hit = snapshot is not None
        if not snapshot or snapshot.refresh_required or snapshot.status_code == "EXPIRED":
            return VesselPositionWaterSystemVesselsResponse(
                total=0,
                page=query.page,
                page_size=query.page_size,
                items=[],
                query_snapshot_id=query.query_snapshot_id,
                snapshot_hit=False,
                refresh_required=True,
                snapshot_status_code="EXPIRED",
                is_partial=False,
                error_message="SNAPSHOT_EXPIRED",
            )
        boundaries = await self._water_system_boundaries()
        levels = self._water_system_query_levels(query)
        boundary_keyword = getattr(query, "water_system_name", None)
        if getattr(query, "water_system_code", None) == UNKNOWN_WATER_SYSTEM_CODE or boundary_keyword == UNKNOWN_WATER_SYSTEM_NAME:
            boundary_keyword = None
        filtered_boundaries = self._filter_water_boundaries(
            boundaries,
            levels,
            boundary_keyword,
            self._water_system_query_code_set(query, "navigation_scope_codes"),
            self._water_system_query_code_set(query, "navigation_category_codes"),
        )
        items = [
            item for item in snapshot.items
            if not self._is_stale_position(item, snapshot.generated_at, query.reported_within_minutes or 1440)
        ]
        risk_by_profile = await self._compliance_risk_by_profile([item.id for item in items])
        summary_risk_by_profile = await self._summary_risk_level_by_profile([item.id for item in items])
        items = self._filter_water_situation_items_by_risk(items, query, risk_by_profile, summary_risk_by_profile)
        matched_items: list[tuple[VesselPositionMonitorItemResponse, _ResolvedWaterSystem | None]] = []
        for item in items:
            match = self._water_system_match_for_position(
                item,
                water_system_code=query.water_system_code,
                water_system_name=query.water_system_name,
                boundaries=filtered_boundaries,
            )
            if match is not False:
                matched_items.append((item, match))
        enriched = [
            item.model_copy(
                update={
                    "risk_level": summary_risk_by_profile.get(item.id),
                    "certificate_risk_available": bool(risk_by_profile.get(item.id, {}).get("has_certificate_risk")),
                    "current_water_system_code": match.water_system_code if match else None,
                    "current_water_system_name": match.water_system_name if match else None,
                    "current_water_system_source": match.current_water_system_source if match else None,
                    "water_system_match_distance_m": match.match_distance_m if match else None,
                }
            )
            for item, match in matched_items
        ]
        start = (query.page - 1) * query.page_size
        response = VesselPositionWaterSystemVesselsResponse(
            total=len(enriched),
            page=query.page,
            page_size=query.page_size,
            items=enriched[start:start + query.page_size],
            query_snapshot_id=snapshot.snapshot_id,
            snapshot_hit=snapshot_hit,
            refresh_required=False,
            snapshot_status_code=snapshot.status_code,
            is_partial=snapshot.partial,
            error_message=snapshot.error_message,
        )
        await self._store_water_system_vessels_response_cache(cache_key, response)
        return response

    async def ais_water_system_boundaries(self, query) -> VesselAisWaterSystemBoundaryResponse:
        precision = getattr(query, "precision", "low") or "low"
        requested_codes: set[str] = set()
        water_system_code = getattr(query, "water_system_code", None)
        water_system_codes = getattr(query, "water_system_codes", None)
        if water_system_code:
            requested_codes.add(str(water_system_code).strip())
        if water_system_codes:
            requested_codes.update(code.strip() for code in str(water_system_codes).split(",") if code.strip())
        levels = self._water_system_query_levels(query)
        boundaries = self._filter_water_boundaries(
            await self._water_system_boundaries(),
            levels,
            getattr(query, "water_system_name", None),
            self._water_system_query_code_set(query, "navigation_scope_codes"),
            self._water_system_query_code_set(query, "navigation_category_codes"),
        )
        items: list[VesselAisWaterSystemBoundaryItemResponse] = []
        for boundary in boundaries:
            if requested_codes and boundary.code not in requested_codes:
                continue
            paths = (boundary.boundary_paths_by_precision or {}).get(precision) or []
            items.append(
                VesselAisWaterSystemBoundaryItemResponse(
                    water_system_code=boundary.code,
                    water_system_name=boundary.name,
                    parent_water_system_code=boundary.parent_water_system_code,
                    water_level=boundary.level,
                    water_level_name=_water_level_name(boundary.level) or "",
                    navigation_category_code=boundary.navigation_category_code,
                    navigation_category_name=_water_navigation_category_name(boundary.navigation_category_code),
                    navigation_scope_code=boundary.navigation_scope_code,
                    navigation_scope_name=_water_navigation_scope_name(boundary.navigation_scope_code),
                    display_center_longitude=boundary.display_center_longitude,
                    display_center_latitude=boundary.display_center_latitude,
                    boundary_paths=_serialize_boundary_paths(paths) or [],
                    has_boundary=bool(paths),
                    boundary_precision=precision,
                    boundary_status_code="AVAILABLE" if paths else "MISSING",
                    boundary_quality_code=boundary.boundary_quality_code,
                    boundary_quality_name=_water_boundary_quality_name(boundary.boundary_quality_code),
                    center_longitude=boundary.center_longitude,
                    center_latitude=boundary.center_latitude,
                    geometry_coordinate_system_code=boundary.geometry_coordinate_system_code,
                    boundary_coordinate_system_code=boundary.boundary_coordinate_system_code,
                )
            )
        missing = sorted(requested_codes - {item.water_system_code for item in items})
        return VesselAisWaterSystemBoundaryResponse(
            generated_at=datetime.utcnow(),
            boundary_version_id=self._water_boundary_version_id(),
            precision=precision,
            total=len(items),
            items=items,
            uncertainty_notes=[f"缺少水系边界：{', '.join(missing)}"] if missing else [],
        )

    async def ais_snapshot(self, snapshot_id: str) -> VesselAisSnapshotResponse:
        snapshot = await self.db.scalar(select(VesselAisSnapshot).where(VesselAisSnapshot.snapshot_id == snapshot_id))
        if snapshot is None:
            raise NotFoundError("VesselAisSnapshot", snapshot_id)
        status_code = "EXPIRED" if snapshot.expires_at <= datetime.utcnow() else snapshot.status_code
        return VesselAisSnapshotResponse(
            snapshot_id=snapshot.snapshot_id,
            query_hash=snapshot.query_hash,
            query_params=snapshot.query_params_json or {},
            status_code=status_code,
            generated_at=snapshot.generated_at,
            expires_at=snapshot.expires_at,
            cache_backend_code=snapshot.cache_backend_code,
            scanned_profile_count=snapshot.scanned_profile_count,
            queried_mmsi_count=snapshot.queried_mmsi_count,
            matched_profile_count=snapshot.matched_profile_count,
            matched_position_count=snapshot.matched_position_count,
            unmatched_mmsi_count=snapshot.unmatched_mmsi_count,
            invalid_position_count=snapshot.invalid_position_count,
            unknown_city_count=snapshot.unknown_city_count,
            failed_batch_count=snapshot.failed_batch_count,
            failed_batches=snapshot.failed_batches_json or [],
            coverage_rate=snapshot.coverage_rate,
            freshness_distribution=snapshot.freshness_distribution_json or {},
            source_indices=snapshot.source_indices_json or [],
            uncertainty_notes=snapshot.uncertainty_notes_json or [],
            refresh_error=snapshot.refresh_error,
        )

    async def list_unmatched_mmsi(self, query) -> PageResponse[VesselAisUnmatchedMmsiResponse]:
        snapshot_id = getattr(query, "snapshot_id", None)
        snapshot = None
        if snapshot_id:
            snapshot = await self.db.scalar(select(VesselAisSnapshot).where(VesselAisSnapshot.snapshot_id == snapshot_id))
        else:
            snapshot = await self.db.scalar(
                select(VesselAisSnapshot)
                .where(VesselAisSnapshot.status_code.in_(["READY", "PARTIAL"]))
                .order_by(VesselAisSnapshot.generated_at.desc())
                .limit(1)
            )
        if snapshot is None:
            return PageResponse(total=0, page=query.page, page_size=query.page_size, items=[])
        stmt = (
            select(VesselLatestPositionSnapshot)
            .where(
                VesselLatestPositionSnapshot.snapshot_id == snapshot.snapshot_id,
                VesselLatestPositionSnapshot.match_status_code == "UNMATCHED_MMSI",
            )
            .order_by(VesselLatestPositionSnapshot.position_time.desc(), VesselLatestPositionSnapshot.id.desc())
        )
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(stmt.offset((query.page - 1) * query.page_size).limit(query.page_size))
        ).scalars().all()
        return PageResponse(
            total=total,
            page=query.page,
            page_size=query.page_size,
            items=[
                VesselAisUnmatchedMmsiResponse(
                    snapshot_id=row.snapshot_id,
                    generated_at=snapshot.generated_at,
                    mmsi=row.mmsi,
                    longitude=row.longitude,
                    latitude=row.latitude,
                    position_time=row.position_time,
                    freshness_level=row.freshness_level,
                    source_index=row.source_index,
                    city_code=row.city_code,
                    city_name=row.city_name,
                    match_status_code=row.match_status_code,
                )
                for row in rows
            ],
        )

    async def position_ais_situation_card(self, vessel_id: int) -> VesselAisSituationCardResponse:
        generated_at = datetime.utcnow()
        profile = await self._require_profile(vessel_id)
        list_item = (await self._build_list_items([profile]))[0]
        data_sources = ["VESSEL_PROFILE"]
        uncertainty_notes: list[str] = []
        result = None
        items: list[VesselPositionMonitorItemResponse] = []
        realtime_available = await self._realtime_es_host()
        if realtime_available:
            data_sources.append("AIS_REALTIME")
            limits = await self._ais_runtime_limits()
            result = await self._position_monitor_items_for_profiles(
                [profile],
                generated_at=generated_at,
                reported_within_minutes=1440,
                es_batch_size=limits["es_batch_size"],
                es_max_concurrency=limits["es_max_concurrency"],
                include_stale=True,
            )
            items = result.items
        else:
            uncertainty_notes.append("实时 ES 未配置，AIS 位置不可计算")
        position = items[0] if items else None
        source_status = "UNCONFIGURED"
        if realtime_available:
            source_status = "ERROR" if result and result.partial and position is None else ("AVAILABLE" if position else "EMPTY")
        if result and result.error_message:
            uncertainty_notes.append(result.error_message)
        if position is None and realtime_available:
            uncertainty_notes.append("实时 ES 暂未返回该船最新位置")
        freshness_level = _ais_freshness_level(position.position_age_minutes if position else None)
        if freshness_level in {"STALE", "EXPIRED", "UNKNOWN"}:
            uncertainty_notes.append(f"AIS 新鲜度为 {freshness_level}")
        return VesselAisSituationCardResponse(
            vessel_id=vessel_id,
            generated_at=generated_at,
            data_sources=data_sources,
            uncertainty_notes=uncertainty_notes,
            identity={
                "ship_name": list_item.ship_name,
                "current_mmsi": list_item.current_mmsi,
                "ship_type_name": list_item.ship_type_name,
                "deadweight_ton": list_item.deadweight_ton,
                "size_text": list_item.size_text,
                "ship_age": list_item.ship_age,
                "registry_city_name": list_item.registry_city_name,
            },
            realtime={
                "longitude": position.longitude if position else None,
                "latitude": position.latitude if position else None,
                "current_city_code": getattr(position, "current_city_code", None) if position else None,
                "current_city_name": getattr(position, "current_city_name", None) if position else None,
                "current_city_source": getattr(position, "current_city_source", None) if position else None,
                "location_text": position.location_text if position else None,
                "speed_kn": position.speed_kn if position else None,
                "course_deg": position.course_deg if position else None,
                "heading_deg": position.heading_deg if position else None,
                "position_time": position.position_time if position else None,
                "position_age_minutes": position.position_age_minutes if position else None,
                "ais_freshness_level": freshness_level,
            },
            data_availability={
                "source_status": source_status,
                "source_status_name": _source_status_name(source_status),
                "has_realtime_position": position is not None,
                "reported_within_minutes": 1440,
                "partial": bool(result.partial) if result else False,
                "error_message": result.error_message if result else None,
                "snapshot_backend": await self._city_cache_backend(),
                "source_index": getattr(position, "source_index", None) if position else None,
            },
            quality={
                "mmsi_present": bool(list_item.current_mmsi),
                "valid_position": position is not None,
                "position_freshness_level": freshness_level,
                "current_city_source": getattr(position, "current_city_source", None) if position else None,
            },
        )

    async def position_business_card(self, vessel_id: int) -> VesselBusinessSituationCardResponse:
        generated_at = datetime.utcnow()
        profile = await self._require_profile(vessel_id)
        items: list[VesselPositionMonitorItemResponse] = []
        if await self._realtime_es_host():
            result = await self._position_monitor_items_for_profiles(
                [profile],
                generated_at=generated_at,
                reported_within_minutes=43200,
                es_batch_size=50,
                es_max_concurrency=1,
                include_stale=True,
            )
            items = result.items
        list_item = (await self._build_list_items([profile]))[0]
        position = items[0] if items else None
        risk = (await self._compliance_risk_by_profile([vessel_id])).get(vessel_id, {})
        return VesselBusinessSituationCardResponse(
            vessel_id=vessel_id,
            generated_at=generated_at,
            identity={
                "ship_name": list_item.ship_name,
                "current_mmsi": list_item.current_mmsi,
                "ship_type_name": list_item.ship_type_name,
                "deadweight_ton": list_item.deadweight_ton,
                "size_text": list_item.size_text,
                "ship_age": list_item.ship_age,
                "registry_city_name": list_item.registry_city_name,
            },
            realtime={
                "longitude": position.longitude if position else None,
                "latitude": position.latitude if position else None,
                "current_city_code": getattr(position, "current_city_code", None) if position else None,
                "current_city_name": getattr(position, "current_city_name", None) if position else None,
                "current_city_source": getattr(position, "current_city_source", None) if position else None,
                "location_text": position.location_text if position else None,
                "speed_kn": position.speed_kn if position else None,
                "course_deg": position.course_deg if position else None,
                "heading_deg": position.heading_deg if position else None,
                "position_time": position.position_time if position else None,
                "position_age_minutes": position.position_age_minutes if position else None,
            },
            operation={
                "owner_name": list_item.primary_owner_name,
                "operator_name": list_item.primary_operator_name,
                "primary_contact_name": list_item.primary_contact_name,
                "primary_contact_phone": list_item.primary_contact_phone,
                "contact_available": list_item.contact_available,
            },
            compliance=risk,
            business={
                "contactable": bool(list_item.contact_available and list_item.primary_contact_phone),
                "tonnage_ready": list_item.deadweight_ton is not None,
            },
        )

    def _position_monitor_profile_base_stmt(self, query):
        stmt = (
            select(VesselProfile)
            .outerjoin(VesselCapacityDimension, VesselCapacityDimension.vessel_profile_id == VesselProfile.id)
            .outerjoin(VesselContact, VesselContact.vessel_profile_id == VesselProfile.id)
            .outerjoin(
                VesselOwnerPeriod,
                and_(VesselOwnerPeriod.vessel_profile_id == VesselProfile.id, VesselOwnerPeriod.is_current.is_(True)),
            )
            .outerjoin(
                VesselOperatorPeriod,
                and_(VesselOperatorPeriod.vessel_profile_id == VesselProfile.id, VesselOperatorPeriod.is_current.is_(True)),
            )
            .where(VesselProfile.deleted_at.is_(None))
        )
        if query.keyword:
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
            stmt = stmt.where(VesselCapacityDimension.deadweight_ton >= query.deadweight_min)
        if query.deadweight_max is not None:
            stmt = stmt.where(VesselCapacityDimension.deadweight_ton <= query.deadweight_max)
        if query.draft_max is not None:
            stmt = stmt.where(VesselCapacityDimension.design_draft_m <= query.draft_max)
        if query.contact_available is not None:
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

    async def _mmsi_values_by_profile(self, ids: list[int]) -> dict[int, list[str]]:
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
        profiles = await self._profiles_by_ids(ids)
        for profile_id, profile in profiles.items():
            result[profile_id].append(profile.current_mmsi)
        for row in rows:
            if row.identifier_value and row.identifier_value not in result[row.vessel_profile_id]:
                result[row.vessel_profile_id].append(row.identifier_value)
        return result

    async def _search_realtime_positions(self, mmsi_values: list[str], *, max_hits: int) -> dict[str, dict[str, Any]]:
        terms: list[Any] = []
        for value in mmsi_values:
            text_value = str(value).strip()
            if not text_value:
                continue
            terms.append(text_value)
            if text_value.isdigit():
                terms.append(int(text_value))
        terms = list(dict.fromkeys(terms))
        mmsi_fields = [
            "shipMmsi",
            "shipMmsi.keyword",
            "mmsi",
            "mmsi.keyword",
            "ship_mmsi",
            "ship_mmsi.keyword",
            "MMSI",
            "ais",
            "ship_ais",
        ]
        time_fields = ["posTime", "updateTime", "timestamp", "location_time", "update_time", "position_time", "time", "@timestamp"]
        source_fields = [
            "shipMmsi",
            "mmsi",
            "ship_mmsi",
            "MMSI",
            "ais",
            "ship_ais",
            "lon",
            "lng",
            "longitude",
            "longitude_gcj02",
            "lat",
            "latitude",
            "latitude_gcj02",
            "speed",
            "sog",
            "speed_kn",
            "cog",
            "course",
            "course_deg",
            "head",
            "heading",
            "hdg",
            "heading_deg",
            "posTime",
            "updateTime",
            "timestamp",
            "location_time",
            "update_time",
            "position_time",
            "time",
            "@timestamp",
            "location_text",
            "address",
            "area_name",
            "city_name",
            "city",
            "city_code",
            "cityCode",
            "adcode",
            "city_adcode",
            "region_code",
            "shipEnName",
        ]
        query_body = {
            "size": min(max_hits, 1000),
            "track_total_hits": False,
            "_source": source_fields,
            "sort": [
                {field: {"order": "desc", "unmapped_type": "date", "missing": "_last"}}
                for field in time_fields
            ],
            "query": {
                "bool": {
                    "should": [{"terms": {field: terms}} for field in mmsi_fields],
                    "minimum_should_match": 1,
                }
            },
        }
        client = RealtimeEsClient(runtime_config=self.runtime_config)
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
        time_fields = ["posTime", "updateTime", "timestamp", "location_time", "update_time", "position_time", "time", "@timestamp"]
        source_fields = [
            "shipMmsi", "mmsi", "ship_mmsi", "MMSI", "ais", "ship_ais",
            "lon", "lng", "longitude", "longitude_gcj02", "lat", "latitude", "latitude_gcj02",
            "speed", "sog", "speed_kn", "cog", "course", "course_deg", "head", "heading", "hdg", "heading_deg",
            "posTime", "updateTime", "timestamp", "location_time", "update_time", "position_time", "time", "@timestamp",
            "location_text", "address", "area_name", "city_name", "city", "city_code", "cityCode", "adcode", "city_adcode", "region_code",
        ]
        earliest = (datetime.utcnow() - timedelta(minutes=reported_within_minutes)).strftime("%Y-%m-%d %H:%M:%S")
        range_should = [{"range": {field: {"gte": earliest}}} for field in time_fields]
        query_body = {
            "size": min(max_hits, 10000),
            "track_total_hits": False,
            "_source": source_fields,
            "sort": [
                {field: {"order": "desc", "unmapped_type": "date", "missing": "_last"}}
                for field in time_fields
            ],
            "query": {
                "bool": {
                    "should": range_should,
                    "minimum_should_match": 1,
                }
            },
        }
        client = RealtimeEsClient(runtime_config=self.runtime_config)
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
    ) -> tuple[dict[str, dict[str, Any]], bool, str | None, int, list[dict[str, Any]]]:
        positions: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        unique_values = [value for value in dict.fromkeys(mmsi_values) if value]
        batches = [unique_values[start:start + batch_size] for start in range(0, len(unique_values), batch_size)]
        semaphore = asyncio.Semaphore(max(1, max_concurrency))

        async def run_batch(batch_index: int, batch: list[str]) -> tuple[int, list[str], dict[str, dict[str, Any]], str | None]:
            async with semaphore:
                try:
                    return batch_index, batch, await self._search_realtime_positions(batch, max_hits=max(len(batch) * 3, 200)), None
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
    ) -> _PositionBuildResult:
        mmsi_by_profile = await self._mmsi_values_by_profile([row.id for row in profiles])
        mmsi_values = sorted({item for values in mmsi_by_profile.values() for item in values if item})
        if not mmsi_values:
            return _PositionBuildResult([], False, None, 0, 0, 0, 0, 0, 0)
        positions, partial, error_message, failed_batch_count, failed_batches = await self._search_realtime_positions_batched(
            mmsi_values,
            batch_size=es_batch_size,
            max_concurrency=es_max_concurrency,
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
        boundaries = await self._city_boundaries()
        boundary_grid = _CITY_BOUNDARY_CACHE.get("grid_index") or {}
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
                resolved_city = self._resolve_current_city_from_boundaries(longitude, latitude, boundaries, boundary_grid) if valid_position else _ResolvedCity(None, UNKNOWN_CITY_NAME, CURRENT_CITY_SOURCE_INVALID_POSITION)
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
        rows = (
            await self.db.execute(
                select(VesselProfileSummary.vessel_profile_id, VesselProfileSummary.risk_level).where(
                    VesselProfileSummary.vessel_profile_id.in_(profile_ids)
                )
            )
        ).all()
        return {int(profile_id): str(risk_level or "UNKNOWN") for profile_id, risk_level in rows}

    def _filter_water_situation_items_by_risk(
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

    def _water_system_query_levels(self, query) -> set[int]:
        levels: set[int] = set()
        level = getattr(query, "water_level", None)
        if level is not None:
            try:
                levels.add(int(level))
            except (TypeError, ValueError):
                pass
        raw_levels = getattr(query, "water_levels", None)
        if raw_levels:
            for part in str(raw_levels).split(","):
                text = part.strip()
                if not text:
                    continue
                try:
                    levels.add(int(text))
                except ValueError:
                    continue
        return {item for item in levels if item in {1, 2, 3, 4, 5, 6, 7}} or {1, 2, 3, 4}

    def _water_system_query_code_set(self, query, attr_name: str) -> set[str]:
        raw = getattr(query, attr_name, None)
        if not raw:
            return set()
        return {part.strip() for part in str(raw).split(",") if part.strip()}

    def _filter_water_boundaries(
        self,
        boundaries: list[_WaterSystemBoundary],
        levels: set[int],
        keyword: str | None,
        navigation_scope_codes: set[str] | None = None,
        navigation_category_codes: set[str] | None = None,
    ) -> list[_WaterSystemBoundary]:
        result = [boundary for boundary in boundaries if boundary.level in levels]
        if navigation_scope_codes:
            result = [boundary for boundary in result if (boundary.navigation_scope_code or "") in navigation_scope_codes]
        if navigation_category_codes:
            result = [boundary for boundary in result if (boundary.navigation_category_code or "") in navigation_category_codes]
        if keyword:
            text = keyword.strip()
            result = [boundary for boundary in result if text in boundary.name or text in boundary.code]
        return result

    def _water_system_situation_items(
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
        boundaries: list[_WaterSystemBoundary],
        boundary_paths_by_code: dict[str, list[list[tuple[float, float]]]] | None = None,
        boundary_precision: str | None = None,
        include_empty_water_systems: bool = True,
    ) -> list[VesselPositionWaterSystemSituationItemResponse]:
        boundary_paths_by_code = boundary_paths_by_code or {}
        boundary_by_code = {boundary.code: boundary for boundary in boundaries}
        grouped: dict[str, list[VesselPositionMonitorItemResponse]] = defaultdict(list)
        unmatched_items: list[VesselPositionMonitorItemResponse] = []
        grid_index = _WATER_SYSTEM_BOUNDARY_CACHE.get("grid_index") or {}
        allowed_codes = set(boundary_by_code.keys())
        for item in items:
            matches = self._resolve_current_water_systems_from_boundaries(
                _to_decimal(item.longitude),
                _to_decimal(item.latitude),
                boundaries,
                grid_index,
                allowed_codes,
            )
            if not matches:
                unmatched_items.append(item)
                continue
            for match in matches:
                if match.water_system_code:
                    grouped[match.water_system_code].append(item)
        result: list[VesselPositionWaterSystemSituationItemResponse] = []
        for code, system_items in grouped.items():
            boundary = boundary_by_code.get(code)
            if boundary is None:
                continue
            result.append(
                self._water_system_situation_response_item(
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
        if include_empty_water_systems:
            for boundary in boundaries:
                if boundary.code in grouped:
                    continue
                result.append(
                    self._water_system_situation_response_item(
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
                VesselPositionWaterSystemSituationItemResponse(
                    water_system_code=None,
                    water_system_name=UNKNOWN_WATER_SYSTEM_NAME,
                    water_level=None,
                    water_level_name=None,
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
                    boundary_status_code="UNKNOWN_WATER_SYSTEM",
                    latest_position_time=max([item.position_time for item in unmatched_items if item.position_time], default=None),
                    mmsi_count=queried_mmsi_count,
                    matched_position_count=matched_position_count,
                    unpositioned_count=unpositioned_count + invalid_position_count,
                    is_partial=partial,
                    error_message=error_message,
                )
            )
        return sorted(result, key=lambda item: (item.positioned_count, item.total_deadweight_ton or Decimal("0")), reverse=True)

    def _water_system_situation_response_item(
        self,
        boundary: _WaterSystemBoundary,
        system_items: list[VesselPositionMonitorItemResponse],
        risk_by_profile: dict[int, dict[str, Any]],
        summary_risk_by_profile: dict[int, str],
        generated_at: datetime,
        reported_within_minutes: int,
        partial: bool,
        error_message: str | None,
        paths: list[list[tuple[float, float]]] | None,
        boundary_precision: str | None,
    ) -> VesselPositionWaterSystemSituationItemResponse:
        fresh_items = [item for item in system_items if not self._is_stale_position(item, generated_at, reported_within_minutes)]
        stats_items = fresh_items or system_items
        longitudes = [_to_decimal(item.longitude) for item in stats_items]
        latitudes = [_to_decimal(item.latitude) for item in stats_items]
        longitudes = [value for value in longitudes if value is not None]
        latitudes = [value for value in latitudes if value is not None]
        heat_longitude = (sum(longitudes, Decimal("0")) / Decimal(len(longitudes))).quantize(Decimal("0.000001")) if longitudes else None
        heat_latitude = (sum(latitudes, Decimal("0")) / Decimal(len(latitudes))).quantize(Decimal("0.000001")) if latitudes else None
        serialized_paths = _serialize_boundary_paths(paths)
        return VesselPositionWaterSystemSituationItemResponse(
            water_system_code=boundary.code,
            water_system_name=boundary.name,
            parent_water_system_code=boundary.parent_water_system_code,
            water_level=boundary.level,
            water_level_name=_water_level_name(boundary.level),
            feature_type_code=boundary.feature_type_code,
            feature_type_name=_water_feature_type_name(boundary.feature_type_code),
            hydrology_period_code=boundary.hydrology_period_code,
            hydrology_period_name=_water_hydrology_period_name(boundary.hydrology_period_code),
            salinity_type_code=boundary.salinity_type_code,
            salinity_type_name=_water_salinity_name(boundary.salinity_type_code),
            water_boundary_type_code=boundary.water_boundary_type_code,
            water_boundary_type_name=_water_boundary_type_name(boundary.water_boundary_type_code),
            navigation_category_code=boundary.navigation_category_code,
            navigation_category_name=_water_navigation_category_name(boundary.navigation_category_code),
            navigation_scope_code=boundary.navigation_scope_code,
            navigation_scope_name=_water_navigation_scope_name(boundary.navigation_scope_code),
            center_longitude=boundary.center_longitude,
            center_latitude=boundary.center_latitude,
            display_center_longitude=boundary.display_center_longitude,
            display_center_latitude=boundary.display_center_latitude,
            heat_center_longitude=heat_longitude or boundary.display_center_longitude or boundary.center_longitude,
            heat_center_latitude=heat_latitude or boundary.display_center_latitude or boundary.center_latitude,
            boundary_paths=serialized_paths,
            has_boundary=bool(paths),
            boundary_precision=boundary_precision if serialized_paths else None,
            boundary_quality_code=boundary.boundary_quality_code,
            boundary_quality_name=_water_boundary_quality_name(boundary.boundary_quality_code),
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
            boundary_status_code="AVAILABLE" if paths else "MISSING",
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

    async def _water_system_boundaries(self) -> list[_WaterSystemBoundary]:
        now = datetime.utcnow()
        loaded_at = _WATER_SYSTEM_BOUNDARY_CACHE.get("loaded_at")
        if loaded_at and (now - loaded_at).total_seconds() < WATER_SYSTEM_BOUNDARY_CACHE_TTL_SECONDS:
            return list(_WATER_SYSTEM_BOUNDARY_CACHE.get("boundaries") or [])

        rows = (
            await self.db.execute(
                select(WaterSystemBoundary, WaterSystem)
                .join(WaterSystem, WaterSystem.id == WaterSystemBoundary.water_system_id)
                .where(
                    WaterSystemBoundary.is_current.is_(True),
                    WaterSystemBoundary.geometry_status_code == "AVAILABLE",
                    WaterSystem.is_enabled.is_(True),
                    WaterSystem.ais_situation_scope == "INCLUDED",
                )
            )
        ).all()
        boundaries: list[_WaterSystemBoundary] = []
        for boundary, water_system in rows:
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
                _WaterSystemBoundary(
                    code=water_system.water_system_code,
                    name=water_system.water_system_name,
                    parent_water_system_code=water_system.parent_water_system_code,
                    level=water_system.water_level,
                    feature_type_code=water_system.feature_type_code,
                    hydrology_period_code=water_system.hydrology_period_code,
                    salinity_type_code=water_system.salinity_type_code,
                    water_boundary_type_code=water_system.water_boundary_type_code,
                    navigation_category_code=water_system.navigation_category_code,
                    navigation_scope_code=water_system.navigation_scope_code,
                    ais_situation_scope=water_system.ais_situation_scope,
                    center_longitude=_to_decimal(boundary.center_longitude),
                    center_latitude=_to_decimal(boundary.center_latitude),
                    display_center_longitude=_to_decimal(water_system.display_center_longitude),
                    display_center_latitude=_to_decimal(water_system.display_center_latitude),
                    boundary_quality_code=boundary.boundary_quality_code,
                    geometry_coordinate_system_code=boundary.geometry_coordinate_system_code,
                    boundary_coordinate_system_code=boundary.boundary_coordinate_system_code,
                    shape_area_degree=_to_decimal(boundary.source_shape_area_degree),
                    bbox=bbox,
                    bbox_area=max(0.0, (max_x - min_x) * (max_y - min_y)),
                    polygons=polygons,
                    boundary_paths_by_precision=boundary_paths_by_precision,
                )
            )
        _WATER_SYSTEM_BOUNDARY_CACHE["loaded_at"] = now
        _WATER_SYSTEM_BOUNDARY_CACHE["boundaries"] = boundaries
        _WATER_SYSTEM_BOUNDARY_CACHE["grid_index"] = _build_water_system_boundary_grid(boundaries)
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

    def _water_boundary_paths_by_code(
        self,
        boundaries: list[_WaterSystemBoundary],
        precision: str,
    ) -> dict[str, list[list[tuple[float, float]]]]:
        result: dict[str, list[list[tuple[float, float]]]] = {}
        for boundary in boundaries:
            paths = (boundary.boundary_paths_by_precision or {}).get(precision) or []
            if paths:
                result[boundary.code] = paths
        return result

    def _water_boundary_version_id(self) -> int | None:
        loaded_at = _WATER_SYSTEM_BOUNDARY_CACHE.get("loaded_at")
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

    def _resolve_current_water_systems_from_boundaries(
        self,
        longitude: Decimal | None,
        latitude: Decimal | None,
        boundaries: list[_WaterSystemBoundary],
        grid_index: dict[tuple[int, int], list[_WaterSystemBoundary]] | None = None,
        allowed_codes: set[str] | None = None,
    ) -> list[_ResolvedWaterSystem]:
        if not self._valid_longitude_latitude(longitude, latitude):
            return []
        lon = float(longitude)
        lat = float(latitude)
        if grid_index:
            if allowed_codes is None:
                allowed_codes = {boundary.code for boundary in boundaries}
            candidates = [
                boundary for boundary in grid_index.get(_water_grid_key(lon, lat), [])
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
            near_matches: list[tuple[_WaterSystemBoundary, Decimal]] = []
            near_candidates = boundaries
            if grid_index:
                candidates_by_code: dict[str, _WaterSystemBoundary] = {}
                for key in _water_neighbor_grid_keys(lon, lat):
                    for boundary in grid_index.get(key, []):
                        if allowed_codes is not None and boundary.code not in allowed_codes:
                            continue
                        candidates_by_code.setdefault(boundary.code, boundary)
                near_candidates = list(candidates_by_code.values())
            for boundary in near_candidates:
                if not self._expanded_water_bbox_contains(boundary.bbox, lon, lat, 0.06):
                    continue
                distance_m = self._water_boundary_distance_m(lon, lat, boundary)
                if distance_m is not None and distance_m <= Decimal("5000"):
                    near_matches.append((boundary, distance_m))
            if not near_matches:
                return []
            selected, distance_m = min(
                near_matches,
                key=lambda item: (
                    self._water_boundary_category_rank(item[0]),
                    item[1],
                    item[0].shape_area_degree if item[0].shape_area_degree is not None else Decimal("999999999"),
                    Decimal(str(item[0].bbox_area)),
                ),
            )
            return [
                _ResolvedWaterSystem(
                    water_system_code=selected.code,
                    water_system_name=selected.name,
                    current_water_system_source=CURRENT_WATER_SYSTEM_SOURCE_NEAR_BOUNDARY,
                    water_level=selected.level,
                    boundary=selected,
                    match_distance_m=distance_m.quantize(Decimal("0.1")),
                )
            ]
        selected = min(matches, key=self._water_boundary_sort_key)
        return [
            _ResolvedWaterSystem(
                water_system_code=selected.code,
                water_system_name=selected.name,
                current_water_system_source=CURRENT_WATER_SYSTEM_SOURCE_BOUNDARY,
                water_level=selected.level,
                boundary=selected,
                match_distance_m=Decimal("0"),
            )
        ]

    def _water_boundary_sort_key(self, boundary: _WaterSystemBoundary) -> tuple[int, Decimal, Decimal]:
        category_rank = self._water_boundary_category_rank(boundary)
        shape_area = boundary.shape_area_degree if boundary.shape_area_degree is not None else Decimal("999999999")
        return category_rank, shape_area, Decimal(str(boundary.bbox_area))

    def _water_boundary_category_rank(self, boundary: _WaterSystemBoundary) -> int:
        return {
            "CANAL": 0,
            "DELTA_NETWORK": 0,
            "TRIBUTARY": 1,
            "MAIN_RIVER": 2,
            "LAKE": 3,
        }.get(boundary.navigation_category_code or "", 4)

    def _expanded_water_bbox_contains(
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

    def _water_boundary_distance_m(
        self,
        lon: float,
        lat: float,
        boundary: _WaterSystemBoundary,
    ) -> Decimal | None:
        distances: list[float] = []
        for polygon in boundary.polygons:
            for ring in polygon:
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

    def _water_system_match_for_position(
        self,
        item: VesselPositionMonitorItemResponse,
        *,
        water_system_code: str | None,
        water_system_name: str | None,
        boundaries: list[_WaterSystemBoundary],
    ) -> _ResolvedWaterSystem | None | bool:
        grid_index = _WATER_SYSTEM_BOUNDARY_CACHE.get("grid_index") or {}
        matches = self._resolve_current_water_systems_from_boundaries(
            _to_decimal(item.longitude),
            _to_decimal(item.latitude),
            boundaries,
            grid_index,
        )
        if water_system_code:
            expected = water_system_code.strip()
            if expected == UNKNOWN_WATER_SYSTEM_CODE:
                return None if not matches else False
            return next((match for match in matches if match.water_system_code == expected), False)
        if water_system_name:
            expected_name = water_system_name.strip()
            if expected_name == UNKNOWN_WATER_SYSTEM_NAME:
                return None if not matches else False
            return next((match for match in matches if match.water_system_name == expected_name), False)
        return matches[0] if matches else None

    def _water_system_matches_position(
        self,
        item: VesselPositionMonitorItemResponse,
        *,
        water_system_code: str | None,
        water_system_name: str | None,
        boundaries: list[_WaterSystemBoundary],
    ) -> bool:
        return self._water_system_match_for_position(
            item,
            water_system_code=water_system_code,
            water_system_name=water_system_name,
            boundaries=boundaries,
        ) is not False

    async def _store_city_situation_snapshot(
        self,
        items: list[VesselPositionMonitorItemResponse],
        *,
        generated_at: datetime,
        partial: bool,
        error_message: str | None,
    ) -> str:
        now = datetime.utcnow()
        ttl_seconds = _city_snapshot_ttl()
        expired = [key for key, value in _CITY_SITUATION_SNAPSHOTS.items() if value.expires_at <= now]
        for key in expired:
            _CITY_SITUATION_SNAPSHOTS.pop(key, None)
        while len(_CITY_SITUATION_SNAPSHOTS) >= CITY_SITUATION_SNAPSHOT_MAX_SIZE:
            oldest_key = min(_CITY_SITUATION_SNAPSHOTS, key=lambda key: _CITY_SITUATION_SNAPSHOTS[key].expires_at)
            _CITY_SITUATION_SNAPSHOTS.pop(oldest_key, None)
        snapshot_id = uuid.uuid4().hex
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
