"""analysis 模块 service。"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
import math
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import settings
from app.core.exceptions import AppException, NotFoundError, ValidationError
from app.integrations.hifleet.client import HifleetRouteClient
from app.integrations.http.route_geometry_types import RouteGeometryQuery
from app.models.address import AdminRegion, AdminRegionBoundary, Region, TransportNode
from app.models.analysis import (
    AnalysisJobDefinition,
    AnalysisJobRun,
    FactCandidateFitDaily,
    FactFreightCityDaily,
    FactFreightCommodityDaily,
    FactFreightDaily,
    FactFreightFlowDaily,
    FactFreightNodeDaily,
    FactFreightPriceDaily,
    FactRegionDaily,
    FactRegionSupplyDemandDaily,
    FactShipCityDaily,
    FactShipDaily,
    FactShipFlowDaily,
    FactVesselAisFreshnessDaily,
    FactVesselAssetDaily,
    FactVesselQualityDaily,
    FactVesselRiskDaily,
    FactVesselTrajectoryDaily,
)
from app.models.commodity import CommodityStandard
from app.models.freight import Freight
from app.models.dictionary import StdDict, StdDictItem
from app.modules.address.boundary_utils import (
    boundary_paths_for_precision,
    extract_geojson_polygons,
    serialize_boundary_paths,
)
from app.modules.analysis.schemas import (
    AnalysisActionBlock,
    AnalysisContextBlock,
    AnalysisJobRunDetailResponse,
    AnalysisJobRunResponse,
    AnalysisLineageBlock,
    AnalysisOverviewResponse,
    AnalysisQualityBlock,
    AnalysisTaskDetailResponse,
    AnalysisTaskResponse,
    AnalysisTaskTriggerRequest,
    BoundaryHeatMapItem,
    ChartPoint,
    FlowAnalysisOverviewResponse,
    FlowMapItem,
    FlowRouteCachePrecomputeResponse,
    FreightAnalysisOverviewResponse,
    HeatMapItem,
    MetricCard,
    MetricEvidence,
    PageResponse,
    PriceAnalysisOverviewResponse,
    RegionSupplyDemandAnalysisResponse,
    RegionAnalysisOverviewResponse,
    ShipAnalysisOverviewResponse,
    VesselAssetAnalysisResponse,
    VesselCandidateFitAnalysisResponse,
    VesselQualityAnalysisResponse,
    VesselRiskAnalysisResponse,
    VesselTrajectoryAnalysisResponse,
)
from app.modules.analysis.map_state import build_map_state_payload, default_retry_action
from app.modules.analysis.job_catalog import MODULE_NAMES
from app.modules.analysis.quote_route_service import QuoteRouteEstimateService
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


def _num(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _ratio(value: float, total: float) -> float | None:
    if not total:
        return None
    return round(value / total, 4)


def _metric(code: str, title: str, value: Any, unit: str | None = None, description: str | None = None) -> MetricCard:
    numeric = _num(value)
    if numeric.is_integer():
        display_value: int | float = int(numeric)
    else:
        display_value = round(numeric, 2)
    return MetricCard(code=code, title=title, value=display_value, unit=unit, description=description)


def _reasons(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if value:
        return [str(value)]
    return []


def _evidence(
    code: str,
    value: Any,
    *,
    unit: str | None,
    start: date,
    end: date,
    row: Any | None = None,
    last_successful_run_at: datetime | None = None,
    extra: dict | None = None,
) -> MetricEvidence:
    numeric_value: float | int | None
    if value is None:
        numeric_value = None
    else:
        numeric = _num(value)
        numeric_value = int(numeric) if numeric.is_integer() else round(numeric, 4)
    return MetricEvidence(
        metric_code=code,
        value=numeric_value,
        unit=unit,
        date_from=start,
        date_to=end,
        source_layer_code=getattr(row, "source_layer_code", None) if row is not None else None,
        sample_count=getattr(row, "sample_count", None) if row is not None else None,
        coverage_rate=round(_num(getattr(row, "coverage_rate", None)), 2) if row is not None and getattr(row, "coverage_rate", None) is not None else None,
        confidence_level=getattr(row, "confidence_level", None) if row is not None else None,
        not_computable_reasons=_reasons(getattr(row, "not_computable_reasons_json", None)) if row is not None else [],
        uncertainty_reasons=_reasons(getattr(row, "uncertainty_reasons_json", None)) if row is not None else [],
        generated_at=getattr(row, "generated_at", None) if row is not None else None,
        source_updated_at=getattr(row, "source_updated_at", None) if row is not None else None,
        last_successful_run_at=last_successful_run_at,
        extra=extra,
    )


def _job_to_response(entity: AnalysisJobRun) -> AnalysisJobRunResponse:
    module_name = MODULE_NAMES.get(entity.module_code, entity.module_name)
    return AnalysisJobRunResponse(
        id=entity.id,
        job_code=entity.job_code,
        job_name=entity.job_name,
        module_code=entity.module_code,
        module_name=module_name,
        stat_date_from=entity.stat_date_from,
        stat_date_to=entity.stat_date_to,
        status_code=entity.status_code,
        status_name=entity.status_name,
        celery_task_id=entity.celery_task_id,
        queued_at=entity.queued_at,
        started_at=entity.started_at,
        finished_at=entity.finished_at,
        duration_ms=entity.duration_ms,
        input_rows=entity.input_rows,
        output_rows=entity.output_rows,
        affected_rows=entity.affected_rows,
        error_message=entity.error_message,
        triggered_by=entity.triggered_by,
        created_at=entity.created_at,
    )


def _task_to_response(entity: AnalysisJobDefinition) -> AnalysisTaskResponse:
    module_name = MODULE_NAMES.get(entity.module_code, entity.module_name)
    return AnalysisTaskResponse(
        id=entity.id,
        job_code=entity.job_code,
        job_name=entity.job_name,
        module_code=entity.module_code,
        module_name=module_name,
        description=entity.description,
        source_tables_json=entity.source_tables_json,
        target_tables_json=entity.target_tables_json,
        default_parameters_json=entity.default_parameters_json,
        schedule_cron=entity.schedule_cron,
        schedule_enabled=entity.schedule_enabled,
        enabled=entity.enabled,
        last_run_id=entity.last_run_id,
        last_status_code=entity.last_status_code,
        last_finished_at=entity.last_finished_at,
        last_result_summary_json=entity.last_result_summary_json,
        sort_order=entity.sort_order,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _status_name(status_code: str) -> str:
    return {
        "QUEUED": "排队中",
        "RUNNING": "运行中",
        "SUCCESS": "成功",
        "PARTIAL_SUCCESS": "部分成功",
        "FAILED": "失败",
    }.get(status_code, status_code)


def _to_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _line_string_points(geometry: dict | None) -> list[tuple[float, float]]:
    if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
        return []
    points: list[tuple[float, float]] = []
    for item in geometry.get("coordinates") or []:
        if not isinstance(item, list | tuple) or len(item) < 2:
            continue
        lon = _to_optional_float(item[0])
        lat = _to_optional_float(item[1])
        if lon is None or lat is None:
            continue
        if -180 <= lon <= 180 and -90 <= lat <= 90:
            point = (lon, lat)
            if not points or points[-1] != point:
                points.append(point)
    return points


def _haversine_distance_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    radius_km = 6371.0088
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _line_length_km(points: list[tuple[float, float]]) -> float | None:
    if len(points) < 2:
        return None
    distance = 0.0
    for index in range(len(points) - 1):
        start = points[index]
        end = points[index + 1]
        distance += _haversine_distance_km(start[0], start[1], end[0], end[1])
    return round(distance, 3)


def _safe_reason(exc: Exception) -> str:
    if isinstance(exc, AppException):
        text = exc.message
    else:
        text = str(exc)
    return (text or "AMMS 航线测算失败").replace("HiFleet", "AMMS").replace("HIFLEET", "AMMS").replace("\r", " ").replace("\n", " ").strip()[:180]


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
    target_route = "/address/nodes" if status_code == "NOT_COMPUTABLE" else "/analysis/flows"
    return default_retry_action(
        status_code,
        target_route=target_route,
        query={
            "segment_type": segment_type,
            "origin_id": item.origin_id,
            "destination_id": item.destination_id,
        },
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
    ttl = _FLOW_ROUTE_GEOMETRY_CACHE_TTL_SECONDS
    _FLOW_ROUTE_GEOMETRY_CACHE[cache_key] = (datetime.now(UTC) + timedelta(seconds=min(ttl, 300)), dict(payload))
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


class AnalysisDashboardService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.runtime_config = RuntimeConfigService(db)

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
        if not (
            _valid_flow_coordinate(origin_lon, origin_lat)
            and _valid_flow_coordinate(destination_lon, destination_lat)
        ):
            reasons = ["起终点经纬度不完整，无法生成 AMMS 轨迹"]
            return {
                "route_status_code": "NOT_COMPUTABLE",
                "route_cache_status": "SKIPPED",
                "geometry_source": "AMMS",
                "route_not_computable_reasons": reasons,
                "map_state": _flow_map_state_payload(
                    "NOT_COMPUTABLE",
                    item,
                    segment_type,
                    cache_status="SKIPPED",
                    reasons=reasons,
                    missing_fields=["origin_longitude", "origin_latitude", "destination_longitude", "destination_latitude"],
                ),
            }
        if origin_lon == destination_lon and origin_lat == destination_lat:
            reasons = ["起终点坐标相同，无法生成 AMMS 轨迹"]
            return {
                "route_status_code": "NOT_COMPUTABLE",
                "route_cache_status": "SKIPPED",
                "geometry_source": "AMMS",
                "route_not_computable_reasons": reasons,
                "map_state": _flow_map_state_payload(
                    "NOT_COMPUTABLE",
                    item,
                    segment_type,
                    cache_status="SKIPPED",
                    reasons=reasons,
                    missing_fields=["origin_longitude", "origin_latitude", "destination_longitude", "destination_latitude"],
                ),
            }

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
            reasons = ["AMMS 轨迹缓存尚未生成"]
            return {
                "route_status_code": "PENDING",
                "route_cache_status": "MISS",
                "geometry_source": "AMMS",
                "route_not_computable_reasons": reasons,
                "map_state": _flow_map_state_payload(
                    "PENDING",
                    item,
                    segment_type,
                    cache_status="MISS",
                    reasons=reasons,
                ),
            }

        assert origin_lon is not None and origin_lat is not None and destination_lon is not None and destination_lat is not None
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
            generated_at = datetime.now(UTC)
            payload = {
                "route_status_code": status,
                "route_cache_status": "FAILED",
                "geometry_source": "AMMS",
                "route_generated_at": generated_at,
                "route_not_computable_reasons": [reason],
                "map_state": _flow_map_state_payload(
                    status,
                    item,
                    segment_type,
                    cache_status="FAILED",
                    generated_at=generated_at,
                    reasons=[reason],
                ),
            }
            await _flow_route_geometry_cache_set(cache_key, payload)
            return payload

        points = _line_string_points(result.geometry)
        distance_km = result.distance_km if result.distance_km is not None else _line_length_km(points)
        if len(points) < 2:
            reasons = ["AMMS 返回轨迹为空"]
            generated_at = datetime.now(UTC)
            payload = {
                "route_status_code": "FAILED",
                "route_cache_status": "FAILED",
                "geometry_source": "AMMS",
                "route_generated_at": generated_at,
                "route_not_computable_reasons": reasons,
                "map_state": _flow_map_state_payload(
                    "FAILED",
                    item,
                    segment_type,
                    cache_status="FAILED",
                    generated_at=generated_at,
                    reasons=reasons,
                ),
            }
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
            "map_state": _flow_map_state_payload(
                "READY",
                item,
                segment_type,
                cache_status="GENERATED",
                generated_at=generated_at,
            ),
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

    async def _date_range(self, date_from: date | None, date_to: date | None) -> tuple[date, date]:
        latest = await self.db.scalar(select(func.max(FactFreightDaily.stat_date)))
        latest = latest or await self.db.scalar(select(func.max(FactShipDaily.stat_date)))
        end = date_to or latest or date.today()
        start = date_from or (end - timedelta(days=89))
        return start, end

    async def _dict_labels(self, dict_codes: list[str]) -> dict[str, dict[str, str]]:
        rows = (
            await self.db.execute(
                select(StdDict.dict_code, StdDictItem.item_code, StdDictItem.item_name)
                .join(StdDictItem, StdDictItem.dict_id == StdDict.id)
                .where(StdDict.dict_code.in_(dict_codes), StdDictItem.status == 1)
            )
        ).all()
        labels: dict[str, dict[str, str]] = {code: {} for code in dict_codes}
        for dict_code, item_code, item_name in rows:
            labels.setdefault(dict_code, {})[item_code] = item_name
        return labels

    @staticmethod
    def _workbench_meta(
        start: date,
        end: date,
        *,
        source_tables: list[str],
        sample_count: int,
        actions: list[AnalysisActionBlock],
        data_versions: list[str] | None = None,
        not_computable_reasons: list[str] | None = None,
        uncertainty_reasons: list[str] | None = None,
    ) -> dict[str, Any]:
        confidence = "HIGH" if sample_count > 0 and not not_computable_reasons else "UNKNOWN"
        coverage_rate = 100.0 if sample_count > 0 and not not_computable_reasons else 0.0
        return {
            "context": AnalysisContextBlock(date_from=start, date_to=end),
            "lineage": AnalysisLineageBlock(
                source_tables=source_tables,
                data_versions=data_versions or ["FORMAL_ANALYSIS_V1"],
                sample_count=int(sample_count),
                generated_at=datetime.now(UTC).replace(tzinfo=None),
            ),
            "quality": AnalysisQualityBlock(
                coverage_rate=coverage_rate,
                confidence_level=confidence,
                not_computable_reasons=not_computable_reasons or ([] if sample_count > 0 else ["SOURCE_MISSING"]),
                uncertainty_reasons=uncertainty_reasons or [],
            ),
            "actions": actions,
        }

    async def get_overview(self, date_from: date | None, date_to: date | None) -> AnalysisOverviewResponse:
        start, end = await self._date_range(date_from, date_to)
        freight = await self._freight_totals(start, end)
        ship = await self._ship_totals(start, end)
        region_count = await self.db.scalar(
            select(func.count(func.distinct(FactRegionDaily.region_id))).where(
                FactRegionDaily.stat_date >= start,
                FactRegionDaily.stat_date <= end,
                FactRegionDaily.region_id.is_not(None),
            )
        )
        jobs = await self.list_jobs(None, None, start, end, 1, 5)
        return AnalysisOverviewResponse(
            date_from=start,
            date_to=end,
            **self._workbench_meta(
                start,
                end,
                source_tables=["fact_freight_daily", "fact_ship_daily", "fact_region_daily"],
                sample_count=int(freight["freight_count"] + ship["ship_count"]),
                actions=[
                    AnalysisActionBlock(action_code="OPEN_FREIGHT_INSIGHT", title="查看货源洞察", target_route="/analysis/freight"),
                    AnalysisActionBlock(action_code="OPEN_CAPACITY_CENTER", title="查看运力中心", target_route="/analysis/ships"),
                ],
            ),
            metrics=[
                _metric("freight_count", "货源量", freight["freight_count"], "条"),
                _metric("freight_tonnage", "货源吨位", freight["total_tonnage"], "吨"),
                _metric("active_ship_count", "活跃船舶", ship["active_ship_count"], "艘"),
                _metric("region_count", "覆盖区域", region_count or 0, "个"),
            ],
            recent_jobs=jobs.items,
        )

    async def _freight_totals(self, start: date, end: date) -> dict[str, float]:
        row = (
            await self.db.execute(
                select(
                    func.coalesce(func.sum(FactFreightDaily.freight_count), 0),
                    func.coalesce(func.sum(FactFreightDaily.confirmed_count), 0),
                    func.coalesce(func.sum(FactFreightDaily.candidate_count), 0),
                    func.coalesce(func.sum(FactFreightDaily.source_inbound_count), 0),
                    func.coalesce(func.sum(FactFreightDaily.total_tonnage), 0),
                    func.coalesce(func.sum(FactFreightDaily.total_estimated_amount), 0),
                    func.avg(FactFreightDaily.avg_unit_price),
                ).where(FactFreightDaily.stat_date >= start, FactFreightDaily.stat_date <= end)
            )
        ).one()
        return {
            "freight_count": _num(row[0]),
            "confirmed_count": _num(row[1]),
            "candidate_count": _num(row[2]),
            "source_inbound_count": _num(row[3]),
            "total_tonnage": _num(row[4]),
            "total_amount": _num(row[5]),
            "avg_unit_price": _num(row[6]),
        }

    async def _ship_totals(self, start: date, end: date) -> dict[str, float]:
        latest_date = await self.db.scalar(
            select(func.max(FactShipDaily.stat_date)).where(FactShipDaily.stat_date >= start, FactShipDaily.stat_date <= end)
        )
        if latest_date is None:
            return {"ship_count": 0, "active_ship_count": 0, "total_deadweight_ton": 0}
        row = (
            await self.db.execute(
                select(
                    func.coalesce(func.sum(FactShipDaily.ship_count), 0),
                    func.coalesce(func.sum(FactShipDaily.active_ship_count), 0),
                    func.coalesce(func.sum(FactShipDaily.total_deadweight_ton), 0),
                ).where(FactShipDaily.stat_date == latest_date)
            )
        ).one()
        return {"ship_count": _num(row[0]), "active_ship_count": _num(row[1]), "total_deadweight_ton": _num(row[2])}

    async def freight_overview(self, date_from: date | None, date_to: date | None) -> FreightAnalysisOverviewResponse:
        start, end = await self._date_range(date_from, date_to)
        totals = await self._freight_totals(start, end)
        raw_quality = await self._freight_raw_quality()
        return FreightAnalysisOverviewResponse(
            date_from=start,
            date_to=end,
            **self._workbench_meta(
                start,
                end,
                source_tables=["freight", "freight_candidate", "fact_freight_daily", "fact_freight_flow_daily"],
                sample_count=int(totals["freight_count"]),
                actions=[
                    AnalysisActionBlock(action_code="OPEN_FREIGHT_LIST", title="查看机会样本库", target_route="/freight/list"),
                    AnalysisActionBlock(action_code="OPEN_FREIGHT_QUALITY", title="处理货源清洗", target_route="/freight/normalization"),
                ],
                uncertainty_reasons=["分页列表指标不得替代本接口聚合结果"],
            ),
            metrics=[
                _metric("freight_count", "货源量", totals["freight_count"], "条"),
                _metric("confirmed_count", "确认货源", totals["confirmed_count"], "条"),
                _metric("total_tonnage", "总吨位", totals["total_tonnage"], "吨"),
                _metric("avg_unit_price", "平均运价", totals["avg_unit_price"], "元/吨"),
                _metric("raw_level_count", "待清洗货源", raw_quality["raw_level_count"], "条", "原文级装卸地或货品仍需清洗提升"),
            ],
            trend=await self.freight_trend(start, end),
            node_ranking=await self.freight_node_ranking(start, end, 12),
            commodity_structure=await self.freight_commodity_structure(start, end),
            price_distribution=await self.freight_price_distribution(start, end),
            hot_routes=await self.freight_hot_routes(start, end, 8),
        )

    async def _freight_raw_quality(self) -> dict[str, int]:
        raw_level_count = int(
            await self.db.scalar(
                select(func.count(Freight.id)).where(
                    Freight.deleted_at.is_(None),
                    or_(
                        Freight.origin_match_level_code == "RAW",
                        Freight.destination_match_level_code == "RAW",
                        Freight.commodity_match_level_code == "RAW",
                        Freight.origin_city_code.is_(None),
                        Freight.destination_city_code.is_(None),
                        Freight.commodity_standard_id.is_(None),
                    ),
                )
            )
            or 0
        )
        return {"raw_level_count": raw_level_count}

    async def freight_trend(self, start: date, end: date) -> list[ChartPoint]:
        rows = (
            await self.db.execute(
                select(FactFreightDaily)
                .where(FactFreightDaily.stat_date >= start, FactFreightDaily.stat_date <= end)
                .order_by(FactFreightDaily.stat_date.asc())
            )
        ).scalars().all()
        return [
            ChartPoint(
                name=row.stat_date.strftime("%m-%d"),
                date=row.stat_date,
                value=row.freight_count,
                extra={"tonnage": _num(row.total_tonnage), "avg_unit_price": _num(row.avg_unit_price)},
            )
            for row in rows
        ]

    async def freight_commodity_structure(self, start: date, end: date) -> list[ChartPoint]:
        rows = (
            await self.db.execute(
                select(
                    CommodityStandard.name,
                    func.sum(FactFreightCommodityDaily.freight_count),
                    func.sum(FactFreightCommodityDaily.total_tonnage),
                )
                .join(CommodityStandard, CommodityStandard.id == FactFreightCommodityDaily.commodity_standard_id)
                .where(FactFreightCommodityDaily.stat_date >= start, FactFreightCommodityDaily.stat_date <= end)
                .group_by(CommodityStandard.name)
                .order_by(func.sum(FactFreightCommodityDaily.freight_count).desc())
                .limit(12)
            )
        ).all()
        total = sum(_num(row[1]) for row in rows)
        return [
            ChartPoint(name=row[0], value=int(_num(row[1])), ratio=_ratio(_num(row[1]), total), extra={"tonnage": _num(row[2])})
            for row in rows
        ]

    async def freight_node_ranking(self, start: date, end: date, limit: int = 12) -> list[HeatMapItem]:
        rows = (
            await self.db.execute(
                select(
                    FactFreightNodeDaily.node_id,
                    FactFreightNodeDaily.node_name,
                    TransportNode.longitude,
                    TransportNode.latitude,
                    FactFreightNodeDaily.city_code,
                    FactFreightNodeDaily.primary_region_id,
                    func.sum(FactFreightNodeDaily.heat_value),
                    func.sum(FactFreightNodeDaily.freight_count),
                    func.sum(FactFreightNodeDaily.inbound_count),
                    func.sum(FactFreightNodeDaily.outbound_count),
                    func.sum(FactFreightNodeDaily.total_tonnage),
                )
                .join(TransportNode, TransportNode.id == FactFreightNodeDaily.node_id)
                .where(FactFreightNodeDaily.stat_date >= start, FactFreightNodeDaily.stat_date <= end)
                .group_by(
                    FactFreightNodeDaily.node_id,
                    FactFreightNodeDaily.node_name,
                    TransportNode.longitude,
                    TransportNode.latitude,
                    FactFreightNodeDaily.city_code,
                    FactFreightNodeDaily.primary_region_id,
                )
                .order_by(func.sum(FactFreightNodeDaily.heat_value).desc())
                .limit(limit)
            )
        ).all()
        values = [_num(row[6]) for row in rows]
        high = max(values) if values else 0
        return [
            HeatMapItem(
                id=row[0],
                node_id=row[0],
                region_id=row[5],
                name=row[1] or str(row[0]),
                longitude=_num(row[2]) if row[2] is not None else None,
                latitude=_num(row[3]) if row[3] is not None else None,
                value=round(_num(row[6]), 2),
                level="HIGH" if high and _num(row[6]) >= high * 0.66 else "MEDIUM" if high and _num(row[6]) >= high * 0.33 else "LOW",
                freight_count=int(_num(row[7])),
                inbound_count=int(_num(row[8])),
                outbound_count=int(_num(row[9])),
                tonnage=round(_num(row[10]), 2),
            )
            for row in rows
        ]

    async def freight_tonnage_distribution(self, start: date, end: date) -> list[ChartPoint]:
        buckets = [
            ("600吨以下", 0, 600),
            ("600-1500吨", 600, 1500),
            ("1500-3000吨", 1500, 3000),
            ("3000-6000吨", 3000, 6000),
            ("6000吨以上", 6000, None),
        ]
        rows = (
            await self.db.execute(
                select(FactFreightFlowDaily.total_tonnage, FactFreightFlowDaily.freight_count)
                .where(FactFreightFlowDaily.stat_date >= start, FactFreightFlowDaily.stat_date <= end)
            )
        ).all()
        counts = {name: 0 for name, _, _ in buckets}
        for tonnage, count in rows:
            value = _num(tonnage)
            for name, low, high in buckets:
                if value >= low and (high is None or value < high):
                    counts[name] += int(count or 0)
                    break
        total = sum(counts.values())
        return [ChartPoint(name=name, value=value, ratio=_ratio(value, total)) for name, value in counts.items()]

    async def freight_price_distribution(self, start: date, end: date) -> list[ChartPoint]:
        rows = (
            await self.db.execute(
                select(
                    FactFreightPriceDaily.price_bucket_name,
                    func.sum(FactFreightPriceDaily.freight_count),
                    func.avg(FactFreightPriceDaily.avg_unit_price),
                )
                .where(FactFreightPriceDaily.stat_date >= start, FactFreightPriceDaily.stat_date <= end)
                .group_by(FactFreightPriceDaily.price_bucket_code, FactFreightPriceDaily.price_bucket_name)
                .order_by(func.min(FactFreightPriceDaily.min_unit_price).asc())
            )
        ).all()
        total = sum(_num(row[1]) for row in rows)
        return [
            ChartPoint(name=row[0], value=int(_num(row[1])), ratio=_ratio(_num(row[1]), total), extra={"avg_unit_price": _num(row[2])})
            for row in rows
        ]

    async def freight_hot_routes(
        self,
        start: date,
        end: date,
        limit: int = 10,
        *,
        route_geometry_mode: str = "cache",
        force_refresh_routes: bool = False,
    ) -> list[FlowMapItem]:
        origin = aliased(TransportNode)
        destination = aliased(TransportNode)
        origin_city = aliased(AdminRegion)
        destination_city = aliased(AdminRegion)
        rows = (
            await self.db.execute(
                select(
                    origin.id,
                    origin.name,
                    origin.longitude,
                    origin.latitude,
                    destination.id,
                    destination.name,
                    destination.longitude,
                    destination.latitude,
                    origin_city.name,
                    destination_city.name,
                    FactFreightFlowDaily.origin_city_code,
                    FactFreightFlowDaily.destination_city_code,
                    CommodityStandard.name,
                    func.sum(FactFreightFlowDaily.freight_count),
                    func.sum(FactFreightFlowDaily.total_tonnage),
                    func.avg(FactFreightFlowDaily.avg_unit_price),
                )
                .outerjoin(origin, origin.id == FactFreightFlowDaily.origin_node_id)
                .outerjoin(destination, destination.id == FactFreightFlowDaily.destination_node_id)
                .outerjoin(origin_city, origin_city.code == FactFreightFlowDaily.origin_city_code)
                .outerjoin(destination_city, destination_city.code == FactFreightFlowDaily.destination_city_code)
                .outerjoin(CommodityStandard, CommodityStandard.id == FactFreightFlowDaily.commodity_standard_id)
                .where(FactFreightFlowDaily.stat_date >= start, FactFreightFlowDaily.stat_date <= end)
                .group_by(
                    origin.id,
                    origin.name,
                    origin.longitude,
                    origin.latitude,
                    destination.id,
                    destination.name,
                    destination.longitude,
                    destination.latitude,
                    origin_city.name,
                    destination_city.name,
                    FactFreightFlowDaily.origin_city_code,
                    FactFreightFlowDaily.destination_city_code,
                    CommodityStandard.name,
                )
                .order_by(func.sum(FactFreightFlowDaily.freight_count).desc())
                .limit(limit)
            )
        ).all()
        items = [
            FlowMapItem(
                origin_id=row[0],
                origin_name=row[1] or row[8] or row[10] or "未知起点",
                origin_longitude=_num(row[2]) if row[2] is not None else None,
                origin_latitude=_num(row[3]) if row[3] is not None else None,
                destination_id=row[4],
                destination_name=row[5] or row[9] or row[11] or "未知终点",
                destination_longitude=_num(row[6]) if row[6] is not None else None,
                destination_latitude=_num(row[7]) if row[7] is not None else None,
                commodity_name=row[12],
                value=int(_num(row[13])),
                freight_count=int(_num(row[13])),
                tonnage=round(_num(row[14]), 2),
                avg_unit_price=round(_num(row[15]), 2),
            )
            for row in rows
        ]
        if route_geometry_mode == "none":
            return items
        return await self._attach_flow_route_geometries(
            items,
            segment_type="ANALYSIS_FREIGHT_FLOW_MAP",
            generate_missing=route_geometry_mode == "generate",
            force_refresh=force_refresh_routes,
        )

    async def ship_overview(self, date_from: date | None, date_to: date | None) -> ShipAnalysisOverviewResponse:
        start, end = await self._date_range(date_from, date_to)
        totals = await self._ship_totals(start, end)
        active_city_count = await self.db.scalar(
            select(func.count(func.distinct(FactShipCityDaily.city_code))).where(
                FactShipCityDaily.stat_date >= start,
                FactShipCityDaily.stat_date <= end,
                FactShipCityDaily.active_ship_count > 0,
            )
        )
        return ShipAnalysisOverviewResponse(
            date_from=start,
            date_to=end,
            **self._workbench_meta(
                start,
                end,
                source_tables=["vessel_profile", "fact_ship_daily", "fact_ship_city_daily"],
                sample_count=int(totals["ship_count"]),
                actions=[
                    AnalysisActionBlock(action_code="OPEN_CAPACITY_POOL", title="查看船舶台账", target_route="/vessels/assets"),
                    AnalysisActionBlock(action_code="OPEN_CANDIDATE_FIT", title="查看船货适配", target_route="/vessels/candidate-analysis"),
                ],
            ),
            metrics=[
                _metric("ship_count", "船舶总量", totals["ship_count"], "艘"),
                _metric("active_ship_count", "活跃船舶", totals["active_ship_count"], "艘"),
                _metric("deadweight", "总载重吨", totals["total_deadweight_ton"], "吨"),
                _metric("active_city_count", "活跃城市", active_city_count or 0, "个"),
            ],
            type_distribution=await self.ship_type_distribution(start, end),
            age_distribution=await self.ship_age_distribution(start, end),
            deadweight_distribution=await self.ship_deadweight_distribution(start, end),
            active_trend=await self.ship_active_trend(start, end),
        )

    async def ship_type_distribution(self, start: date, end: date) -> list[ChartPoint]:
        labels = await self._dict_labels(["SHIP_TYPE"])
        latest = await self.db.scalar(select(func.max(FactShipDaily.stat_date)).where(FactShipDaily.stat_date >= start, FactShipDaily.stat_date <= end))
        if latest is None:
            return []
        rows = (
            await self.db.execute(
                select(FactShipDaily.ship_type_code, func.sum(FactShipDaily.ship_count))
                .where(FactShipDaily.stat_date == latest)
                .group_by(FactShipDaily.ship_type_code)
                .order_by(func.sum(FactShipDaily.ship_count).desc())
            )
        ).all()
        total = sum(_num(row[1]) for row in rows)
        return [
            ChartPoint(name=labels.get("SHIP_TYPE", {}).get(row[0] or "", row[0] or "未知船型"), value=int(_num(row[1])), ratio=_ratio(_num(row[1]), total))
            for row in rows
        ]

    async def ship_age_distribution(self, start: date, end: date) -> list[ChartPoint]:
        latest = await self.db.scalar(select(func.max(FactShipDaily.stat_date)).where(FactShipDaily.stat_date >= start, FactShipDaily.stat_date <= end))
        if latest is None:
            return []
        rows = (
            await self.db.execute(
                select(FactShipDaily.age_bucket_name, func.sum(FactShipDaily.ship_count))
                .where(FactShipDaily.stat_date == latest, FactShipDaily.age_bucket_name.is_not(None))
                .group_by(FactShipDaily.age_bucket_code, FactShipDaily.age_bucket_name)
                .order_by(FactShipDaily.age_bucket_code.asc())
            )
        ).all()
        total = sum(_num(row[1]) for row in rows)
        return [ChartPoint(name=row[0] or "未知船龄", value=int(_num(row[1])), ratio=_ratio(_num(row[1]), total)) for row in rows]

    async def ship_deadweight_distribution(self, start: date, end: date) -> list[ChartPoint]:
        latest = await self.db.scalar(select(func.max(FactShipDaily.stat_date)).where(FactShipDaily.stat_date >= start, FactShipDaily.stat_date <= end))
        if latest is None:
            return []
        rows = (
            await self.db.execute(
                select(FactShipDaily.deadweight_bucket_name, func.sum(FactShipDaily.ship_count))
                .where(FactShipDaily.stat_date == latest, FactShipDaily.deadweight_bucket_name.is_not(None))
                .group_by(FactShipDaily.deadweight_bucket_code, FactShipDaily.deadweight_bucket_name)
                .order_by(FactShipDaily.deadweight_bucket_code.asc())
            )
        ).all()
        total = sum(_num(row[1]) for row in rows)
        return [ChartPoint(name=row[0] or "未知载重", value=int(_num(row[1])), ratio=_ratio(_num(row[1]), total)) for row in rows]

    async def ship_active_trend(self, start: date, end: date) -> list[ChartPoint]:
        rows = (
            await self.db.execute(
                select(FactShipDaily.stat_date, func.sum(FactShipDaily.active_ship_count))
                .where(FactShipDaily.stat_date >= start, FactShipDaily.stat_date <= end)
                .group_by(FactShipDaily.stat_date)
                .order_by(FactShipDaily.stat_date.asc())
            )
        ).all()
        return [ChartPoint(name=row[0].strftime("%m-%d"), date=row[0], value=int(_num(row[1]))) for row in rows]

    async def ship_flow_map(
        self,
        start: date,
        end: date,
        limit: int = 30,
        *,
        route_geometry_mode: str = "cache",
        force_refresh_routes: bool = False,
    ) -> list[FlowMapItem]:
        origin = aliased(TransportNode)
        destination = aliased(TransportNode)
        rows = (
            await self.db.execute(
                select(
                    origin.id,
                    origin.name,
                    origin.longitude,
                    origin.latitude,
                    destination.id,
                    destination.name,
                    destination.longitude,
                    destination.latitude,
                    func.sum(FactShipFlowDaily.ship_count),
                    func.sum(FactShipFlowDaily.voyage_count),
                    func.sum(FactShipFlowDaily.total_deadweight_ton),
                )
                .join(origin, origin.id == FactShipFlowDaily.origin_node_id)
                .join(destination, destination.id == FactShipFlowDaily.destination_node_id)
                .where(FactShipFlowDaily.stat_date >= start, FactShipFlowDaily.stat_date <= end)
                .group_by(origin.id, origin.name, origin.longitude, origin.latitude, destination.id, destination.name, destination.longitude, destination.latitude)
                .order_by(func.sum(FactShipFlowDaily.voyage_count).desc())
                .limit(limit)
            )
        ).all()
        items = [
            FlowMapItem(
                origin_id=row[0],
                origin_name=row[1],
                origin_longitude=_num(row[2]) if row[2] is not None else None,
                origin_latitude=_num(row[3]) if row[3] is not None else None,
                destination_id=row[4],
                destination_name=row[5],
                destination_longitude=_num(row[6]) if row[6] is not None else None,
                destination_latitude=_num(row[7]) if row[7] is not None else None,
                value=int(_num(row[9])),
                ship_count=int(_num(row[8])),
                voyage_count=int(_num(row[9])),
                tonnage=round(_num(row[10]), 2),
            )
            for row in rows
        ]
        if route_geometry_mode == "none":
            return items
        return await self._attach_flow_route_geometries(
            items,
            segment_type="ANALYSIS_SHIP_FLOW_MAP",
            generate_missing=route_geometry_mode == "generate",
            force_refresh=force_refresh_routes,
        )

    async def region_overview(
        self,
        date_from: date | None,
        date_to: date | None,
        *,
        include_boundary: bool = False,
        boundary_precision: str = "low",
    ) -> RegionAnalysisOverviewResponse:
        start, end = await self._date_range(date_from, date_to)
        rows = (
            await self.db.execute(
                select(Region.name, func.sum(FactRegionDaily.freight_count), func.sum(FactRegionDaily.total_tonnage))
                .join(Region, Region.id == FactRegionDaily.region_id)
                .where(FactRegionDaily.stat_date >= start, FactRegionDaily.stat_date <= end)
                .group_by(Region.name)
                .order_by(func.sum(FactRegionDaily.freight_count).desc())
                .limit(12)
            )
        ).all()
        total_freight = sum(_num(row[1]) for row in rows)
        heat = await self.region_heat_map(
            start,
            end,
            include_boundary=include_boundary,
            boundary_precision=boundary_precision,
        )
        return RegionAnalysisOverviewResponse(
            date_from=start,
            date_to=end,
            **self._workbench_meta(
                start,
                end,
                source_tables=["region", "fact_region_daily", "admin_region_boundary"],
                sample_count=int(total_freight),
                actions=[
                    AnalysisActionBlock(action_code="OPEN_FLOW_ANALYSIS", title="查看区域流向", target_route="/analysis/flows"),
                    AnalysisActionBlock(action_code="OPEN_ROUTE_LIST", title="查看航线列表", target_route="/route/list"),
                ],
            ),
            metrics=[
                _metric("region_count", "活跃区域", len(rows), "个"),
                _metric("freight_count", "区域货源", total_freight, "条"),
                _metric("heat_city_count", "热力城市", len(heat), "个"),
            ],
            region_ranking=[
                ChartPoint(name=row[0], value=int(_num(row[1])), ratio=_ratio(_num(row[1]), total_freight), extra={"tonnage": _num(row[2])})
                for row in rows
            ],
            heat_map=heat,
        )

    async def region_heat_map(
        self,
        start: date,
        end: date,
        *,
        include_boundary: bool = False,
        boundary_precision: str = "low",
    ) -> list[BoundaryHeatMapItem]:
        rows = (
            await self.db.execute(
                select(
                    AdminRegion.id,
                    FactFreightCityDaily.city_code,
                    func.max(FactFreightCityDaily.city_name),
                    AdminRegion.name,
                    AdminRegion.longitude,
                    AdminRegion.latitude,
                    func.max(FactFreightCityDaily.primary_region_id),
                    AdminRegionBoundary.id,
                    AdminRegionBoundary.center_longitude,
                    AdminRegionBoundary.center_latitude,
                    func.sum(FactFreightCityDaily.heat_value),
                    func.sum(FactFreightCityDaily.freight_count),
                    func.sum(FactFreightCityDaily.inbound_count),
                    func.sum(FactFreightCityDaily.outbound_count),
                    func.sum(FactFreightCityDaily.total_tonnage),
                    func.avg(FactFreightCityDaily.avg_unit_price),
                )
                .outerjoin(AdminRegion, AdminRegion.code == FactFreightCityDaily.city_code)
                .outerjoin(
                    AdminRegionBoundary,
                    (AdminRegionBoundary.admin_region_id == AdminRegion.id) & (AdminRegionBoundary.is_current.is_(True)),
                )
                .where(FactFreightCityDaily.stat_date >= start, FactFreightCityDaily.stat_date <= end)
                .group_by(
                    FactFreightCityDaily.city_code,
                    AdminRegion.id,
                    AdminRegion.name,
                    AdminRegion.longitude,
                    AdminRegion.latitude,
                    AdminRegionBoundary.id,
                    AdminRegionBoundary.center_longitude,
                    AdminRegionBoundary.center_latitude,
                )
                .order_by(func.sum(FactFreightCityDaily.heat_value).desc())
            )
        ).all()
        boundary_geometry_by_admin_id: dict[int, dict] = {}
        if include_boundary:
            admin_region_ids = [int(row[0]) for row in rows if row[0] is not None and row[7] is not None]
            if admin_region_ids:
                boundary_rows = (
                    await self.db.execute(
                        select(AdminRegionBoundary.admin_region_id, AdminRegionBoundary.geometry_json)
                        .where(
                            AdminRegionBoundary.admin_region_id.in_(admin_region_ids),
                            AdminRegionBoundary.is_current.is_(True),
                        )
                    )
                ).all()
                boundary_geometry_by_admin_id = {int(row[0]): row[1] for row in boundary_rows if row[1]}

        values = [_num(row[10]) for row in rows]
        high = max(values) if values else 0
        items: list[BoundaryHeatMapItem] = []
        for row in rows:
            boundary_paths = None
            if include_boundary and row[0] is not None:
                polygons = extract_geojson_polygons(boundary_geometry_by_admin_id.get(int(row[0])) or {})
                boundary_paths = serialize_boundary_paths(boundary_paths_for_precision(polygons, boundary_precision))

            center_longitude = row[8] if row[8] is not None else row[4]
            center_latitude = row[9] if row[9] is not None else row[5]
            value = _num(row[10])
            items.append(
                BoundaryHeatMapItem(
                    id=row[0],
                    city_code=row[1],
                    region_id=row[6],
                    name=row[3] or row[2] or row[1] or "未知城市",
                    value=round(value, 2),
                    level="HIGH"
                    if high and value >= high * 0.66
                    else "MEDIUM"
                    if high and value >= high * 0.33
                    else "LOW",
                    boundary_paths=boundary_paths,
                    has_boundary=bool(boundary_paths) if include_boundary else bool(row[7]),
                    boundary_precision=boundary_precision if boundary_paths else None,
                    center_longitude=_num(center_longitude) if center_longitude is not None else None,
                    center_latitude=_num(center_latitude) if center_latitude is not None else None,
                    freight_count=int(_num(row[11])),
                    inbound_count=int(_num(row[12])),
                    outbound_count=int(_num(row[13])),
                    tonnage=round(_num(row[14]), 2),
                    avg_unit_price=round(_num(row[15]), 2) if row[15] is not None else None,
                )
            )
        return items

    async def flow_overview(self, date_from: date | None, date_to: date | None) -> FlowAnalysisOverviewResponse:
        start, end = await self._date_range(date_from, date_to)
        freight_flows = await self.freight_hot_routes(start, end, 20)
        ship_flows = await self.ship_flow_map(start, end, 20)
        return FlowAnalysisOverviewResponse(
            date_from=start,
            date_to=end,
            **self._workbench_meta(
                start,
                end,
                source_tables=["fact_freight_flow_daily", "fact_ship_flow_daily", "shipping_route_line_track"],
                sample_count=len(freight_flows) + len(ship_flows),
                actions=[
                    AnalysisActionBlock(action_code="PRECOMPUTE_FLOW_ROUTES", title="生成 AMMS 流向轨迹", target_route="/analysis/flows"),
                    AnalysisActionBlock(action_code="OPEN_ROUTE_LIST", title="查看航线规划", target_route="/route/list"),
                ],
                uncertainty_reasons=["流向地图只使用 READY 轨迹绘制，失败或待生成状态需查看 route_not_computable_reasons"],
            ),
            metrics=[
                _metric("freight_flow_count", "货源流向", len(freight_flows), "条"),
                _metric("ship_flow_count", "船舶流向", len(ship_flows), "条"),
                _metric("top_freight_route", "最热货源流向", freight_flows[0].freight_count if freight_flows else 0, "条"),
                _metric("top_ship_route", "最热船舶流向", ship_flows[0].voyage_count if ship_flows else 0, "航次"),
            ],
            freight_flows=freight_flows,
            ship_flows=ship_flows,
        )

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
            all_items.extend(
                await self.freight_hot_routes(
                    start,
                    end,
                    limit,
                    route_geometry_mode="generate",
                    force_refresh_routes=force_refresh,
                )
            )
        if "ship" in normalized_types:
            all_items.extend(
                await self.ship_flow_map(
                    start,
                    end,
                    limit,
                    route_geometry_mode="generate",
                    force_refresh_routes=force_refresh,
                )
            )
        counts = self._flow_route_cache_counts(all_items)
        return FlowRouteCachePrecomputeResponse(
            status_code="SUCCESS",
            message="AMMS 流向轨迹缓存已生成",
            date_from=start,
            date_to=end,
            **counts,
        )

    async def price_overview(self, date_from: date | None, date_to: date | None) -> PriceAnalysisOverviewResponse:
        start, end = await self._date_range(date_from, date_to)
        price_rows = (
            await self.db.execute(
                select(FactFreightDaily.stat_date, func.avg(FactFreightDaily.avg_unit_price))
                .where(FactFreightDaily.stat_date >= start, FactFreightDaily.stat_date <= end)
                .group_by(FactFreightDaily.stat_date)
                .order_by(FactFreightDaily.stat_date.asc())
            )
        ).all()
        commodity_rows = (
            await self.db.execute(
                select(CommodityStandard.name, func.avg(FactFreightCommodityDaily.avg_unit_price), func.sum(FactFreightCommodityDaily.freight_count))
                .join(CommodityStandard, CommodityStandard.id == FactFreightCommodityDaily.commodity_standard_id)
                .where(FactFreightCommodityDaily.stat_date >= start, FactFreightCommodityDaily.stat_date <= end)
                .group_by(CommodityStandard.name)
                .order_by(func.sum(FactFreightCommodityDaily.freight_count).desc())
                .limit(12)
            )
        ).all()
        route_prices = await self.freight_hot_routes(start, end, 10)
        latest_price = _num(price_rows[-1][1]) if price_rows else 0
        return PriceAnalysisOverviewResponse(
            date_from=start,
            date_to=end,
            **self._workbench_meta(
                start,
                end,
                source_tables=["fact_freight_daily", "fact_freight_price_daily", "fact_freight_commodity_daily"],
                sample_count=len(price_rows),
                actions=[
                    AnalysisActionBlock(action_code="OPEN_QUOTE_SIMULATOR", title="进入智能报价测算", target_route="/analysis/quote-simulator"),
                    AnalysisActionBlock(action_code="OPEN_FREIGHT_LIST", title="查看有价货源", target_route="/freight/list"),
                ],
            ),
            metrics=[
                _metric("avg_unit_price", "平均运价", latest_price, "元/吨"),
                _metric("priced_routes", "有价线路", len(route_prices), "条"),
                _metric("commodity_price_count", "覆盖货品", len(commodity_rows), "类"),
            ],
            price_trend=[
                ChartPoint(name=row[0].strftime("%m-%d"), date=row[0], value=round(_num(row[1]), 2))
                for row in price_rows
            ],
            price_distribution=await self.freight_price_distribution(start, end),
            commodity_prices=[
                ChartPoint(name=row[0], value=round(_num(row[1]), 2), extra={"freight_count": int(_num(row[2]))})
                for row in commodity_rows
            ],
            route_prices=route_prices,
        )

    async def _last_successful_run_at(self, job_code: str) -> datetime | None:
        row = await self.db.scalar(select(AnalysisJobDefinition).where(AnalysisJobDefinition.job_code == job_code))
        if row and row.last_status_code == "SUCCESS":
            return row.last_finished_at
        latest = await self.db.scalar(
            select(func.max(AnalysisJobRun.finished_at)).where(
                AnalysisJobRun.job_code == job_code,
                AnalysisJobRun.status_code == "SUCCESS",
            )
        )
        return latest

    def _source_status(self, rows: list[Any], start: date, end: date, last_successful_run_at: datetime | None) -> list[MetricEvidence]:
        if not rows:
            return [
                MetricEvidence(
                    metric_code="source_status",
                    value=None,
                    unit=None,
                    date_from=start,
                    date_to=end,
                    source_layer_code="NOT_AVAILABLE",
                    sample_count=0,
                    coverage_rate=0,
                    confidence_level="UNKNOWN",
                    not_computable_reasons=["SOURCE_MISSING"],
                    uncertainty_reasons=["分析事实未生成"],
                    last_successful_run_at=last_successful_run_at,
                )
            ]
        buckets: dict[tuple[str | None, str | None], dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "sample": 0, "coverage": [], "reasons": set(), "updated": None, "generated": None}
        )
        for row in rows:
            key = (getattr(row, "source_layer_code", None), getattr(row, "confidence_level", None))
            item = buckets[key]
            item["count"] += 1
            item["sample"] += int(getattr(row, "sample_count", None) or 0)
            coverage = getattr(row, "coverage_rate", None)
            if coverage is not None:
                item["coverage"].append(_num(coverage))
            item["reasons"].update(_reasons(getattr(row, "not_computable_reasons_json", None)))
            for field, attr in (("updated", "source_updated_at"), ("generated", "generated_at")):
                value = getattr(row, attr, None)
                if value and (item[field] is None or value > item[field]):
                    item[field] = value
        return [
            MetricEvidence(
                metric_code="source_status",
                value=item["count"],
                unit="条",
                date_from=start,
                date_to=end,
                source_layer_code=source_layer,
                sample_count=item["sample"],
                coverage_rate=round(sum(item["coverage"]) / len(item["coverage"]), 2) if item["coverage"] else None,
                confidence_level=confidence,
                not_computable_reasons=sorted(item["reasons"]),
                generated_at=item["generated"],
                source_updated_at=item["updated"],
                last_successful_run_at=last_successful_run_at,
            )
            for (source_layer, confidence), item in sorted(buckets.items(), key=lambda pair: str(pair[0]))
        ]

    async def vessel_asset_analysis(self, date_from: date | None, date_to: date | None) -> VesselAssetAnalysisResponse:
        start, end = await self._date_range(date_from, date_to)
        rows = (
            await self.db.execute(
                select(FactVesselAssetDaily)
                .where(FactVesselAssetDaily.stat_date >= start, FactVesselAssetDaily.stat_date <= end)
                .order_by(FactVesselAssetDaily.stat_date.asc())
            )
        ).scalars().all()
        ref = rows[0] if rows else None
        last = await self._last_successful_run_at("ANALYSIS_VESSEL_ASSET_DAILY")
        latest_date = max((row.stat_date for row in rows), default=None)
        latest_rows = [row for row in rows if row.stat_date == latest_date] if latest_date else []
        quality_totals: dict[str, int] = defaultdict(int)
        risk_totals: dict[str, int] = defaultdict(int)
        for row in latest_rows:
            quality_totals[row.quality_level] += int(row.profile_count or 0)
            risk_totals[row.risk_level] += int(row.profile_count or 0)
        return VesselAssetAnalysisResponse(
            date_from=start,
            date_to=end,
            metrics=[
                _evidence("profile_count", sum(row.profile_count or 0 for row in latest_rows), unit="艘", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("trusted_profile_count", sum(row.trusted_profile_count or 0 for row in latest_rows), unit="艘", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("low_quality_count", sum(row.low_quality_count or 0 for row in latest_rows), unit="艘", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("active_sample_count", sum(row.active_sample_count or 0 for row in latest_rows), unit="艘", start=start, end=end, row=ref, last_successful_run_at=last),
            ],
            quality_distribution=[ChartPoint(name=key, value=value) for key, value in sorted(quality_totals.items())],
            risk_distribution=[ChartPoint(name=key, value=value) for key, value in sorted(risk_totals.items())],
            source_status=self._source_status(rows, start, end, last),
        )

    async def vessel_trajectory_analysis(self, date_from: date | None, date_to: date | None) -> VesselTrajectoryAnalysisResponse:
        start, end = await self._date_range(date_from, date_to)
        rows = (
            await self.db.execute(
                select(FactVesselTrajectoryDaily)
                .where(FactVesselTrajectoryDaily.stat_date >= start, FactVesselTrajectoryDaily.stat_date <= end)
                .order_by(FactVesselTrajectoryDaily.stat_date.asc())
            )
        ).scalars().all()
        ref = rows[0] if rows else None
        last = await self._last_successful_run_at("ANALYSIS_VESSEL_TRAJECTORY_DAILY")
        by_date: dict[date, list[FactVesselTrajectoryDaily]] = defaultdict(list)
        gap_buckets: dict[str, int] = defaultdict(int)
        for row in rows:
            by_date[row.stat_date].append(row)
            gap_buckets["有断点" if int(row.gap_count or 0) > 0 else "无断点"] += 1
        coverage_trend = []
        for stat_date, day_rows in sorted(by_date.items()):
            coverages = [_num(row.coverage_rate) for row in day_rows if row.coverage_rate is not None]
            coverage_trend.append(ChartPoint(name=stat_date.strftime("%m-%d"), date=stat_date, value=round(sum(coverages) / len(coverages), 2) if coverages else 0))
        return VesselTrajectoryAnalysisResponse(
            date_from=start,
            date_to=end,
            metrics=[
                _evidence("route_match_count", sum(row.route_match_count or 0 for row in rows), unit="次", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("gap_count", sum(row.gap_count or 0 for row in rows), unit="个", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("not_computable_count", sum(1 for row in rows if row.not_computable_reasons_json), unit="条", start=start, end=end, row=ref, last_successful_run_at=last),
            ],
            coverage_trend=coverage_trend,
            gap_distribution=[ChartPoint(name=key, value=value) for key, value in sorted(gap_buckets.items())],
            source_status=self._source_status(rows, start, end, last),
        )

    async def vessel_quality_analysis(self, date_from: date | None, date_to: date | None) -> VesselQualityAnalysisResponse:
        start, end = await self._date_range(date_from, date_to)
        rows = (
            await self.db.execute(
                select(FactVesselQualityDaily).where(FactVesselQualityDaily.stat_date >= start, FactVesselQualityDaily.stat_date <= end)
            )
        ).scalars().all()
        ref = rows[0] if rows else None
        last = await self._last_successful_run_at("ANALYSIS_VESSEL_QUALITY_DAILY")
        issue_totals: dict[str, int] = defaultdict(int)
        severity_totals: dict[str, int] = defaultdict(int)
        for row in rows:
            count = int(row.opened_count or 0) + int(row.closed_count or 0)
            issue_totals[row.issue_type_code] += count
            severity_totals[row.severity_code] += count
        return VesselQualityAnalysisResponse(
            date_from=start,
            date_to=end,
            metrics=[
                _evidence("opened_count", sum(row.opened_count or 0 for row in rows), unit="条", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("closed_count", sum(row.closed_count or 0 for row in rows), unit="条", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("avg_close_hours", sum(_num(row.avg_close_hours) for row in rows) / len(rows) if rows else None, unit="小时", start=start, end=end, row=ref, last_successful_run_at=last),
            ],
            issue_distribution=[ChartPoint(name=key, value=value) for key, value in sorted(issue_totals.items())],
            severity_distribution=[ChartPoint(name=key, value=value) for key, value in sorted(severity_totals.items())],
            source_status=self._source_status(rows, start, end, last),
        )

    async def vessel_risk_analysis(self, date_from: date | None, date_to: date | None) -> VesselRiskAnalysisResponse:
        start, end = await self._date_range(date_from, date_to)
        rows = (
            await self.db.execute(
                select(FactVesselRiskDaily).where(FactVesselRiskDaily.stat_date >= start, FactVesselRiskDaily.stat_date <= end)
            )
        ).scalars().all()
        ref = rows[0] if rows else None
        last = await self._last_successful_run_at("ANALYSIS_VESSEL_RISK_DAILY")
        level_totals: dict[str, int] = defaultdict(int)
        type_totals: dict[str, int] = defaultdict(int)
        for row in rows:
            level_totals[row.risk_level] += int(row.risk_count or 0)
            type_totals[row.risk_type_code] += int(row.risk_count or 0)
        return VesselRiskAnalysisResponse(
            date_from=start,
            date_to=end,
            metrics=[
                _evidence("risk_count", sum(row.risk_count or 0 for row in rows), unit="条", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("high_count", sum(row.high_count or 0 for row in rows), unit="条", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("unknown_count", sum(row.unknown_count or 0 for row in rows), unit="条", start=start, end=end, row=ref, last_successful_run_at=last),
            ],
            risk_level_distribution=[ChartPoint(name=key, value=value) for key, value in sorted(level_totals.items())],
            risk_type_distribution=[ChartPoint(name=key, value=value) for key, value in sorted(type_totals.items())],
            source_status=self._source_status(rows, start, end, last),
        )

    async def vessel_candidate_fit_analysis(self, date_from: date | None, date_to: date | None) -> VesselCandidateFitAnalysisResponse:
        start, end = await self._date_range(date_from, date_to)
        rows = (
            await self.db.execute(
                select(FactCandidateFitDaily).where(FactCandidateFitDaily.stat_date >= start, FactCandidateFitDaily.stat_date <= end)
            )
        ).scalars().all()
        ref = rows[0] if rows else None
        last = await self._last_successful_run_at("ANALYSIS_CANDIDATE_FIT_DAILY")
        value_totals: dict[str, int] = defaultdict(int)
        annotation_totals: dict[str, int] = defaultdict(int)
        for row in rows:
            value_totals[row.candidate_value_level] += int(row.candidate_item_count or 0)
            for key, value in (row.annotation_distribution_json or {}).items():
                annotation_totals[str(key)] += int(value or 0)
        return VesselCandidateFitAnalysisResponse(
            date_from=start,
            date_to=end,
            metrics=[
                _evidence("analysis_count", sum(row.analysis_count or 0 for row in rows), unit="次", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("candidate_item_count", sum(row.candidate_item_count or 0 for row in rows), unit="条", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("low_confidence_count", sum(row.low_confidence_count or 0 for row in rows), unit="条", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("not_computable_count", sum(row.not_computable_count or 0 for row in rows), unit="条", start=start, end=end, row=ref, last_successful_run_at=last),
            ],
            value_distribution=[ChartPoint(name=key, value=value) for key, value in sorted(value_totals.items())],
            annotation_distribution=[ChartPoint(name=key, value=value) for key, value in sorted(annotation_totals.items())],
            source_status=self._source_status(rows, start, end, last),
        )

    async def region_supply_demand_analysis(self, date_from: date | None, date_to: date | None) -> RegionSupplyDemandAnalysisResponse:
        start, end = await self._date_range(date_from, date_to)
        rows = (
            await self.db.execute(
                select(FactRegionSupplyDemandDaily).where(
                    FactRegionSupplyDemandDaily.stat_date >= start,
                    FactRegionSupplyDemandDaily.stat_date <= end,
                )
            )
        ).scalars().all()
        ref = rows[0] if rows else None
        last = await self._last_successful_run_at("ANALYSIS_REGION_SUPPLY_DEMAND_DAILY")
        tension_distribution: dict[str, int] = defaultdict(int)
        not_computable_distribution: dict[str, int] = defaultdict(int)
        for row in rows:
            if row.tension_index is None:
                tension_distribution["不可计算"] += 1
            elif _num(row.tension_index) >= 1.5:
                tension_distribution["高张力"] += 1
            elif _num(row.tension_index) >= 0.8:
                tension_distribution["中张力"] += 1
            else:
                tension_distribution["低张力"] += 1
            for reason in _reasons(row.not_computable_reasons_json):
                not_computable_distribution[reason] += 1
        return RegionSupplyDemandAnalysisResponse(
            date_from=start,
            date_to=end,
            metrics=[
                _evidence("demand_sample_count", sum(row.demand_sample_count or 0 for row in rows), unit="条", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("ais_supply_count", sum(row.ais_supply_count or 0 for row in rows), unit="艘", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("trusted_supply", sum(row.trusted_supply or 0 for row in rows), unit="艘", start=start, end=end, row=ref, last_successful_run_at=last),
                _evidence("unmatched_mmsi_count", sum(row.unmatched_mmsi_count or 0 for row in rows), unit="条", start=start, end=end, row=ref, last_successful_run_at=last),
            ],
            tension_distribution=[ChartPoint(name=key, value=value) for key, value in sorted(tension_distribution.items())],
            not_computable_distribution=[ChartPoint(name=key, value=value) for key, value in sorted(not_computable_distribution.items())],
            source_status=self._source_status(rows, start, end, last),
        )

    async def list_jobs(
        self,
        module_code: str | None,
        status_code: str | None,
        date_from: date | None,
        date_to: date | None,
        page: int,
        page_size: int,
    ) -> PageResponse[AnalysisJobRunResponse]:
        stmt = select(AnalysisJobRun)
        if module_code:
            stmt = stmt.where(AnalysisJobRun.module_code == module_code)
        if status_code:
            stmt = stmt.where(AnalysisJobRun.status_code == status_code)
        if date_from:
            stmt = stmt.where(AnalysisJobRun.stat_date_to >= date_from)
        if date_to:
            stmt = stmt.where(AnalysisJobRun.stat_date_from <= date_to)

        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(AnalysisJobRun.created_at.desc(), AnalysisJobRun.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return PageResponse[AnalysisJobRunResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_job_to_response(row) for row in rows],
        )

    async def get_job_detail(self, job_run_id: int) -> AnalysisJobRunDetailResponse:
        row = await self.db.scalar(select(AnalysisJobRun).where(AnalysisJobRun.id == job_run_id))
        if row is None:
            raise NotFoundError("AnalysisJobRun", job_run_id)
        base = _job_to_response(row).model_dump()
        return AnalysisJobRunDetailResponse(
            **base,
            parameters_json=row.parameters_json,
            result_summary_json=row.result_summary_json,
        )

    async def list_tasks(
        self,
        module_code: str | None,
        enabled: bool | None,
        page: int,
        page_size: int,
    ) -> PageResponse[AnalysisTaskResponse]:
        stmt = select(AnalysisJobDefinition)
        if module_code:
            stmt = stmt.where(AnalysisJobDefinition.module_code == module_code)
        if enabled is not None:
            stmt = stmt.where(AnalysisJobDefinition.enabled == enabled)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(AnalysisJobDefinition.sort_order.asc(), AnalysisJobDefinition.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return PageResponse[AnalysisTaskResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_task_to_response(row) for row in rows],
        )

    async def get_task_detail(self, job_code: str) -> AnalysisTaskDetailResponse:
        row = await self.db.scalar(select(AnalysisJobDefinition).where(AnalysisJobDefinition.job_code == job_code))
        if row is None:
            raise NotFoundError("AnalysisJobDefinition", job_code)
        runs = (
            await self.db.execute(
                select(AnalysisJobRun)
                .where(AnalysisJobRun.job_code == job_code)
                .order_by(AnalysisJobRun.created_at.desc(), AnalysisJobRun.id.desc())
                .limit(20)
            )
        ).scalars().all()
        base = _task_to_response(row).model_dump()
        return AnalysisTaskDetailResponse(**base, recent_runs=[_job_to_response(item) for item in runs])

    async def list_task_runs(
        self,
        job_code: str,
        status_code: str | None,
        date_from: date | None,
        date_to: date | None,
        page: int,
        page_size: int,
    ) -> PageResponse[AnalysisJobRunResponse]:
        stmt = select(AnalysisJobRun).where(AnalysisJobRun.job_code == job_code)
        if status_code:
            stmt = stmt.where(AnalysisJobRun.status_code == status_code)
        if date_from:
            stmt = stmt.where(AnalysisJobRun.stat_date_to >= date_from)
        if date_to:
            stmt = stmt.where(AnalysisJobRun.stat_date_from <= date_to)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(AnalysisJobRun.created_at.desc(), AnalysisJobRun.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return PageResponse[AnalysisJobRunResponse](total=total, page=page, page_size=page_size, items=[_job_to_response(row) for row in rows])

    async def trigger_task(self, job_code: str, payload: AnalysisTaskTriggerRequest, triggered_by: str | None) -> AnalysisJobRunResponse:
        definition = await self.db.scalar(select(AnalysisJobDefinition).where(AnalysisJobDefinition.job_code == job_code))
        if definition is None:
            raise NotFoundError("AnalysisJobDefinition", job_code)
        if not definition.enabled:
            raise ValidationError("分析任务已停用，不能手动触发", {"job_code": job_code})
        now = datetime.utcnow()
        parameters = {
            **(definition.default_parameters_json or {}),
            **(payload.parameters_json or {}),
            "force_rebuild": payload.force_rebuild,
        }
        run = AnalysisJobRun(
            job_code=definition.job_code,
            job_name=definition.job_name,
            module_code=definition.module_code,
            module_name=definition.module_name,
            stat_date_from=payload.date_from,
            stat_date_to=payload.date_to,
            status_code="QUEUED",
            status_name=_status_name("QUEUED"),
            queued_at=now,
            parameters_json=parameters,
            triggered_by=triggered_by,
            created_at=now,
        )
        self.db.add(run)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(run)

        try:
            from app.tasks.analysis_tasks import run_analysis_job

            async_result = run_analysis_job.apply_async(
                args=[
                    definition.job_code,
                    payload.date_from.isoformat(),
                    payload.date_to.isoformat(),
                    payload.force_rebuild,
                    {"job_run_id": run.id, "triggered_by": triggered_by, **(payload.parameters_json or {})},
                ],
                queue="analysis",
            )
            run.celery_task_id = async_result.id
        except Exception as exc:
            run.status_code = "FAILED"
            run.status_name = _status_name("FAILED")
            run.finished_at = datetime.utcnow()
            run.error_message = f"Celery 任务投递失败：{exc}"
            await self.db.commit()
            raise ValidationError("Celery 任务投递失败，请确认 Redis 和 analysis-worker 已启动", {"error": str(exc)}) from exc
        await self.db.commit()
        await self.db.refresh(run)
        return _job_to_response(run)
