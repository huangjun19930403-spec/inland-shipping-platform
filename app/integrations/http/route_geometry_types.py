"""路线几何查询/结果对象。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class RouteGeometryQuery:
    origin_lon: float
    origin_lat: float
    dest_lon: float
    dest_lat: float
    transport_mode: str
    segment_type: str


@dataclass(slots=True)
class RouteGeometryResult:
    geometry: dict[str, Any]
    source: str
    provider: str
    provider_trace_id: str | None
    status: str
    distance_km: float | None = None
    estimated_duration_hour: float | None = None
    raw_summary: dict[str, Any] | None = None
