"""Implementation methods for the vessel ais domain."""

from __future__ import annotations

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
        snapshot = await self._get_city_situation_snapshot(query.query_snapshot_id)
        snapshot_hit = snapshot is not None
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
        return VesselPositionCityVesselsResponse(
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
