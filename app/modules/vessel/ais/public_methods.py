"""Public AIS endpoint workflows and situation cards."""

from __future__ import annotations

from app.modules.vessel.ais.common import *


class VesselAisPublicMethodsMixin:
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
                reported_within_minutes=1440,
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
        if not self._position_query_has_profile_filters(query):
            snapshot_response = await self._position_monitor_from_latest_snapshot(
                query,
                generated_at=generated_at,
                message=None,
            )
            if snapshot_response is not None and snapshot_response.items:
                return snapshot_response
        profiles = await self._position_monitor_profiles(query)
        if not profiles:
            return self._empty_position_response(generated_at, "未匹配到符合条件的船舶档案")
        if not await self._realtime_es_host():
            fallback = await self._position_monitor_from_latest_snapshot(
                query,
                generated_at=generated_at,
                message="实时 ES 未配置，已返回最近一次入库 AIS 快照",
            )
            if fallback is not None:
                return fallback
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
        mmsi_by_profile = await self._mmsi_values_for_loaded_profiles(
            [row.id for row in profiles],
            profiles,
        )
        mmsi_values = sorted({item for values in mmsi_by_profile.values() for item in values if item})
        if not mmsi_values:
            return self._empty_position_response(generated_at, "匹配船舶缺少可用于实时查询的 MMSI", len(profiles))
        limits = await self._ais_runtime_limits()
        try:
            result = await asyncio.wait_for(
                self._position_monitor_items_for_profiles(
                    profiles,
                    generated_at=generated_at,
                    reported_within_minutes=query.reported_within_minutes or 1440,
                    es_batch_size=limits["es_batch_size"],
                    es_max_concurrency=limits["es_max_concurrency"],
                    include_stale=True,
                    mmsi_by_profile=mmsi_by_profile,
                ),
                timeout=await self._ais_realtime_query_budget_seconds(),
            )
        except asyncio.TimeoutError:
            await self._rollback_after_realtime_abort()
            fallback = await self._position_monitor_from_latest_snapshot(
                query,
                generated_at=generated_at,
                message="实时 AIS 查询超时，已返回最近一次入库 AIS 快照",
            )
            if fallback is not None:
                return fallback
            return self._position_monitor_realtime_error_response(
                generated_at,
                "实时 AIS 查询超时，且当前没有可用的入库 AIS 快照；请检查实时 ES 配置或先运行 local-demo/预计算任务生成快照。",
                matched_profile_count=len(profiles),
            )
        except Exception as exc:
            await self._rollback_after_realtime_abort()
            fallback = await self._position_monitor_from_latest_snapshot(
                query,
                generated_at=generated_at,
                message=f"实时 AIS 查询失败，已返回最近一次入库 AIS 快照：{_public_ais_error_message(exc) or '实时源异常'}",
            )
            if fallback is not None:
                return fallback
            return self._position_monitor_realtime_error_response(
                generated_at,
                f"实时 AIS 查询失败，且当前没有可用的入库 AIS 快照：{_public_ais_error_message(exc) or '实时源异常'}",
                matched_profile_count=len(profiles),
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
        can_use_persisted_snapshot = not self._has_position_profile_filters(query)
        if not force_refresh:
            cached = await self._get_city_situation_response_cache(cache_key)
            if cached is not None:
                cached_response, cache_backend = cached
                if can_use_persisted_snapshot:
                    latest_snapshot = await self._latest_persisted_ais_snapshot()
                    cached_snapshot_id = getattr(cached_response.summary, "query_snapshot_id", None)
                    cached_positioned = int(getattr(cached_response.summary, "positioned_count", 0) or 0)
                    latest_positioned = int(getattr(latest_snapshot, "matched_position_count", 0) or 0) if latest_snapshot else 0
                    if latest_snapshot is not None and (
                        cached_snapshot_id != latest_snapshot.snapshot_id
                        or (latest_positioned > 0 and cached_positioned == 0)
                    ):
                        logger.info(
                            "ignore stale AIS city situation cache: cached_snapshot=%s latest_snapshot=%s cached_positioned=%s latest_positioned=%s",
                            cached_snapshot_id,
                            latest_snapshot.snapshot_id,
                            cached_positioned,
                            latest_positioned,
                        )
                        cached_response = None
                if cached_response is None:
                    pass
                else:
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
        if can_use_persisted_snapshot:
            persisted = await self._city_situation_from_latest_snapshot(
                query,
                generated_at=generated_at,
                cache_backend=cache_backend,
                message="已返回最近一次入库 AIS 城市快照；后台任务会持续刷新全量船位。",
                total_profile_count=0,
                scanned_profile_count=0,
                unscanned_profile_count=0,
            )
            if persisted is not None:
                if not force_refresh or not persisted.is_stale_cache:
                    await self._store_city_situation_response_cache(cache_key, persisted)
                    return persisted
            if not force_refresh and persisted is not None:
                return persisted
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
            fallback = await self._city_situation_from_latest_snapshot(
                query,
                generated_at=generated_at,
                cache_backend=cache_backend,
                message="实时 ES 未配置，已返回最近一次入库 AIS 城市快照",
                total_profile_count=total_profile_count or len(profiles),
                scanned_profile_count=len(profiles),
                unscanned_profile_count=unscanned_profile_count,
            )
            if fallback is not None:
                await self._store_city_situation_response_cache(cache_key, fallback)
                return fallback
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
        use_recent_position_scan = False
        try:
            if use_recent_position_scan:
                realtime_coro = self._position_monitor_items_from_recent_positions(
                    query,
                    generated_at=generated_at,
                    reported_within_minutes=query.reported_within_minutes or 1440,
                    max_hits=profile_limit,
                    include_stale=True,
                )
            else:
                realtime_coro = self._position_monitor_items_for_profiles(
                    profiles,
                    generated_at=generated_at,
                    reported_within_minutes=query.reported_within_minutes or 1440,
                    es_batch_size=es_batch_size,
                    es_max_concurrency=es_max_concurrency,
                    include_stale=True,
                    include_unmatched=False,
                    unmatched_scan_limit=0,
                )
            result = await asyncio.wait_for(
                realtime_coro,
                timeout=await self._ais_realtime_query_budget_seconds(),
            )
        except asyncio.TimeoutError:
            await self._rollback_after_realtime_abort()
            fallback = await self._city_situation_from_latest_snapshot(
                query,
                generated_at=generated_at,
                cache_backend=cache_backend,
                message="实时 AIS 查询超时，已返回最近一次入库 AIS 城市快照",
                total_profile_count=total_profile_count or len(profiles),
                scanned_profile_count=len(profiles),
                unscanned_profile_count=0 if use_recent_position_scan else unscanned_profile_count,
            )
            if fallback is not None:
                await self._store_city_situation_response_cache(cache_key, fallback)
                return fallback
            return self._city_situation_realtime_error_response(
                generated_at=generated_at,
                cache_backend=cache_backend,
                message="实时 AIS 查询超时，且当前没有可用的入库 AIS 城市快照；请检查实时 ES 配置或先运行 local-demo/预计算任务生成快照。",
                total_profile_count=total_profile_count or len(profiles),
                scanned_profile_count=0 if use_recent_position_scan else len(profiles),
                unscanned_profile_count=0 if use_recent_position_scan else unscanned_profile_count,
            )
        except Exception as exc:
            await self._rollback_after_realtime_abort()
            fallback = await self._city_situation_from_latest_snapshot(
                query,
                generated_at=generated_at,
                cache_backend=cache_backend,
                message=f"实时 AIS 查询失败，已返回最近一次入库 AIS 城市快照：{_public_ais_error_message(exc) or '实时源异常'}",
                total_profile_count=total_profile_count or len(profiles),
                scanned_profile_count=len(profiles),
                unscanned_profile_count=0 if use_recent_position_scan else unscanned_profile_count,
            )
            if fallback is not None:
                await self._store_city_situation_response_cache(cache_key, fallback)
                return fallback
            return self._city_situation_realtime_error_response(
                generated_at=generated_at,
                cache_backend=cache_backend,
                message=f"实时 AIS 查询失败，且当前没有可用的入库 AIS 城市快照：{_public_ais_error_message(exc) or '实时源异常'}",
                total_profile_count=total_profile_count or len(profiles),
                scanned_profile_count=0 if use_recent_position_scan else len(profiles),
                unscanned_profile_count=0 if use_recent_position_scan else unscanned_profile_count,
            )
        if result.partial and not result.items:
            result_error_message = _public_ais_error_message(result.error_message)
            fallback = await self._city_situation_from_latest_snapshot(
                query,
                generated_at=generated_at,
                cache_backend=cache_backend,
                message=f"实时 AIS 查询失败，已返回最近一次入库 AIS 城市快照：{result_error_message or '实时源异常'}",
                total_profile_count=total_profile_count or len(profiles),
                scanned_profile_count=len(profiles),
                unscanned_profile_count=unscanned_profile_count,
            )
            if fallback is not None:
                await self._store_city_situation_response_cache(cache_key, fallback)
                return fallback
        partial = result.partial
        error_message = _public_ais_error_message(result.error_message)
        if unscanned_profile_count > 0 and not use_recent_position_scan:
            partial = True
            error_parts = [part for part in [error_message, f"服务端按扫描上限统计，未扫描档案 {unscanned_profile_count} 艘"] if part]
            error_message = "；".join(error_parts) or None
        scanned_profile_count_for_summary = result.queried_mmsi_count if use_recent_position_scan else len(profiles)
        unscanned_profile_count_for_summary = 0 if use_recent_position_scan else unscanned_profile_count
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
                scanned_profile_count=scanned_profile_count_for_summary,
                unscanned_profile_count=unscanned_profile_count_for_summary,
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

    async def position_channel_situation(self, query) -> VesselPositionNavigationChannelSituationResponse:
        generated_at = datetime.utcnow()
        cache_key = _channel_situation_query_cache_key(query)
        cache_backend = await self._city_cache_backend()
        force_refresh = bool(getattr(query, "force_refresh", False))
        channel_type_codes = self._channel_query_code_set(query, "channel_type_codes")
        planning_level_codes = self._channel_query_code_set(query, "planning_level_codes")
        can_use_persisted_snapshot = not self._has_position_profile_filters(query)
        if not force_refresh:
            cached = await self._get_channel_situation_response_cache(cache_key)
            if cached is not None:
                cached_response, cache_backend = cached
                if can_use_persisted_snapshot:
                    latest_snapshot = await self._latest_persisted_ais_snapshot()
                    cached_snapshot_id = getattr(cached_response.summary, "query_snapshot_id", None)
                    cached_positioned = int(getattr(cached_response.summary, "positioned_count", 0) or 0)
                    latest_positioned = int(getattr(latest_snapshot, "matched_position_count", 0) or 0) if latest_snapshot else 0
                    if latest_snapshot is not None and (
                        cached_snapshot_id != latest_snapshot.snapshot_id
                        or (latest_positioned > 0 and cached_positioned == 0)
                    ):
                        logger.info(
                            "ignore stale AIS channel situation cache: cached_snapshot=%s latest_snapshot=%s cached_positioned=%s latest_positioned=%s",
                            cached_snapshot_id,
                            latest_snapshot.snapshot_id,
                            cached_positioned,
                            latest_positioned,
                        )
                        cached_response = None
                if cached_response is not None:
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
        if can_use_persisted_snapshot:
            persisted = await self._channel_situation_from_latest_snapshot(
                query,
                generated_at=generated_at,
                cache_backend=cache_backend,
                message="已返回最近一次入库 AIS 航道快照；后台任务会持续刷新全量船位。",
                total_profile_count=0,
                scanned_profile_count=0,
                unscanned_profile_count=0,
                channel_type_codes=channel_type_codes,
                planning_level_codes=planning_level_codes,
            )
            if persisted is not None:
                if not force_refresh or not persisted.is_stale_cache:
                    await self._store_channel_situation_response_cache(cache_key, persisted)
                    return persisted
        limits = await self._ais_runtime_limits()
        profile_limit = limits["profile_limit"]
        es_batch_size = limits["es_batch_size"]
        es_max_concurrency = limits["es_max_concurrency"]
        total_profile_count = await self._position_monitor_profile_count(query)
        profiles = await self._position_monitor_profiles(query, limit=profile_limit)
        unscanned_profile_count = max(0, (total_profile_count or len(profiles)) - len(profiles))
        if not profiles:
            channels: list[VesselPositionNavigationChannelSituationItemResponse] = []
            if bool(getattr(query, "include_empty_channels", True)):
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
                    0,
                    0,
                    False,
                    None,
                    filtered_boundaries,
                    {},
                    None,
                    True,
                )
            return VesselPositionNavigationChannelSituationResponse(
                source_status="EMPTY",
                source_status_name=_source_status_name("EMPTY"),
                generated_at=generated_at,
                message="未匹配到符合条件的船舶档案",
                cache_status="MISS",
                cache_generated_at=generated_at,
                is_stale_cache=False,
                snapshot_backend=cache_backend,
                cache_backend_note="memory 仅适合本地开发；生产多实例请配置 Redis" if cache_backend == "memory" else None,
                summary=VesselPositionNavigationChannelSituationSummary(
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
                    channel_count=sum(1 for item in channels if item.channel_code),
                    boundary_channel_count=sum(1 for item in channels if item.channel_code and item.has_boundary),
                    missing_boundary_channel_count=sum(1 for item in channels if item.channel_code and not item.has_boundary),
                ),
                channels=channels,
            )
        if not force_refresh and can_use_persisted_snapshot:
            persisted = await self._channel_situation_from_latest_snapshot(
                query,
                generated_at=generated_at,
                cache_backend=cache_backend,
                message="已返回最近一次入库 AIS 航道快照；后台任务会持续刷新全量船位。",
                total_profile_count=total_profile_count or len(profiles),
                scanned_profile_count=len(profiles),
                unscanned_profile_count=unscanned_profile_count,
                channel_type_codes=channel_type_codes,
                planning_level_codes=planning_level_codes,
            )
            if persisted is not None:
                await self._store_channel_situation_response_cache(cache_key, persisted)
                return persisted
        if not await self._realtime_es_host():
            fallback = await self._channel_situation_from_latest_snapshot(
                query,
                generated_at=generated_at,
                cache_backend=cache_backend,
                message="实时 ES 未配置，已返回最近一次入库 AIS 航道快照",
                total_profile_count=total_profile_count or len(profiles),
                scanned_profile_count=len(profiles),
                unscanned_profile_count=unscanned_profile_count,
                channel_type_codes=channel_type_codes,
                planning_level_codes=planning_level_codes,
            )
            if fallback is not None:
                await self._store_channel_situation_response_cache(cache_key, fallback)
                return fallback
            channels: list[VesselPositionNavigationChannelSituationItemResponse] = []
            if bool(getattr(query, "include_empty_channels", True)):
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
                    0,
                    0,
                    False,
                    None,
                    filtered_boundaries,
                    {},
                    None,
                    True,
                )
            return VesselPositionNavigationChannelSituationResponse(
                source_status="UNCONFIGURED",
                source_status_name=_source_status_name("UNCONFIGURED"),
                generated_at=generated_at,
                message="实时 ES 未配置，暂无航道态势",
                cache_status="MISS",
                cache_generated_at=generated_at,
                is_stale_cache=False,
                snapshot_backend=cache_backend,
                cache_backend_note="memory 仅适合本地开发；生产多实例请配置 Redis" if cache_backend == "memory" else None,
                summary=VesselPositionNavigationChannelSituationSummary(
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
                    channel_count=sum(1 for item in channels if item.channel_code),
                    boundary_channel_count=sum(1 for item in channels if item.channel_code and item.has_boundary),
                    missing_boundary_channel_count=sum(1 for item in channels if item.channel_code and not item.has_boundary),
                ),
                channels=channels,
            )
        use_recent_position_scan = False
        try:
            if use_recent_position_scan:
                realtime_coro = self._position_monitor_items_from_recent_positions(
                    query,
                    generated_at=generated_at,
                    reported_within_minutes=query.reported_within_minutes or 1440,
                    max_hits=profile_limit,
                    include_stale=True,
                )
            else:
                realtime_coro = self._position_monitor_items_for_profiles(
                    profiles,
                    generated_at=generated_at,
                    reported_within_minutes=query.reported_within_minutes or 1440,
                    es_batch_size=es_batch_size,
                    es_max_concurrency=es_max_concurrency,
                    include_stale=True,
                    include_unmatched=False,
                    unmatched_scan_limit=0,
                    resolve_city=False,
                )
            result = await asyncio.wait_for(
                realtime_coro,
                timeout=await self._ais_realtime_query_budget_seconds(),
            )
        except asyncio.TimeoutError:
            await self._rollback_after_realtime_abort()
            fallback = await self._channel_situation_from_latest_snapshot(
                query,
                generated_at=generated_at,
                cache_backend=cache_backend,
                message="实时 AIS 查询超时，已返回最近一次入库 AIS 航道快照",
                total_profile_count=total_profile_count or len(profiles),
                scanned_profile_count=len(profiles),
                unscanned_profile_count=0 if use_recent_position_scan else unscanned_profile_count,
                channel_type_codes=channel_type_codes,
                planning_level_codes=planning_level_codes,
            )
            if fallback is not None:
                await self._store_channel_situation_response_cache(cache_key, fallback)
                return fallback
            return await self._channel_situation_realtime_error_response(
                query,
                generated_at=generated_at,
                cache_backend=cache_backend,
                message="实时 AIS 查询超时，当前没有可用的航道态势快照；请检查实时 ES 配置或先运行 local-demo/预计算任务生成快照。",
                total_profile_count=total_profile_count or len(profiles),
                scanned_profile_count=0 if use_recent_position_scan else len(profiles),
                unscanned_profile_count=0 if use_recent_position_scan else unscanned_profile_count,
                channel_type_codes=channel_type_codes,
                planning_level_codes=planning_level_codes,
            )
        except Exception as exc:
            await self._rollback_after_realtime_abort()
            fallback = await self._channel_situation_from_latest_snapshot(
                query,
                generated_at=generated_at,
                cache_backend=cache_backend,
                message=f"实时 AIS 查询失败，已返回最近一次入库 AIS 航道快照：{_public_ais_error_message(exc) or '实时源异常'}",
                total_profile_count=total_profile_count or len(profiles),
                scanned_profile_count=len(profiles),
                unscanned_profile_count=0 if use_recent_position_scan else unscanned_profile_count,
                channel_type_codes=channel_type_codes,
                planning_level_codes=planning_level_codes,
            )
            if fallback is not None:
                await self._store_channel_situation_response_cache(cache_key, fallback)
                return fallback
            return await self._channel_situation_realtime_error_response(
                query,
                generated_at=generated_at,
                cache_backend=cache_backend,
                message=f"实时 AIS 查询失败，当前没有可用的航道态势快照：{_public_ais_error_message(exc) or '实时源异常'}",
                total_profile_count=total_profile_count or len(profiles),
                scanned_profile_count=0 if use_recent_position_scan else len(profiles),
                unscanned_profile_count=0 if use_recent_position_scan else unscanned_profile_count,
                channel_type_codes=channel_type_codes,
                planning_level_codes=planning_level_codes,
            )
        if result.partial and not result.items:
            result_error_message = _public_ais_error_message(result.error_message)
            fallback = await self._channel_situation_from_latest_snapshot(
                query,
                generated_at=generated_at,
                cache_backend=cache_backend,
                message=f"实时 AIS 查询失败，已返回最近一次入库 AIS 航道快照：{result_error_message or '实时源异常'}",
                total_profile_count=total_profile_count or len(profiles),
                scanned_profile_count=len(profiles),
                unscanned_profile_count=0 if use_recent_position_scan else unscanned_profile_count,
                channel_type_codes=channel_type_codes,
                planning_level_codes=planning_level_codes,
            )
            if fallback is not None:
                await self._store_channel_situation_response_cache(cache_key, fallback)
                return fallback
        partial = result.partial
        error_message = _public_ais_error_message(result.error_message)
        if unscanned_profile_count > 0 and not use_recent_position_scan:
            partial = True
            parts = [part for part in [error_message, f"服务端按扫描上限统计，未扫描档案 {unscanned_profile_count} 艘"] if part]
            error_message = "；".join(parts) or None
        scanned_profile_count_for_summary = result.queried_mmsi_count if use_recent_position_scan else len(profiles)
        unscanned_profile_count_for_summary = 0 if use_recent_position_scan else unscanned_profile_count
        risk_by_profile = await self._compliance_risk_by_profile([item.id for item in result.items])
        summary_risk_by_profile = await self._summary_risk_level_by_profile([item.id for item in result.items])
        items = self._filter_channel_situation_items_by_risk(result.items, query, risk_by_profile, summary_risk_by_profile)
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
        channels = self._channel_situation_items(
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
            bool(getattr(query, "include_empty_channels", True)),
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
            uncertainty_notes.append("当前航道态势快照使用本机内存缓存，多实例部署时建议使用 Redis")
        if partial:
            uncertainty_notes.append("本次 AIS 航道态势为部分结果")
        if result.invalid_positions:
            uncertainty_notes.append(f"发现无效点位 {len(result.invalid_positions)} 条")
        if result.source_indices:
            uncertainty_notes.append(f"实时 ES 来源索引：{', '.join(result.source_indices[:5])}")
        snapshot_expires_at = generated_at + timedelta(seconds=_city_snapshot_ttl())
        response_status = "PARTIAL" if partial and channels else ("ERROR" if partial and not channels else ("AVAILABLE" if channels else "EMPTY"))
        response = VesselPositionNavigationChannelSituationResponse(
            source_status=response_status,
            source_status_name=_source_status_name(response_status),
            generated_at=generated_at,
            message=error_message if partial else (None if channels else "实时 ES 暂无符合筛选条件的航道态势"),
            cache_status="MISS",
            cache_generated_at=generated_at,
            is_stale_cache=False,
            snapshot_backend=cache_backend,
            cache_backend_note="memory 仅适合本地开发；生产多实例请配置 Redis" if cache_backend == "memory" else None,
            summary=VesselPositionNavigationChannelSituationSummary(
                matched_profile_count=total_profile_count or len(profiles),
                scanned_profile_count=scanned_profile_count_for_summary,
                unscanned_profile_count=unscanned_profile_count_for_summary,
                queried_mmsi_count=result.queried_mmsi_count,
                matched_position_count=result.matched_position_count,
                unmatched_mmsi_count=0,
                unpositioned_count=result.unpositioned_count,
                invalid_position_count=len(result.invalid_positions),
                unknown_channel_count=sum(item.positioned_count for item in channels if not item.channel_code),
                positioned_count=len(positioned_items),
                stale_position_count=len(items) - len(positioned_items),
                contactable_position_count=sum(1 for item in positioned_items if item.contact_available),
                certificate_risk_count=sum(1 for item in positioned_items if risk_by_profile.get(item.id, {}).get("has_certificate_risk")),
                high_risk_count=sum(1 for item in positioned_items if summary_risk_by_profile.get(item.id) == "HIGH"),
                channel_count=sum(1 for item in channels if item.channel_code),
                boundary_channel_count=sum(1 for item in channels if item.channel_code and item.has_boundary),
                missing_boundary_channel_count=sum(1 for item in channels if item.channel_code and not item.has_boundary),
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
            channels=channels,
        )
        await self._store_channel_situation_response_cache(cache_key, response)
        return response

    async def position_channel_vessels(self, query) -> VesselPositionNavigationChannelVesselsResponse:
        if not query.query_snapshot_id:
            return VesselPositionNavigationChannelVesselsResponse(
                total=0,
                page=query.page,
                page_size=query.page_size,
                items=[],
                query_snapshot_id=None,
                snapshot_hit=False,
                refresh_required=True,
                snapshot_status_code="MISSING",
                is_partial=False,
                error_message="航道下钻必须带 query_snapshot_id，请先刷新 AIS 航道态势",
            )
        cache_key = _situation_vessels_query_cache_key(query)
        cached = await self._get_channel_vessels_response_cache(cache_key)
        if cached is not None:
            cached_response, _cache_backend = cached
            return cached_response.model_copy(
                update={"snapshot_hit": True, "refresh_required": False},
                deep=True,
            )
        snapshot = await self._get_city_situation_snapshot(query.query_snapshot_id)
        snapshot_hit = snapshot is not None
        if not snapshot or snapshot.refresh_required or snapshot.status_code == "EXPIRED":
            return VesselPositionNavigationChannelVesselsResponse(
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
        boundaries = await self._channel_boundaries()
        boundary_keyword = getattr(query, "channel_name", None)
        if getattr(query, "channel_code", None) == UNKNOWN_CHANNEL_CODE or boundary_keyword == UNKNOWN_CHANNEL_NAME:
            boundary_keyword = None
        filtered_boundaries = self._filter_channel_boundaries(
            boundaries,
            boundary_keyword,
            self._channel_query_code_set(query, "channel_type_codes"),
            self._channel_query_code_set(query, "planning_level_codes"),
        )
        items = [
            item for item in snapshot.items
            if not self._is_stale_position(item, snapshot.generated_at, query.reported_within_minutes or 1440)
        ]
        risk_by_profile = await self._compliance_risk_by_profile([item.id for item in items])
        summary_risk_by_profile = await self._summary_risk_level_by_profile([item.id for item in items])
        items = self._filter_channel_situation_items_by_risk(items, query, risk_by_profile, summary_risk_by_profile)
        matched_items: list[tuple[VesselPositionMonitorItemResponse, _ResolvedNavigationChannel | None]] = []
        for item in items:
            match = self._channel_match_for_position(
                item,
                channel_code=query.channel_code,
                channel_name=query.channel_name,
                boundaries=filtered_boundaries,
            )
            if match is not False:
                matched_items.append((item, match))
        enriched = [
            item.model_copy(
                update={
                    "risk_level": summary_risk_by_profile.get(item.id),
                    "certificate_risk_available": bool(risk_by_profile.get(item.id, {}).get("has_certificate_risk")),
                    "current_channel_code": match.channel_code if match else None,
                    "current_channel_name": match.channel_name if match else None,
                    "current_channel_source": match.current_channel_source if match else None,
                    "channel_match_distance_m": match.match_distance_m if match else None,
                }
            )
            for item, match in matched_items
        ]
        start = (query.page - 1) * query.page_size
        response = VesselPositionNavigationChannelVesselsResponse(
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
        await self._store_channel_vessels_response_cache(cache_key, response)
        return response

    async def ais_channel_boundaries(self, query) -> VesselAisNavigationChannelBoundaryResponse:
        precision = getattr(query, "precision", "low") or "low"
        requested_codes: set[str] = set()
        channel_code = getattr(query, "channel_code", None)
        channel_codes = getattr(query, "channel_codes", None)
        if channel_code:
            requested_codes.add(str(channel_code).strip())
        if channel_codes:
            requested_codes.update(code.strip() for code in str(channel_codes).split(",") if code.strip())
        boundaries = self._filter_channel_boundaries(
            await self._channel_boundaries(),
            getattr(query, "channel_name", None),
            self._channel_query_code_set(query, "channel_type_codes"),
            self._channel_query_code_set(query, "planning_level_codes"),
        )
        items: list[VesselAisNavigationChannelBoundaryItemResponse] = []
        for boundary in boundaries:
            if requested_codes and boundary.code not in requested_codes:
                continue
            paths = (boundary.boundary_paths_by_precision or {}).get(precision) or []
            items.append(
                VesselAisNavigationChannelBoundaryItemResponse(
                    channel_code=boundary.code,
                    channel_name=boundary.name,
                    parent_channel_code=boundary.parent_channel_code,
                    channel_type_code=boundary.channel_type_code,
                    channel_type_name=_channel_type_name(boundary.channel_type_code) or "",
                    planning_level_code=boundary.planning_level_code,
                    planning_level_name=_channel_planning_level_name(boundary.planning_level_code) or "",
                    ais_scope_code=boundary.ais_scope_code,
                    ais_scope_name=_channel_ais_scope_name(boundary.ais_scope_code),
                    display_center_longitude=boundary.display_center_longitude,
                    display_center_latitude=boundary.display_center_latitude,
                    boundary_paths=_serialize_boundary_paths(paths) or [],
                    has_boundary=bool(paths),
                    boundary_precision=precision,
                    boundary_status_code="AVAILABLE" if paths else "MISSING",
                    boundary_quality_code=boundary.boundary_quality_code,
                    boundary_quality_name=_channel_boundary_quality_name(boundary.boundary_quality_code),
                    connectivity_status_code=boundary.connectivity_status_code,
                    connectivity_status_name=_channel_connectivity_status_name(boundary.connectivity_status_code),
                    repair_status_code=boundary.repair_status_code,
                    repair_status_name=_channel_repair_status_name(boundary.repair_status_code),
                    center_longitude=boundary.center_longitude,
                    center_latitude=boundary.center_latitude,
                    geometry_coordinate_system_code=boundary.geometry_coordinate_system_code,
                    boundary_coordinate_system_code=boundary.boundary_coordinate_system_code,
                )
            )
        missing = sorted(requested_codes - {item.channel_code for item in items})
        return VesselAisNavigationChannelBoundaryResponse(
            generated_at=datetime.utcnow(),
            boundary_version_id=self._channel_boundary_version_id(),
            precision=precision,
            total=len(items),
            items=items,
            uncertainty_notes=[f"缺少航道边界：{', '.join(missing)}"] if missing else [],
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
