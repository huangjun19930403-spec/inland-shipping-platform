"""Map state helpers for production route and flow analysis."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.modules.analysis.schemas import AnalysisActionBlock, AnalysisMapStateBlock

_STATUS_IMPACT = {
    "READY": "真实航线轨迹已生成，可作为地图展示、距离和报价测算依据。",
    "PENDING": "真实航线轨迹尚未生成，地图暂不绘制替代直线，相关距离和价格结论需等待轨迹任务完成。",
    "FAILED": "外部航线服务返回失败，地图和依赖真实轨迹的分析结论不可作为生产依据。",
    "NOT_COMPUTABLE": "缺少节点、坐标、业务类别或服务配置，当前流向无法计算真实航线。",
}

_REASON_FIELD_HINTS = {
    "装货节点不存在": ["origin_node_id"],
    "卸货节点不存在": ["destination_node_id"],
    "装货节点未启用": ["origin_node_status"],
    "卸货节点未启用": ["destination_node_status"],
    "装货节点缺少经纬度": ["origin_longitude", "origin_latitude"],
    "卸货节点缺少经纬度": ["destination_longitude", "destination_latitude"],
    "装货节点未配置装货业务类别": ["origin_business_category"],
    "卸货节点未配置卸货业务类别": ["destination_business_category"],
    "起终点经纬度不完整": ["origin_longitude", "origin_latitude", "destination_longitude", "destination_latitude"],
    "起终点坐标相同": ["origin_longitude", "origin_latitude", "destination_longitude", "destination_latitude"],
    "未配置 AMMS": ["AMMS_BASE_URL", "AMMS_API_KEY"],
    "AMMS 未配置": ["AMMS_BASE_URL", "AMMS_API_KEY"],
}


def public_route_reason(value: str) -> str:
    return value.replace("HiFleet", "AMMS").replace("HIFLEET", "AMMS").replace("\r", " ").replace("\n", " ").strip()


def missing_fields_from_reasons(reasons: list[str]) -> list[str]:
    fields: list[str] = []
    for reason in reasons:
        for marker, marker_fields in _REASON_FIELD_HINTS.items():
            if marker in reason:
                fields.extend(marker_fields)
    return sorted(set(fields))


def default_retry_action(status_code: str, *, target_route: str, query: dict[str, Any] | None = None) -> AnalysisActionBlock | None:
    if status_code == "READY":
        return None
    if status_code == "PENDING":
        return AnalysisActionBlock(
            action_code="PRECOMPUTE_ROUTE_GEOMETRY",
            title="生成真实航线",
            target_route=target_route,
            query=query or {},
            required_fields=["origin_node_id", "destination_node_id"],
        )
    if status_code == "FAILED":
        return AnalysisActionBlock(
            action_code="RETRY_ROUTE_GEOMETRY",
            title="重试航线服务",
            target_route=target_route,
            query={**(query or {}), "force_refresh": True},
            required_fields=["origin_node_id", "destination_node_id"],
        )
    return AnalysisActionBlock(
        action_code="OPEN_ROUTE_DATA_GOVERNANCE",
        title="补齐节点/配置",
        target_route="/address/nodes",
        query=query or {},
        required_fields=["origin_node_id", "destination_node_id"],
    )


def build_map_state(
    status_code: str,
    *,
    provider_code: str = "AMMS",
    cache_status: str | None = None,
    last_updated_at: datetime | None = None,
    reasons: list[str] | None = None,
    missing_fields: list[str] | None = None,
    retry_action: AnalysisActionBlock | None = None,
    business_impact: str | None = None,
) -> AnalysisMapStateBlock:
    status = str(status_code or "PENDING").upper()
    public_reasons = [public_route_reason(item) for item in reasons or [] if item]
    fields = sorted(set(missing_fields or missing_fields_from_reasons(public_reasons)))
    return AnalysisMapStateBlock(
        status_code=status,
        provider_code=provider_code,
        provider_name=provider_code,
        cache_status=cache_status,
        last_updated_at=last_updated_at,
        error_reason=public_reasons[0] if status in {"FAILED", "NOT_COMPUTABLE"} and public_reasons else None,
        missing_fields=fields,
        not_computable_reasons=public_reasons,
        retry_action=retry_action,
        business_impact=business_impact or _STATUS_IMPACT.get(status, _STATUS_IMPACT["PENDING"]),
    )


def build_map_state_payload(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return build_map_state(*args, **kwargs).model_dump(mode="json")
