"""Runtime config, query budgets, and AIS response cache helpers."""

from __future__ import annotations

from app.modules.vessel.ais.common import *


class VesselAisRuntimeCacheMixin:
    """Implementation methods for the vessel ais domain."""

    _FULL_AIS_SNAPSHOT_ID = "AIS-PRODUCTION-CURRENT"

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
            "es_batch_size": _safe_int(batch_size, 100, minimum=1, maximum=100),
            "es_max_concurrency": _safe_int(max_concurrency, 4, minimum=1, maximum=16),
            "unmatched_scan_limit": _safe_int(unmatched_scan_limit, 1000, minimum=1, maximum=10000),
        }

    async def _ais_realtime_query_budget_seconds(self) -> float:
        default_timeout = float(settings.ES_TIMEOUT_SECONDS or 12.0)
        runtime_config = getattr(self, "runtime_config", None)
        if runtime_config is None:
            timeout = default_timeout
        else:
            timeout = await runtime_config.get_float(
                ES_TIMEOUT_SECONDS,
                default_timeout,
                profile_code=ES_REALTIME_CONFIG_PROFILE,
            )
        return max(25.0, min(float(timeout or default_timeout), 45.0))

    async def _ais_es_request_timeout_seconds(self) -> float:
        budget = await self._ais_realtime_query_budget_seconds()
        return max(5.0, min(20.0, budget - 0.5))

    def _has_position_profile_filters(self, query: Any) -> bool:
        filter_attrs = [
            "keyword",
            "ship_type_code",
            "profile_status_code",
            "deadweight_min",
            "deadweight_max",
            "draft_max",
            "contact_available",
        ]
        return any(getattr(query, attr, None) not in (None, "") for attr in filter_attrs)

    async def _rollback_after_realtime_abort(self) -> None:
        try:
            await self.db.rollback()
        except Exception as exc:  # noqa: BLE001
            logger.warning("rollback after realtime AIS abort failed: %s", exc)

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
        now = datetime.utcnow()
        checked_at = _CITY_SITUATION_REDIS_BACKEND_CHECK.get("checked_at")
        checked_backend = _CITY_SITUATION_REDIS_BACKEND_CHECK.get("backend")
        if (
            checked_at
            and checked_backend in {"redis", "memory"}
            and (now - checked_at).total_seconds() < 30
            and (checked_backend == "redis" or not shared_required)
        ):
            return checked_backend
        if Redis is None:
            if shared_required:
                raise AppException(
                    "生产环境 AIS 城市态势 Redis 客户端不可用",
                    code="VESSEL_AIS_REDIS_UNAVAILABLE",
                    status_code=503,
                    detail={"cache_backend": setting},
                )
            _CITY_SITUATION_REDIS_BACKEND_CHECK.update({"checked_at": now, "backend": "memory"})
            logger.warning("city situation redis client unavailable; falling back to memory cache")
            return "memory"
        try:
            redis_client = await self._city_redis()
            if redis_client is not None:
                await redis_client.ping()
                _CITY_SITUATION_REDIS_BACKEND_CHECK.update({"checked_at": now, "backend": "redis"})
                return "redis"
        except Exception as exc:  # noqa: BLE001
            if shared_required:
                raise AppException(
                    "生产环境 AIS 城市态势 Redis 不可用",
                    code="VESSEL_AIS_REDIS_UNAVAILABLE",
                    status_code=503,
                    detail={"cache_backend": setting, "error": str(exc)},
                ) from exc
            _CITY_SITUATION_REDIS_BACKEND_CHECK.update({"checked_at": now, "backend": "memory"})
            logger.warning("city situation redis unavailable; falling back to memory cache: %s", exc)
        _CITY_SITUATION_REDIS_BACKEND_CHECK.update({"checked_at": now, "backend": "memory"})
        return "memory"

    async def _city_redis(self) -> Any | None:
        global _CITY_SITUATION_REDIS_CLIENT, _CITY_SITUATION_REDIS_LOOP_ID
        if Redis is None:
            return None
        current_loop_id = id(asyncio.get_running_loop())
        if _CITY_SITUATION_REDIS_CLIENT is not None and _CITY_SITUATION_REDIS_LOOP_ID != current_loop_id:
            try:
                await _CITY_SITUATION_REDIS_CLIENT.aclose()
            except Exception:  # noqa: BLE001
                pass
            _CITY_SITUATION_REDIS_CLIENT = None
            _CITY_SITUATION_REDIS_LOOP_ID = None
        if _CITY_SITUATION_REDIS_CLIENT is None:
            _CITY_SITUATION_REDIS_CLIENT = Redis.from_url(
                settings.CELERY_BROKER_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=0.25,
                socket_timeout=0.8,
            )
            _CITY_SITUATION_REDIS_LOOP_ID = current_loop_id
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

    async def _get_channel_situation_response_cache(
        self,
        cache_key: str,
    ) -> tuple[VesselPositionNavigationChannelSituationResponse, str] | None:
        now = datetime.utcnow()
        shared_required = _city_shared_cache_required()
        if await self._city_cache_backend() == "redis":
            try:
                redis_client = await self._city_redis()
                payload = await redis_client.get(CHANNEL_SITUATION_CACHE_KEY_PREFIX + cache_key) if redis_client else None
                if payload:
                    return VesselPositionNavigationChannelSituationResponse.model_validate_json(payload), "redis"
            except Exception as exc:  # noqa: BLE001
                logger.warning("channel situation redis cache read failed: %s", exc)
            if shared_required:
                return None
        if shared_required:
            return None
        cached = _CHANNEL_SITUATION_RESPONSE_CACHE.get(cache_key)
        if cached is None:
            return None
        if cached.expires_at <= now:
            _CHANNEL_SITUATION_RESPONSE_CACHE.pop(cache_key, None)
            return None
        return cached.response.model_copy(deep=True), "memory"

    async def _store_channel_situation_response_cache(
        self,
        cache_key: str,
        response: VesselPositionNavigationChannelSituationResponse,
    ) -> None:
        ttl = _channel_situation_cache_ttl()
        shared_required = _city_shared_cache_required()
        if await self._city_cache_backend() == "redis":
            try:
                redis_client = await self._city_redis()
                if redis_client is not None:
                    await redis_client.setex(CHANNEL_SITUATION_CACHE_KEY_PREFIX + cache_key, ttl, response.model_dump_json())
                    return
            except Exception as exc:  # noqa: BLE001
                logger.warning("channel situation redis cache write failed: %s", exc)
            if shared_required:
                return
        if shared_required:
            return
        _CHANNEL_SITUATION_RESPONSE_CACHE[cache_key] = _NavigationChannelSituationResponseCacheEntry(
            expires_at=datetime.utcnow() + timedelta(seconds=ttl),
            response=response.model_copy(deep=True),
        )

    async def _clear_ais_situation_response_caches(self) -> None:
        _CITY_SITUATION_RESPONSE_CACHE.clear()
        _CHANNEL_SITUATION_RESPONSE_CACHE.clear()
        _CITY_SITUATION_VESSELS_RESPONSE_CACHE.clear()
        _CHANNEL_SITUATION_VESSELS_RESPONSE_CACHE.clear()
        try:
            if await self._city_cache_backend() != "redis":
                return
            redis_client = await self._city_redis()
            if redis_client is None:
                return
            prefixes = [
                CITY_SITUATION_CACHE_KEY_PREFIX,
                CHANNEL_SITUATION_CACHE_KEY_PREFIX,
                CITY_SITUATION_VESSELS_CACHE_KEY_PREFIX,
                CHANNEL_SITUATION_VESSELS_CACHE_KEY_PREFIX,
            ]
            for prefix in prefixes:
                keys = [key async for key in redis_client.scan_iter(match=f"{prefix}*")]
                if keys:
                    await redis_client.delete(*keys)
        except Exception as exc:  # noqa: BLE001
            logger.warning("clear AIS situation response caches failed: %s", exc)

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

    async def _get_channel_vessels_response_cache(
        self,
        cache_key: str,
    ) -> tuple[VesselPositionNavigationChannelVesselsResponse, str] | None:
        now = datetime.utcnow()
        shared_required = _city_shared_cache_required()
        if await self._city_cache_backend() == "redis":
            try:
                redis_client = await self._city_redis()
                payload = await redis_client.get(CHANNEL_SITUATION_VESSELS_CACHE_KEY_PREFIX + cache_key) if redis_client else None
                if payload:
                    return VesselPositionNavigationChannelVesselsResponse.model_validate_json(payload), "redis"
            except Exception as exc:  # noqa: BLE001
                logger.warning("channel situation vessels redis cache read failed: %s", exc)
            if shared_required:
                return None
        if shared_required:
            return None
        cached = _CHANNEL_SITUATION_VESSELS_RESPONSE_CACHE.get(cache_key)
        if cached is None:
            return None
        if cached.expires_at <= now:
            _CHANNEL_SITUATION_VESSELS_RESPONSE_CACHE.pop(cache_key, None)
            return None
        return cached.response.model_copy(deep=True), "memory"

    async def _store_channel_vessels_response_cache(
        self,
        cache_key: str,
        response: VesselPositionNavigationChannelVesselsResponse,
    ) -> None:
        ttl = _city_snapshot_ttl()
        shared_required = _city_shared_cache_required()
        if await self._city_cache_backend() == "redis":
            try:
                redis_client = await self._city_redis()
                if redis_client is not None:
                    await redis_client.setex(CHANNEL_SITUATION_VESSELS_CACHE_KEY_PREFIX + cache_key, ttl, response.model_dump_json())
                    return
            except Exception as exc:  # noqa: BLE001
                logger.warning("channel situation vessels redis cache write failed: %s", exc)
            if shared_required:
                return
        if shared_required:
            return
        _CHANNEL_SITUATION_VESSELS_RESPONSE_CACHE[cache_key] = _NavigationChannelSituationVesselsResponseCacheEntry(
            expires_at=datetime.utcnow() + timedelta(seconds=ttl),
            response=response.model_copy(deep=True),
        )

    async def _city_situation_allows_seed_snapshot(self) -> bool:
        return not bool(await self._realtime_es_host())
