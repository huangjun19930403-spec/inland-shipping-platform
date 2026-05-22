"""Flow route geometry cache and AMMS generation helpers."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.core.config import settings
from app.integrations.hifleet.client import HifleetRouteClient
from app.integrations.http.route_geometry_types import RouteGeometryQuery
from app.modules.analysis.map_state import build_map_state_payload, default_retry_action
from app.modules.analysis.quote_route_service import _line_length_km, _line_string_points, _safe_reason, _to_optional_float
from app.modules.analysis.schemas import AnalysisActionBlock, FlowMapItem, FlowRouteCachePrecomputeResponse
from app.modules.system.runtime_config import RuntimeConfigService

try:  # Redis is optional locally; memory cache remains the fallback.
    from redis.asyncio import Redis
except Exception:  # pragma: no cover - optional dependency guard
    Redis = None  # type: ignore[assignment]


_FLOW_ROUTE_GEOMETRY_CACHE_TTL_SECONDS = settings.ANALYSIS_FLOW_ROUTE_CACHE_TTL_SECONDS
_FLOW_ROUTE_GEOMETRY_FAILURE_CACHE_TTL_SECONDS = settings.ANALYSIS_FLOW_ROUTE_FAILURE_CACHE_TTL_SECONDS
_FLOW_ROUTE_GEOMETRY_CACHE_KEY_PREFIX = "analysis:flow_route_geometry:"
_FLOW_ROUTE_GEOMETRY_CACHE: dict[str, tuple[datetime, dict[str, Any]]] = {}
_FLOW_ROUTE_GEOMETRY_REDIS_CLIENT: Any | None = None


def _reasons(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [str(value)] if value else []


def _valid_flow_coordinate(lon: float | None, lat: float | None) -> bool:
    return lon is not None and lat is not None and -180 <= lon <= 180 and -90 <= lat <= 90


def _flow_route_geometry_cache_key(item: FlowMapItem, segment_type: str) -> str:
    raw = "|".join(
        [
            segment_type,
            str(item.origin_id or ""),
            str(item.destination_id or ""),
            f"{float(item.origin_longitude or 0):.6f}",
            f"{float(item.origin_latitude or 0):.6f}",
            f"{float(item.destination_longitude or 0):.6f}",
            f"{float(item.destination_latitude or 0):.6f}",
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _flow_route_action(status_code: str, item: FlowMapItem, segment_type: str) -> AnalysisActionBlock | None:
    return default_retry_action(
        status_code,
        target_route="/address/nodes" if status_code == "NOT_COMPUTABLE" else "/analysis/flows",
        query={"segment_type": segment_type, "origin_id": item.origin_id, "destination_id": item.destination_id},
    )


def _flow_map_state_payload(
    status_code: str,
    item: FlowMapItem,
    segment_type: str,
    *,
    cache_status: str | None,
    generated_at: datetime | None = None,
    reasons: list[str] | None = None,
    missing_fields: list[str] | None = None,
) -> dict[str, Any]:
    return build_map_state_payload(
        status_code,
        provider_code="AMMS",
        cache_status=cache_status,
        last_updated_at=generated_at,
        reasons=reasons or [],
        missing_fields=missing_fields,
        retry_action=_flow_route_action(status_code, item, segment_type),
    )


def _flow_route_geometry_cache_backend_setting() -> str:
    return (settings.ANALYSIS_FLOW_ROUTE_CACHE_BACKEND or "redis").strip().lower()


async def _flow_route_geometry_redis() -> Any | None:
    global _FLOW_ROUTE_GEOMETRY_REDIS_CLIENT
    if _flow_route_geometry_cache_backend_setting() != "redis" or Redis is None:
        return None
    if _FLOW_ROUTE_GEOMETRY_REDIS_CLIENT is None:
        _FLOW_ROUTE_GEOMETRY_REDIS_CLIENT = Redis.from_url(
            settings.CELERY_BROKER_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _FLOW_ROUTE_GEOMETRY_REDIS_CLIENT


def _restore_flow_route_payload(payload: dict[str, Any]) -> dict[str, Any]:
    restored = dict(payload)
    generated_at = restored.get("route_generated_at")
    if isinstance(generated_at, str):
        try:
            restored["route_generated_at"] = datetime.fromisoformat(generated_at)
        except ValueError:
            restored["route_generated_at"] = None
    return restored


def _serialize_flow_route_payload(payload: dict[str, Any]) -> dict[str, Any]:
    serializable = dict(payload)
    generated_at = serializable.get("route_generated_at")
    if isinstance(generated_at, datetime):
        serializable["route_generated_at"] = generated_at.isoformat()
    return serializable


async def _flow_route_geometry_cache_get(cache_key: str) -> dict[str, Any] | None:
    cached = _FLOW_ROUTE_GEOMETRY_CACHE.get(cache_key)
    if cached is not None:
        expires_at, payload = cached
        if expires_at > datetime.now(UTC):
            return dict(payload)
        _FLOW_ROUTE_GEOMETRY_CACHE.pop(cache_key, None)
    redis_client = await _flow_route_geometry_redis()
    if redis_client is None:
        return None
    try:
        cached_payload = await redis_client.get(_FLOW_ROUTE_GEOMETRY_CACHE_KEY_PREFIX + cache_key)
    except Exception:
        return None
    if not cached_payload:
        return None
    try:
        payload = _restore_flow_route_payload(json.loads(cached_payload))
    except Exception:
        return None
    _FLOW_ROUTE_GEOMETRY_CACHE[cache_key] = (
        datetime.now(UTC) + timedelta(seconds=min(_FLOW_ROUTE_GEOMETRY_CACHE_TTL_SECONDS, 300)),
        dict(payload),
    )
    return payload


async def _flow_route_geometry_cache_set(cache_key: str, payload: dict[str, Any]) -> None:
    status = str(payload.get("route_status_code") or "").upper()
    ttl = _FLOW_ROUTE_GEOMETRY_CACHE_TTL_SECONDS if status == "READY" else _FLOW_ROUTE_GEOMETRY_FAILURE_CACHE_TTL_SECONDS
    _FLOW_ROUTE_GEOMETRY_CACHE[cache_key] = (datetime.now(UTC) + timedelta(seconds=ttl), dict(payload))
    redis_client = await _flow_route_geometry_redis()
    if redis_client is None:
        return
    try:
        await redis_client.setex(
            _FLOW_ROUTE_GEOMETRY_CACHE_KEY_PREFIX + cache_key,
            ttl,
            json.dumps(_serialize_flow_route_payload(payload), ensure_ascii=False, default=str),
        )
    except Exception:
        return


async def _flow_route_geometry_cache_delete(cache_key: str) -> None:
    _FLOW_ROUTE_GEOMETRY_CACHE.pop(cache_key, None)
    redis_client = await _flow_route_geometry_redis()
    if redis_client is None:
        return
    try:
        await redis_client.delete(_FLOW_ROUTE_GEOMETRY_CACHE_KEY_PREFIX + cache_key)
    except Exception:
        return


def _route_state_payload(
    status_code: str,
    item: FlowMapItem,
    segment_type: str,
    *,
    cache_status: str,
    reasons: list[str],
    generated_at: datetime | None = None,
    missing_fields: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "route_status_code": status_code,
        "route_cache_status": cache_status,
        "geometry_source": "AMMS",
        "route_generated_at": generated_at,
        "route_not_computable_reasons": reasons,
        "map_state": _flow_map_state_payload(
            status_code,
            item,
            segment_type,
            cache_status=cache_status,
            generated_at=generated_at,
            reasons=reasons,
            missing_fields=missing_fields,
        ),
    }


class FlowRouteGeometryMixin:
    runtime_config: RuntimeConfigService

    def _route_client(self) -> HifleetRouteClient:
        return HifleetRouteClient(runtime_config=self.runtime_config)

    async def _flow_route_geometry_payload(
        self,
        item: FlowMapItem,
        *,
        segment_type: str,
        client: HifleetRouteClient,
        generate_missing: bool,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        origin_lon = _to_optional_float(item.origin_longitude)
        origin_lat = _to_optional_float(item.origin_latitude)
        destination_lon = _to_optional_float(item.destination_longitude)
        destination_lat = _to_optional_float(item.destination_latitude)
        coordinate_fields = ["origin_longitude", "origin_latitude", "destination_longitude", "destination_latitude"]
        if not (_valid_flow_coordinate(origin_lon, origin_lat) and _valid_flow_coordinate(destination_lon, destination_lat)):
            return _route_state_payload(
                "NOT_COMPUTABLE",
                item,
                segment_type,
                cache_status="SKIPPED",
                reasons=["起终点经纬度不完整，无法生成 AMMS 轨迹"],
                missing_fields=coordinate_fields,
            )
        if origin_lon == destination_lon and origin_lat == destination_lat:
            return _route_state_payload(
                "NOT_COMPUTABLE",
                item,
                segment_type,
                cache_status="SKIPPED",
                reasons=["起终点坐标相同，无法生成 AMMS 轨迹"],
                missing_fields=coordinate_fields,
            )

        cache_key = _flow_route_geometry_cache_key(item, segment_type)
        if force_refresh:
            await _flow_route_geometry_cache_delete(cache_key)
        cached = await _flow_route_geometry_cache_get(cache_key)
        if cached is not None:
            cached["route_cache_status"] = "HIT"
            status = str(cached.get("route_status_code") or "PENDING").upper()
            cached["map_state"] = _flow_map_state_payload(
                status,
                item,
                segment_type,
                cache_status="HIT",
                generated_at=cached.get("route_generated_at"),
                reasons=_reasons(cached.get("route_not_computable_reasons")),
            )
            return cached

        if not generate_missing:
            return _route_state_payload(
                "PENDING",
                item,
                segment_type,
                cache_status="MISS",
                reasons=["AMMS 轨迹缓存尚未生成"],
            )

        try:
            result = await client.generate(
                RouteGeometryQuery(
                    origin_lon=origin_lon,
                    origin_lat=origin_lat,
                    dest_lon=destination_lon,
                    dest_lat=destination_lat,
                    transport_mode="WATER",
                    segment_type=segment_type,
                )
            )
        except Exception as exc:  # noqa: BLE001
            reason = _safe_reason(exc)
            status = "NOT_COMPUTABLE" if "未配置" in reason else "FAILED"
            payload = _route_state_payload(status, item, segment_type, cache_status="FAILED", reasons=[reason], generated_at=datetime.now(UTC))
            await _flow_route_geometry_cache_set(cache_key, payload)
            return payload

        points = _line_string_points(result.geometry)
        distance_km = result.distance_km if result.distance_km is not None else _line_length_km(points)
        if len(points) < 2:
            payload = _route_state_payload(
                "FAILED",
                item,
                segment_type,
                cache_status="FAILED",
                reasons=["AMMS 返回轨迹为空"],
                generated_at=datetime.now(UTC),
            )
            await _flow_route_geometry_cache_set(cache_key, payload)
            return payload

        generated_at = datetime.now(UTC)
        payload = {
            "geometry_json": result.geometry,
            "geometry_source": "AMMS",
            "route_status_code": "READY",
            "route_cache_status": "GENERATED",
            "route_generated_at": generated_at,
            "route_distance_km": round(distance_km, 3) if distance_km is not None else None,
            "route_point_count": len(points),
            "route_not_computable_reasons": [],
            "map_state": _flow_map_state_payload("READY", item, segment_type, cache_status="GENERATED", generated_at=generated_at),
        }
        await _flow_route_geometry_cache_set(cache_key, payload)
        return payload

    async def _attach_flow_route_geometries(
        self,
        items: list[FlowMapItem],
        *,
        segment_type: str,
        generate_missing: bool = False,
        force_refresh: bool = False,
    ) -> list[FlowMapItem]:
        if not items:
            return items
        client = self._route_client()
        payloads = await asyncio.gather(
            *(
                self._flow_route_geometry_payload(
                    item,
                    segment_type=segment_type,
                    client=client,
                    generate_missing=generate_missing,
                    force_refresh=force_refresh,
                )
                for item in items
            )
        )
        return [
            FlowMapItem.model_validate({**item.model_dump(), **payload}) if payload else item
            for item, payload in zip(items, payloads, strict=False)
        ]

    @staticmethod
    def _flow_route_cache_counts(items: list[FlowMapItem]) -> dict[str, int]:
        counts = {
            "total_count": len(items),
            "cached_count": 0,
            "generated_count": 0,
            "pending_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
        }
        for item in items:
            cache_status = str(item.route_cache_status or "").upper()
            status = str(item.route_status_code or "").upper()
            if cache_status == "HIT":
                counts["cached_count"] += 1
            elif cache_status == "GENERATED":
                counts["generated_count"] += 1
            elif cache_status == "SKIPPED":
                counts["skipped_count"] += 1
            elif status == "PENDING" or cache_status == "MISS":
                counts["pending_count"] += 1
            elif status in {"FAILED", "NOT_COMPUTABLE"} or cache_status == "FAILED":
                counts["failed_count"] += 1
        return counts

    async def precompute_flow_route_cache(
        self,
        date_from: date | None,
        date_to: date | None,
        *,
        flow_types: list[str] | None = None,
        limit: int = 20,
        force_refresh: bool = False,
    ) -> FlowRouteCachePrecomputeResponse:
        start, end = await self._date_range(date_from, date_to)
        normalized_types = {str(item).strip().lower() for item in (flow_types or ["freight", "ship"]) if item}
        limit = max(1, min(80, int(limit or 20)))
        all_items: list[FlowMapItem] = []
        if "freight" in normalized_types:
            all_items.extend(await self.freight_hot_routes(start, end, limit, route_geometry_mode="generate", force_refresh_routes=force_refresh))
        if "ship" in normalized_types:
            all_items.extend(await self.ship_flow_map(start, end, limit, route_geometry_mode="generate", force_refresh_routes=force_refresh))
        return FlowRouteCachePrecomputeResponse(
            status_code="SUCCESS",
            message="AMMS 流向轨迹缓存已生成",
            date_from=start,
            date_to=end,
            **self._flow_route_cache_counts(all_items),
        )
