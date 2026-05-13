"""Action evaluator for freight shipping opportunities."""

from __future__ import annotations

from app.models.freight import Freight
from app.modules.freight.schemas import ShippingOpportunityActionResponse


class ShippingOpportunityActionEvaluator:
    """Builds executable opportunity actions with explicit blocked reasons."""

    def evaluate(
        self,
        row: Freight,
        *,
        route_status: str,
        capacity_status: str,
        pricing_status: str,
        missing_reasons: list[str],
        issue_count: int,
    ) -> list[ShippingOpportunityActionResponse]:
        actions = [
            ShippingOpportunityActionResponse(
                action_code="OPEN_FREIGHT_DETAIL",
                title="查看货源详情",
                target_route=f"/freight/detail/{row.id}",
                query={"freight_id": row.id},
            )
        ]
        if self._needs_cleaning(row, missing_reasons, issue_count):
            actions.append(self._cleaning_action(row, missing_reasons))
        actions.extend(
            [
                self._candidate_action(row, capacity_status),
                self._quote_action(row, pricing_status),
                self._rate_estimate_action(row),
            ]
        )
        if route_status == "PENDING_ROUTE_MODEL":
            actions.append(
                ShippingOpportunityActionResponse(
                    action_code="OPEN_ROUTE_PLANNING",
                    title="补齐航线模型",
                    target_route="/route/list",
                    query={
                        "origin_region_id": row.origin_region_id_cache,
                        "destination_region_id": row.destination_region_id_cache,
                    },
                    required_fields=["origin_region_id", "destination_region_id"],
                )
            )
        return actions

    @staticmethod
    def _needs_cleaning(row: Freight, missing_reasons: list[str], issue_count: int) -> bool:
        return bool(
            issue_count
            or missing_reasons
            or row.origin_match_level_code == "RAW"
            or row.destination_match_level_code == "RAW"
            or row.commodity_match_level_code == "RAW"
        )

    @staticmethod
    def _cleaning_action(row: Freight, missing_reasons: list[str]) -> ShippingOpportunityActionResponse:
        return ShippingOpportunityActionResponse(
            action_code="OPEN_FREIGHT_CLEANING",
            title="进入货源清洗",
            target_route="/freight/normalization",
            query={
                "freight_id": row.id,
                "keyword": row.freight_no,
                "status_code": "PENDING",
                "reason_codes": missing_reasons,
            },
            required_fields=["freight_id"],
        )

    @staticmethod
    def _candidate_action(row: Freight, capacity_status: str) -> ShippingOpportunityActionResponse:
        enabled = capacity_status != "NOT_COMPUTABLE"
        return ShippingOpportunityActionResponse(
            action_code="OPEN_CANDIDATE_VESSELS",
            title="船货适配分析",
            target_route="/vessels/candidate-analysis",
            query={"context_type_code": "FREIGHT_SAMPLE", "freight_id": row.id},
            enabled=enabled,
            required_fields=["freight_id", "origin_node_id", "destination_node_id", "commodity_standard_id"],
            disabled_reason=None if enabled else "缺少节点或标准货品，无法计算适配船舶",
        )

    @staticmethod
    def _quote_action(row: Freight, pricing_status: str) -> ShippingOpportunityActionResponse:
        enabled = pricing_status != "NOT_COMPUTABLE"
        return ShippingOpportunityActionResponse(
            action_code="OPEN_QUOTE_SIMULATOR",
            title="智能报价测算",
            target_route="/analysis/quote-simulator",
            query={
                "freight_id": row.id,
                "origin_node_id": row.origin_node_id,
                "destination_node_id": row.destination_node_id,
                "commodity_standard_id": row.commodity_standard_id,
                "tonnage": row.estimated_tonnage or row.max_tonnage or row.min_tonnage,
                "current_quote": row.unit_price,
            },
            enabled=enabled,
            required_fields=["origin_node_id", "destination_node_id", "commodity_standard_id"],
            disabled_reason=None if enabled else "缺少起终点或标准货品，无法报价",
        )

    @staticmethod
    def _rate_estimate_action(row: Freight) -> ShippingOpportunityActionResponse:
        enabled = bool(row.origin_node_id and row.destination_node_id and row.commodity_standard_id and (row.estimated_tonnage or row.max_tonnage or row.min_tonnage))
        return ShippingOpportunityActionResponse(
            action_code="OPEN_RATE_ESTIMATOR",
            title="运价预估测算",
            target_route="/analysis/rate-estimator",
            query={
                "freight_id": row.id,
                "origin_node_id": row.origin_node_id,
                "destination_node_id": row.destination_node_id,
                "commodity_standard_id": row.commodity_standard_id,
                "tonnage": row.estimated_tonnage or row.max_tonnage or row.min_tonnage,
                "expected_loading_time": row.loading_time_from,
            },
            enabled=enabled,
            required_fields=["origin_node_id", "destination_node_id", "commodity_standard_id", "tonnage"],
            disabled_reason=None if enabled else "缺少起终点、标准货品或吨位，无法预估运价",
        )
