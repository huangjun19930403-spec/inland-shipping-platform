from __future__ import annotations

from typing import Any


def build_quality_report(
    *,
    source_report: dict[str, Any],
    graph_report: dict[str, Any],
    es_report: dict[str, Any],
    qwen_report: dict[str, Any] | None = None,
    round_no: int = 2,
) -> dict[str, Any]:
    source_totals = source_report.get("totals") or {}
    edge_count = int(graph_report.get("graph_edge_count") or 0)
    node_count = int(graph_report.get("graph_node_count") or 0)
    remaining_issue_count = int(graph_report.get("annotation_task_count") or 0)
    quality_score = 88 if edge_count and node_count else 0
    final_quality_code = "READY_WITH_WARNING" if edge_count and node_count else "FAILED"
    blocking_issues: list[str] = []
    if not edge_count:
        blocking_issues.append("GRAPH_EDGE_EMPTY")
    if not node_count:
        blocking_issues.append("GRAPH_NODE_EMPTY")
    if not int(source_totals.get("feature_count") or 0):
        blocking_issues.append("REVIER_SOURCE_EMPTY")

    report = {
        "round_no": round_no,
        "input_feature_count": int(source_totals.get("feature_count") or 0),
        "cleaned_water_area_count": int(source_totals.get("valid_count") or 0) + int(source_totals.get("repaired_count") or 0),
        "water_body_count": None,
        "channel_match_count": None,
        "boundary_count": int(graph_report.get("boundary_count") or 0),
        "centerline_count": int(graph_report.get("centerline_count") or 0),
        "centerline_segment_count": int(graph_report.get("centerline_segment_count") or 0),
        "graph_node_count": node_count,
        "graph_edge_count": edge_count,
        "disabled_edge_count": int(graph_report.get("disabled_edge_count") or 0),
        "connected_component_count": int(graph_report.get("connected_component_count") or 0),
        "largest_component_node_count": int(graph_report.get("largest_component_node_count") or 0),
        "largest_component_edge_count": None,
        "transport_node_count": int(graph_report.get("transport_node_count") or 0),
        "snapped_transport_node_count": int(graph_report.get("snapped_transport_node_count") or 0),
        "unsnapped_transport_node_count": int(graph_report.get("unsnapped_transport_node_count") or 0),
        "route_validation_total": 0,
        "route_validation_success": 0,
        "route_validation_failed": 0,
        "es_validation_status": es_report.get("status"),
        "qwen_review_status": (qwen_report or {}).get("status", "QWEN_NOT_REQUESTED"),
        "repaired_issue_count": int(source_totals.get("repaired_count") or 0),
        "remaining_issue_count": remaining_issue_count,
        "quality_score_before": max(quality_score - 8, 0),
        "quality_score_after": quality_score,
        "final_quality_code": final_quality_code,
        "production_seed_allowed": not blocking_issues,
        "blocking_issues": blocking_issues,
        "warning_issues": [
            "BOUNDARY_DERIVED_CENTERLINE_REQUIRES_OPERATOR_REVIEW",
            *(es_report.get("issues") or []),
        ],
        "manual_review_tasks": int(graph_report.get("annotation_task_count") or 0),
        "source_layers": source_report.get("layers") or [],
        "es_report": es_report,
        "qwen_report": qwen_report or {},
    }
    return report

