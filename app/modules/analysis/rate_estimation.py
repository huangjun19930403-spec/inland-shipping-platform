"""Comparable-sample weighting for unknown freight-rate estimates."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.address import TransportNode
from app.models.freight import Freight

LOCAL_ENVIRONMENTS = {"local", "dev", "development", "test", "testing"}


@dataclass
class WeightedRateSample:
    row: Freight
    price: float
    weight: float
    factor_breakdown: dict[str, float]
    distance_km: float | None = None


def num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def round_number(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None and math.isfinite(value) else None


def is_demo_freight(row: Freight) -> bool:
    values = [row.freight_no, row.source_ref_no, row.source_type_code, row.source_channel_code]
    return any("DEMO" in str(value or "").upper() or "LOCAL_SAMPLE" in str(value or "").upper() for value in values)


def weighted_percentile(samples: list[WeightedRateSample], ratio: float) -> float | None:
    if not samples:
        return None
    ordered = sorted(samples, key=lambda item: item.price)
    total_weight = sum(max(item.weight, 0.01) for item in ordered)
    target = total_weight * ratio
    seen = 0.0
    for item in ordered:
        seen += max(item.weight, 0.01)
        if seen >= target:
            return item.price
    return ordered[-1].price


def confidence_level(
    sample_size: int,
    fallback_level: str,
    coverage_rate: float,
    price_spread: float,
    *,
    effective_sample_size: float | None = None,
    quality_warnings: list[str] | None = None,
) -> str:
    effective = effective_sample_size if effective_sample_size is not None else float(sample_size)
    warnings = quality_warnings or []
    if (
        effective >= 8
        and fallback_level in {"EXACT_NODE_COMMODITY", "CITY_COMMODITY"}
        and coverage_rate >= 85
        and price_spread <= 0.22
        and not any(item in warnings for item in {"ROUTE_NOT_READY", "LOW_EFFECTIVE_SAMPLE_SIZE"})
    ):
        return "HIGH"
    if effective >= 4 and sample_size >= 5 and coverage_rate >= 60 and price_spread <= 0.4:
        return "MEDIUM"
    return "LOW"


def geo_distance_km(origin: TransportNode | None, destination: TransportNode | None) -> float | None:
    if origin is None or destination is None:
        return None
    origin_lng = num(origin.longitude)
    origin_lat = num(origin.latitude)
    dest_lng = num(destination.longitude)
    dest_lat = num(destination.latitude)
    if None in (origin_lng, origin_lat, dest_lng, dest_lat):
        return None
    assert origin_lng is not None and origin_lat is not None and dest_lng is not None and dest_lat is not None
    radius = 6371.0
    lat1 = math.radians(origin_lat)
    lat2 = math.radians(dest_lat)
    delta_lat = math.radians(dest_lat - origin_lat)
    delta_lng = math.radians(dest_lng - origin_lng)
    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def production_allows_demo() -> bool:
    return (settings.APP_ENV or "").strip().lower() in LOCAL_ENVIRONMENTS


class RateSampleEstimator:
    """Selects, weights and explains comparable rate samples."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def rate_samples(self, context: Any, route_distance_km: float | None = None) -> tuple[list[Freight], str, list[dict[str, Any]]]:
        assert context.commodity_standard_id is not None
        fallback_trace: list[dict[str, Any]] = []
        base_conditions = [
            Freight.unit_price.is_not(None),
            Freight.estimated_tonnage.is_not(None),
            Freight.unit_price > 0,
            Freight.estimated_tonnage > 0,
        ]
        if context.freight is not None:
            base_conditions.append(Freight.id != context.freight.id)

        async def rows_for(*conditions: Any) -> list[Freight]:
            rows = (
                await self.db.execute(
                    select(Freight)
                    .where(*base_conditions, *conditions)
                    .order_by(Freight.published_at.desc().nullslast(), Freight.id.desc())
                    .limit(80)
                )
            ).scalars().all()
            if production_allows_demo():
                return list(rows)
            return [row for row in rows if not is_demo_freight(row)]

        context_nodes = await self.nodes_by_id([context.origin_node_id, context.destination_node_id])
        origin_city_code = (
            context.freight.origin_city_code
            if context.freight is not None
            else getattr(context_nodes.get(int(context.origin_node_id or 0)), "city_code", None)
        )
        destination_city_code = (
            context.freight.destination_city_code
            if context.freight is not None
            else getattr(context_nodes.get(int(context.destination_node_id or 0)), "city_code", None)
        )

        exact = await rows_for(
            Freight.origin_node_id == context.origin_node_id,
            Freight.destination_node_id == context.destination_node_id,
            Freight.commodity_standard_id == context.commodity_standard_id,
        )
        fallback_trace.append({"level_code": "EXACT_NODE_COMMODITY", "sample_size": len(exact), "accepted": len(exact) >= 3})
        if len(exact) >= 3:
            return exact, "EXACT_NODE_COMMODITY", fallback_trace

        city_rows = await rows_for(
            Freight.origin_city_code == origin_city_code,
            Freight.destination_city_code == destination_city_code,
            Freight.commodity_standard_id == context.commodity_standard_id,
        )
        fallback_trace.append({"level_code": "CITY_COMMODITY", "sample_size": len(city_rows), "accepted": len(city_rows) >= 5})
        if len(city_rows) >= 5:
            return city_rows, "CITY_COMMODITY", fallback_trace

        flow_rows = await rows_for(
            Freight.origin_city_code == origin_city_code,
            Freight.destination_city_code == destination_city_code,
            Freight.commodity_standard_id.is_not(None),
        )
        fallback_trace.append({"level_code": "FLOW_COMMODITY_TYPE", "sample_size": len(flow_rows), "accepted": len(flow_rows) >= 5})
        if len(flow_rows) >= 5:
            return flow_rows, "FLOW_COMMODITY_TYPE", fallback_trace

        commodity_rows = await rows_for(Freight.commodity_standard_id == context.commodity_standard_id)
        fallback_trace.append({"level_code": "COMMODITY", "sample_size": len(commodity_rows), "accepted": len(commodity_rows) >= 5})
        if len(commodity_rows) >= 5:
            return commodity_rows, "COMMODITY", fallback_trace

        if route_distance_km and route_distance_km > 0:
            distance_candidates = await rows_for(Freight.origin_node_id.is_not(None), Freight.destination_node_id.is_not(None))
            distance_rows = await self.distance_band_rows(distance_candidates, route_distance_km)
            fallback_trace.append({"level_code": "DISTANCE_BAND", "sample_size": len(distance_rows), "accepted": len(distance_rows) >= 5})
            if len(distance_rows) >= 5:
                return distance_rows, "DISTANCE_BAND", fallback_trace

        global_rows = await rows_for(or_(Freight.commodity_standard_id == context.commodity_standard_id, Freight.commodity_standard_id.is_not(None)))
        fallback_trace.append({"level_code": "GLOBAL_PRICE", "sample_size": len(global_rows), "accepted": bool(global_rows)})
        return global_rows, "GLOBAL_PRICE", fallback_trace

    async def distance_band_rows(self, rows: list[Freight], route_distance_km: float) -> list[Freight]:
        node_ids = {int(row.origin_node_id) for row in rows if row.origin_node_id} | {
            int(row.destination_node_id) for row in rows if row.destination_node_id
        }
        if not node_ids:
            return []
        nodes = (await self.db.execute(select(TransportNode).where(TransportNode.id.in_(node_ids)))).scalars().all()
        node_by_id = {int(node.id): node for node in nodes}
        tolerance = max(80.0, route_distance_km * 0.35)
        matched: list[tuple[float, Freight]] = []
        for row in rows:
            approx_distance = geo_distance_km(
                node_by_id.get(int(row.origin_node_id)) if row.origin_node_id else None,
                node_by_id.get(int(row.destination_node_id)) if row.destination_node_id else None,
            )
            if approx_distance is None:
                continue
            delta = abs(approx_distance - route_distance_km)
            if delta <= tolerance:
                matched.append((delta, row))
        matched.sort(key=lambda item: item[0])
        return [row for _, row in matched[:80]]

    async def nodes_by_id(self, node_ids: list[int | None]) -> dict[int, TransportNode]:
        ids = [int(item) for item in node_ids if item]
        if not ids:
            return {}
        nodes = (await self.db.execute(select(TransportNode).where(TransportNode.id.in_(ids)))).scalars().all()
        return {int(node.id): node for node in nodes}

    async def weighted_rate_samples(
        self,
        rows: list[Freight],
        context: Any,
        fallback_level: str,
        route_distance_km: float | None,
        route_status_code: str | None,
    ) -> list[WeightedRateSample]:
        node_ids = [context.origin_node_id, context.destination_node_id]
        for row in rows:
            node_ids.extend([row.origin_node_id, row.destination_node_id])
        nodes = await self.nodes_by_id(node_ids)
        weighted: list[WeightedRateSample] = []
        for row in rows:
            price = num(row.unit_price)
            if price is None or price <= 0 or price > 500:
                continue
            sample_distance = geo_distance_km(
                nodes.get(int(row.origin_node_id)) if row.origin_node_id else None,
                nodes.get(int(row.destination_node_id)) if row.destination_node_id else None,
            )
            factors = self.sample_factor_breakdown(
                row,
                context,
                fallback_level,
                route_distance_km=route_distance_km,
                sample_distance_km=sample_distance,
                route_status_code=route_status_code,
            )
            weight = 1.0
            for value in factors.values():
                weight *= max(0.15, min(value, 1.2))
            weighted.append(WeightedRateSample(row=row, price=price, weight=round(weight, 6), factor_breakdown=factors, distance_km=sample_distance))
        return weighted

    @staticmethod
    def sample_factor_breakdown(
        row: Freight,
        context: Any,
        fallback_level: str,
        *,
        route_distance_km: float | None,
        sample_distance_km: float | None,
        route_status_code: str | None,
    ) -> dict[str, float]:
        fallback_factor = {
            "EXACT_NODE_COMMODITY": 1.0,
            "CITY_COMMODITY": 0.75,
            "FLOW_COMMODITY_TYPE": 0.66,
            "COMMODITY": 0.55,
            "DISTANCE_BAND": 0.45,
            "GLOBAL_PRICE": 0.35,
        }.get(fallback_level, 0.3)
        node_factor = 0.55
        if row.origin_node_id == context.origin_node_id and row.destination_node_id == context.destination_node_id:
            node_factor = 1.0
        elif (
            context.freight is not None
            and row.origin_city_code == context.freight.origin_city_code
            and row.destination_city_code == context.freight.destination_city_code
        ):
            node_factor = 0.82
        commodity_factor = 1.0 if row.commodity_standard_id == context.commodity_standard_id else 0.68
        sample_tonnage = num(row.estimated_tonnage)
        tonnage_factor = 0.65
        if sample_tonnage and context.tonnage:
            tonnage_factor = max(0.45, 1 - min(abs(sample_tonnage - context.tonnage) / max(context.tonnage, 1), 0.55))
        sample_time = row.loading_time_from or row.published_at or row.created_at
        target_time = context.expected_loading_time or datetime.now(UTC).replace(tzinfo=None)
        if sample_time is None:
            time_factor = 0.6
        else:
            days = abs((target_time - sample_time).days)
            time_factor = 1.0 if days <= 14 else 0.86 if days <= 45 else 0.68 if days <= 90 else 0.52
        if route_distance_km and sample_distance_km:
            distance_factor = max(0.45, 1 - min(abs(sample_distance_km - route_distance_km) / max(route_distance_km, 1), 0.55))
        else:
            distance_factor = 0.72 if route_status_code == "READY" else 0.58
        route_factor = 1.0 if route_status_code == "READY" else 0.78 if route_status_code else 0.72
        quality_factor = 1.0
        if row.origin_match_level_code == "RAW" or row.destination_match_level_code == "RAW" or row.commodity_match_level_code == "RAW":
            quality_factor = 0.55
        elif row.origin_match_level_code != "NODE" or row.destination_match_level_code != "NODE":
            quality_factor = 0.78
        return {
            "fallback": fallback_factor,
            "node_match": node_factor,
            "commodity_match": commodity_factor,
            "tonnage_similarity": tonnage_factor,
            "time_freshness": time_factor,
            "distance_similarity": distance_factor,
            "route_computability": route_factor,
            "data_quality": quality_factor,
            "capacity_tension": 0.92,
            "navigation_constraint": 0.94 if route_status_code == "READY" else 0.78,
            "source_layer": 0.88 if is_demo_freight(row) else 1.0,
        }

    @staticmethod
    def exclude_price_outliers(samples: list[WeightedRateSample]) -> tuple[list[WeightedRateSample], int]:
        if len(samples) < 6:
            return samples, 0
        prices = sorted(item.price for item in samples)
        q1 = prices[max(0, int((len(prices) - 1) * 0.25))]
        q3 = prices[min(len(prices) - 1, int((len(prices) - 1) * 0.75))]
        iqr = q3 - q1
        if iqr <= 0:
            return samples, 0
        lower = max(1, q1 - 1.5 * iqr)
        upper = q3 + 1.5 * iqr
        filtered = [item for item in samples if lower <= item.price <= upper]
        if len(filtered) < 3:
            return samples, 0
        return filtered, len(samples) - len(filtered)

    @staticmethod
    def effective_sample_size(samples: list[WeightedRateSample]) -> float:
        weights = [max(item.weight, 0.01) for item in samples]
        if not weights:
            return 0.0
        return (sum(weights) ** 2) / sum(weight * weight for weight in weights)

    @staticmethod
    def aggregate_factor_breakdown(samples: list[WeightedRateSample]) -> list[dict[str, Any]]:
        if not samples:
            return []
        factor_titles = {
            "fallback": "样本层级",
            "node_match": "装卸地匹配",
            "commodity_match": "货品匹配",
            "tonnage_similarity": "吨位接近度",
            "time_freshness": "时间新鲜度",
            "distance_similarity": "距离接近度",
            "route_computability": "航线可计算性",
            "data_quality": "数据质量",
            "capacity_tension": "运力紧张度",
            "navigation_constraint": "通航约束",
            "source_layer": "来源层",
        }
        total_weight = sum(max(item.weight, 0.01) for item in samples)
        result: list[dict[str, Any]] = []
        for code, title in factor_titles.items():
            value = sum(item.factor_breakdown.get(code, 0) * max(item.weight, 0.01) for item in samples) / total_weight
            result.append({"code": code, "title": title, "score": round_number(value, 4), "weight": round_number(value * 100, 1)})
        return result

    @staticmethod
    def comparable_sample_payload(samples: list[WeightedRateSample]) -> list[dict[str, Any]]:
        ordered = sorted(samples, key=lambda item: item.weight, reverse=True)
        return [
            {
                "freight_id": int(item.row.id),
                "freight_no": item.row.freight_no,
                "unit_price": round_number(item.price),
                "tonnage": round_number(num(item.row.estimated_tonnage)),
                "origin_node_id": item.row.origin_node_id,
                "destination_node_id": item.row.destination_node_id,
                "commodity_standard_id": item.row.commodity_standard_id,
                "published_at": item.row.published_at.isoformat() if item.row.published_at else None,
                "loading_time_from": item.row.loading_time_from.isoformat() if item.row.loading_time_from else None,
                "distance_km": round_number(item.distance_km),
                "weight": round_number(item.weight, 4),
                "is_demo": is_demo_freight(item.row),
                "factor_summary": item.factor_breakdown,
            }
            for item in ordered[:12]
        ]

    @staticmethod
    def rate_quality_warnings(
        samples: list[WeightedRateSample],
        *,
        fallback_level: str,
        route_warnings: list[str],
        outlier_count: int,
        effective_sample_size: float,
    ) -> list[str]:
        warnings: list[str] = []
        if fallback_level in {"DISTANCE_BAND", "GLOBAL_PRICE"}:
            warnings.append("FALLBACK_LAYER_LOW")
        if route_warnings:
            warnings.append("ROUTE_NOT_READY")
        if outlier_count:
            warnings.append("PRICE_OUTLIER_EXCLUDED")
        if effective_sample_size < 4:
            warnings.append("LOW_EFFECTIVE_SAMPLE_SIZE")
        if any(item.factor_breakdown.get("data_quality", 1) < 0.8 for item in samples):
            warnings.append("DATA_QUALITY_DISCOUNTED")
        if any(is_demo_freight(item.row) for item in samples):
            warnings.append("LOCAL_DEMO_SAMPLE_INCLUDED")
        return list(dict.fromkeys(warnings))
