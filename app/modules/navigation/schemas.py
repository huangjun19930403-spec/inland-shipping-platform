from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class NavigationEndpointRequest(BaseModel):
    endpoint_type_code: str = Field(default="LNG_LAT", max_length=64)
    longitude: float | None = None
    latitude: float | None = None
    name: str | None = Field(default=None, max_length=128)
    ref_id: int | None = None
    transport_node_id: int | None = None
    constraint_point_id: int | None = None


class VesselProfileRequest(BaseModel):
    length_m: float | None = Field(default=None, gt=0)
    beam_m: float | None = Field(default=None, gt=0)
    draft_m: float | None = Field(default=None, gt=0)
    deadweight_ton: float | None = Field(default=None, gt=0)
    air_draft_m: float | None = Field(default=None, gt=0)
    loaded_status: str | None = Field(default=None, max_length=64)


class NavigationRouteGenerateRequest(BaseModel):
    origin: NavigationEndpointRequest
    destination: NavigationEndpointRequest
    vessel_profile: VesselProfileRequest | None = None
    vessel_profile_json: dict[str, Any] | None = None
    routing_preference_code: str = Field(default="RECOMMENDED", max_length=64)
    graph_version_id: int | None = None


class NavigationSnapResponse(BaseModel):
    role: str
    snap_type: str
    snap_distance_m: float
    snap_confidence: int
    snap_point: list[float]
    graph_node_id: int | None = None
    graph_edge_id: int | None = None
    quality_code: str


class NavigationRouteIssueResponse(BaseModel):
    issue_type_code: str
    severity_code: str
    message: str
    suggestion: str | None = None
    related_edge_id: int | None = None
    related_node_id: int | None = None


class NavigationRouteGenerateResponse(BaseModel):
    request_id: int
    result_id: int
    graph_version_id: int | None
    status_code: str
    quality_code: str
    quality_score: int | None
    geometry_json: dict[str, Any] | None = None
    distance_km: float | None = None
    estimated_duration_hour: float | None = None
    edge_ids: list[int] = Field(default_factory=list)
    channel_ids: list[int] = Field(default_factory=list)
    passed_node_ids: list[int] = Field(default_factory=list)
    passed_lock_count: int = 0
    passed_bridge_count: int = 0
    origin_snap: NavigationSnapResponse | None = None
    destination_snap: NavigationSnapResponse | None = None
    issues: list[NavigationRouteIssueResponse] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
