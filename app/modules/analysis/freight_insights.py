"""Problem-oriented freight insight builders."""

from __future__ import annotations

from datetime import date

from app.modules.analysis.schemas import AnalysisActionBlock, AnalysisInsightBlock, ChartPoint, FlowMapItem, HeatMapItem


def _num(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _ratio(part: float, total: float) -> float:
    return round((part / total) * 100, 2) if total else 0.0


def build_freight_insights(
    *,
    totals: dict[str, float],
    raw_quality: dict[str, int],
    trend: list[ChartPoint],
    node_ranking: list[HeatMapItem],
    commodity_structure: list[ChartPoint],
    price_distribution: list[ChartPoint],
    hot_routes: list[FlowMapItem],
    start: date,
    end: date,
) -> list[AnalysisInsightBlock]:
    sample_count = int(totals.get("freight_count", 0) or 0)
    coverage = 100.0 if sample_count else 0.0
    date_query = {"date_from": start.isoformat(), "date_to": end.isoformat()}
    latest = trend[-1] if trend else None
    previous = trend[-2] if len(trend) >= 2 else None
    trend_delta = _num(latest.value if latest else 0) - _num(previous.value if previous else 0)
    top_route = hot_routes[0] if hot_routes else None
    top_node = node_ranking[0] if node_ranking else None
    top_commodity = commodity_structure[0] if commodity_structure else None
    high_price_bucket = price_distribution[-1] if price_distribution else None

    return [
        AnalysisInsightBlock(
            insight_code="FREIGHT_GROWTH_CAPACITY_GAP",
            title="货源增长与运力缺口",
            conclusion=(
                f"最近统计期货源量较上一期增加 {int(trend_delta)} 条，建议优先查看供需适配和可用运力。"
                if trend_delta > 0
                else "当前货源增长不明显，仍需关注重点流向的可用运力和适配质量。"
            ),
            severity_code="WARNING" if trend_delta > 0 else "INFO",
            sample_size=sample_count,
            coverage_rate=coverage,
            confidence_level="MEDIUM" if sample_count else "LOW",
            evidence=[
                {"metric_code": "latest_freight_count", "value": _num(latest.value if latest else 0), "date": latest.date.isoformat() if latest and latest.date else None},
                {"metric_code": "previous_freight_count", "value": _num(previous.value if previous else 0), "date": previous.date.isoformat() if previous and previous.date else None},
                {"metric_code": "trend_delta", "value": trend_delta},
            ],
            not_computable_reasons=[] if trend else ["FREIGHT_TREND_MISSING"],
            recommended_actions=[
                AnalysisActionBlock(action_code="OPEN_SUPPLY_DEMAND_FIT", title="进入供需适配分析", target_route="/freight/supply-demand-fit", query=date_query)
            ],
        ),
        AnalysisInsightBlock(
            insight_code="HOT_ROUTE_CONCENTRATION",
            title="热门流向集中",
            conclusion=(
                f"{top_route.origin_name} 至 {top_route.destination_name} 是当前最热流向，货源 {top_route.freight_count or top_route.value} 条。"
                if top_route
                else "当前统计期没有形成可排序的热门流向。"
            ),
            severity_code="INFO",
            sample_size=int(top_route.freight_count or top_route.value) if top_route else 0,
            coverage_rate=coverage,
            confidence_level="HIGH" if top_route and sample_count >= 20 else "MEDIUM" if top_route else "LOW",
            evidence=[
                {
                    "metric_code": "top_route",
                    "origin_node_id": top_route.origin_id,
                    "destination_node_id": top_route.destination_id,
                    "freight_count": top_route.freight_count,
                    "tonnage": top_route.tonnage,
                    "avg_unit_price": top_route.avg_unit_price,
                }
            ]
            if top_route
            else [],
            not_computable_reasons=[] if top_route else ["HOT_ROUTE_MISSING"],
            recommended_actions=[
                AnalysisActionBlock(
                    action_code="OPEN_ROUTE_FREIGHTS",
                    title="查看该流向机会样本",
                    target_route="/freight/list",
                    query={**date_query, "origin_node_id": top_route.origin_id if top_route else None, "destination_node_id": top_route.destination_id if top_route else None},
                    enabled=bool(top_route),
                    disabled_reason=None if top_route else "缺少可下钻流向",
                )
            ],
        ),
        AnalysisInsightBlock(
            insight_code="QUALITY_RECALC_GAP",
            title="节点与货品质量缺口",
            conclusion=(
                f"仍有 {raw_quality['raw_level_count']} 条货源存在原文级节点、城市或货品缺口，会影响报价、预估和适配结论。"
                if raw_quality["raw_level_count"]
                else "当前货源标准化覆盖较好，未发现原文级节点或货品缺口。"
            ),
            severity_code="WARNING" if raw_quality["raw_level_count"] else "INFO",
            sample_size=raw_quality["raw_level_count"],
            coverage_rate=_ratio(sample_count - raw_quality["raw_level_count"], sample_count),
            confidence_level="HIGH" if sample_count else "LOW",
            evidence=[
                {"metric_code": "raw_level_count", "value": raw_quality["raw_level_count"]},
                {"metric_code": "top_node", "node_id": top_node.node_id if top_node else None, "name": top_node.name if top_node else None},
                {"metric_code": "top_commodity", "name": top_commodity.name if top_commodity else None, "freight_count": top_commodity.value if top_commodity else None},
            ],
            not_computable_reasons=[] if sample_count else ["FREIGHT_SAMPLE_MISSING"],
            recommended_actions=[
                AnalysisActionBlock(action_code="OPEN_QUALITY_RECALC", title="进入质量治理与回算", target_route="/freight/normalization", query=date_query)
            ],
        ),
        AnalysisInsightBlock(
            insight_code="PRICE_ANOMALY_REVIEW",
            title="价格异常与预估复核",
            conclusion=(
                f"价格样本在 {high_price_bucket.name} 桶仍有 {int(high_price_bucket.value)} 条，建议对高价或异常价做运价预估复核。"
                if high_price_bucket
                else "当前统计期缺少价格分布，无法判断价格异常。"
            ),
            severity_code="WARNING" if high_price_bucket and high_price_bucket.value else "INFO",
            sample_size=int(high_price_bucket.value) if high_price_bucket else 0,
            coverage_rate=coverage,
            confidence_level="MEDIUM" if high_price_bucket else "LOW",
            evidence=[
                {
                    "metric_code": "highest_price_bucket",
                    "bucket": high_price_bucket.name,
                    "freight_count": high_price_bucket.value,
                    "avg_unit_price": (high_price_bucket.extra or {}).get("avg_unit_price") if high_price_bucket else None,
                }
            ]
            if high_price_bucket
            else [],
            not_computable_reasons=[] if high_price_bucket else ["PRICE_DISTRIBUTION_MISSING"],
            recommended_actions=[
                AnalysisActionBlock(action_code="OPEN_RATE_ESTIMATOR", title="进入运价预估测算", target_route="/analysis/rate-estimator", query=date_query)
            ],
        ),
        AnalysisInsightBlock(
            insight_code="CANDIDATE_FIT_GAP",
            title="船货适配缺口",
            conclusion=(
                f"建议围绕 {top_route.origin_name} 至 {top_route.destination_name} 做船货适配复核，避免只看货源热度不看可承运运力。"
                if top_route
                else "缺少可用于适配复核的重点流向。"
            ),
            severity_code="WARNING" if top_route else "INFO",
            sample_size=int(top_route.freight_count or top_route.value) if top_route else 0,
            coverage_rate=coverage,
            confidence_level="MEDIUM" if top_route else "LOW",
            evidence=[
                {
                    "metric_code": "candidate_fit_route",
                    "origin_node_id": top_route.origin_id,
                    "destination_node_id": top_route.destination_id,
                    "commodity_name": top_route.commodity_name,
                }
            ]
            if top_route
            else [],
            not_computable_reasons=[] if top_route else ["CANDIDATE_ROUTE_MISSING"],
            recommended_actions=[
                AnalysisActionBlock(
                    action_code="OPEN_CANDIDATE_FIT",
                    title="进入供需适配分析",
                    target_route="/freight/supply-demand-fit",
                    query={**date_query, "origin_node_id": top_route.origin_id if top_route else None, "destination_node_id": top_route.destination_id if top_route else None},
                    enabled=bool(top_route),
                    disabled_reason=None if top_route else "缺少可适配流向",
                )
            ],
        ),
    ]
