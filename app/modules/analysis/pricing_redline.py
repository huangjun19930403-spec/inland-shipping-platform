"""Redline quote calculator based on the intelligent inland quote prototype."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable


DEFAULT_REDLINE_SCENE: dict[str, Any] = {
    "id": "standard",
    "name": "标准测算",
    "note": "用于日常正常报价，兼顾竞争力和安全边界。",
    "targetMargin": 10,
    "vatRate": 9,
    "directInputRate": 1,
    "directBearTaxPoint": True,
    "directRefundEnabled": True,
    "directRefundShare": 80,
    "entrustedInputRate": 9,
    "entrustedServicePoint": 6.5,
    "entrustedRefundEnabled": False,
    "entrustedRefundShare": 0,
    "localShare": 50,
    "includeSurcharge": True,
    "surchargeRate": 12,
    "otherCost": 0,
}


@dataclass(frozen=True)
class RedlineDecision:
    scene: dict[str, Any]
    redline_schemes: list[dict[str, Any]]
    best_scheme: dict[str, Any]
    decision_code: str
    conclusion: str
    recommended_quote: float
    cost_floor: float
    gross_profit: float
    gross_margin_rate: float


def redline_scene(raw_scene: dict | None) -> dict[str, Any]:
    scene = {**DEFAULT_REDLINE_SCENE}
    if isinstance(raw_scene, dict):
        scene.update(raw_scene)
    return scene


def build_redline_decision(
    *,
    current_quote: float,
    owner_quote: float,
    quote_direction: str,
    target_margin: float,
    raw_scene: dict | None,
) -> RedlineDecision:
    scene = redline_scene(raw_scene)
    scheme_specs: list[tuple[str, str, str, Callable[[float, float, dict[str, Any]], dict[str, float]]]] = [
        ("DIRECT", "直接承运", "公司直接组织承运，适合成本控制要求高的业务。", _direct_tax),
        ("ENTRUSTED", "委托承运", "通过承运服务方组织，适合结算与组织链路更完整的业务。", _entrusted_tax),
    ]
    redline_schemes: list[dict[str, Any]] = []
    for scheme_code, title, subtitle, fn in scheme_specs:
        if quote_direction == "SHIPOWNER_FIRST":
            redline = _min_shipper_price(owner_quote, 0, scene, fn)
            target_line = _min_shipper_price(owner_quote, target_margin, scene, fn)
            current = fn(current_quote, owner_quote, scene)
            status_code, status_label, conclusion_text = _status_by_shipowner(
                current_quote, redline, target_line, current
            )
            planned_quote = current_quote
        else:
            redline = _max_shipowner_price(current_quote, 0, scene, fn)
            target_line = _max_shipowner_price(current_quote, target_margin, scene, fn)
            current = fn(current_quote, owner_quote, scene)
            status_code, status_label, conclusion_text = _status_by_shipper(
                owner_quote, redline, target_line, current
            )
            planned_quote = owner_quote
        redline_schemes.append(
            {
                "scheme_code": scheme_code,
                "scheme_title": title,
                "scheme_subtitle": subtitle,
                "status_code": status_code,
                "status_label": status_label,
                "conclusion": conclusion_text,
                "redline_quote": _round(redline, 4),
                "target_margin_quote": _round(target_line, 4),
                "planned_quote": _round(planned_quote, 4),
                "target_margin_rate": _round(target_margin, 4),
                "profit": _round(current["profit"], 4),
                "margin_rate": _round(current["margin"], 4),
                "tax_breakdown": _round_tax_breakdown(current),
            }
        )

    best_scheme = sorted(redline_schemes, key=_scheme_rank, reverse=True)[0]
    decision_code, conclusion = _decision_text(best_scheme)
    if quote_direction == "SHIPOWNER_FIRST":
        recommended_quote = min(float(item["target_margin_quote"] or 0) for item in redline_schemes)
        cost_floor = min(float(item["redline_quote"] or 0) for item in redline_schemes)
    else:
        recommended_quote = max(float(item["target_margin_quote"] or 0) for item in redline_schemes)
        cost_floor = max(float(item["redline_quote"] or 0) for item in redline_schemes)
    return RedlineDecision(
        scene=scene,
        redline_schemes=redline_schemes,
        best_scheme=best_scheme,
        decision_code=decision_code,
        conclusion=conclusion,
        recommended_quote=recommended_quote,
        cost_floor=cost_floor,
        gross_profit=float(best_scheme.get("profit") or 0),
        gross_margin_rate=float(best_scheme.get("margin_rate") or 0),
    )


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None and math.isfinite(value) else None


def _rate(value: Any, default: float = 0.0) -> float:
    number = _num(value)
    if number is None:
        return default
    if number > 1:
        return number / 100
    return max(number, 0.0)


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "是", "启用"}


def _scene_get(scene: dict[str, Any], camel_key: str, snake_key: str | None = None, default: Any = None) -> Any:
    if camel_key in scene:
        return scene[camel_key]
    if snake_key and snake_key in scene:
        return scene[snake_key]
    return default


def _direct_tax(P: float, S: float, scene: dict[str, Any]) -> dict[str, float]:
    v = _rate(_scene_get(scene, "vatRate", "vat_rate", 9))
    i = _rate(_scene_get(scene, "directInputRate", "direct_input_rate", _scene_get(scene, "schemeAInputRate", "scheme_a_input_rate", 1)))
    local_share = _rate(_scene_get(scene, "localShare", "local_share", 50))
    refund_share = _rate(_scene_get(scene, "directRefundShare", "direct_refund_share", _scene_get(scene, "refundShareA", "refund_share_a", 80)))
    surcharge_rate = _surcharge_rate(scene)
    other_cost = _num(_scene_get(scene, "otherCost", "other_cost", 0)) or 0.0
    output_vat = P * v / (1 + v) if v > -1 else 0.0
    input_vat = S * i
    vat_payable = max(output_vat - input_vat, 0.0)
    tax_point_cost = S * i if _bool(
        _scene_get(scene, "directBearTaxPoint", "direct_bear_tax_point", _scene_get(scene, "schemeABearTaxPoint", "scheme_a_bear_tax_point", True)),
        True,
    ) else 0.0
    refund = vat_payable * local_share * refund_share if _bool(
        _scene_get(scene, "directRefundEnabled", "direct_refund_enabled", _scene_get(scene, "schemeARefundEnabled", "scheme_a_refund_enabled", True)),
        True,
    ) else 0.0
    return _tax_result(P, S, output_vat, input_vat, vat_payable, tax_point_cost, refund, surcharge_rate, other_cost)


def _entrusted_tax(P: float, S: float, scene: dict[str, Any]) -> dict[str, float]:
    v = _rate(_scene_get(scene, "vatRate", "vat_rate", 9))
    input_rate = _rate(_scene_get(scene, "entrustedInputRate", "entrusted_input_rate", _scene_get(scene, "schemeBInputRate", "scheme_b_input_rate", 9)))
    tax_point = _rate(_scene_get(scene, "entrustedServicePoint", "entrusted_service_point", _scene_get(scene, "schemeBTaxPoint", "scheme_b_tax_point", 6.5)))
    local_share = _rate(_scene_get(scene, "localShare", "local_share", 50))
    refund_share = _rate(_scene_get(scene, "entrustedRefundShare", "entrusted_refund_share", _scene_get(scene, "refundShareB", "refund_share_b", 0)))
    surcharge_rate = _surcharge_rate(scene)
    other_cost = _num(_scene_get(scene, "otherCost", "other_cost", 0)) or 0.0
    output_vat = P * v / (1 + v) if v > -1 else 0.0
    input_vat = S * input_rate / (1 + input_rate) if input_rate > -1 else 0.0
    vat_payable = max(output_vat - input_vat, 0.0)
    tax_point_cost = S * tax_point
    refund = vat_payable * local_share * refund_share if _bool(
        _scene_get(scene, "entrustedRefundEnabled", "entrusted_refund_enabled", _scene_get(scene, "schemeBRefundEnabled", "scheme_b_refund_enabled", False)),
        False,
    ) else 0.0
    return _tax_result(P, S, output_vat, input_vat, vat_payable, tax_point_cost, refund, surcharge_rate, other_cost)


def _tax_result(
    P: float,
    S: float,
    output_vat: float,
    input_vat: float,
    vat_payable: float,
    tax_point_cost: float,
    refund: float,
    surcharge_rate: float,
    other_cost: float,
) -> dict[str, float]:
    surcharge = vat_payable * surcharge_rate
    total_tax_cost = vat_payable + tax_point_cost + surcharge - refund
    profit = P - S - total_tax_cost - other_cost
    return {
        "output_vat": output_vat,
        "input_vat": input_vat,
        "vat_payable": vat_payable,
        "tax_point_cost": tax_point_cost,
        "refund": refund,
        "surcharge": surcharge,
        "total_tax_cost": total_tax_cost,
        "other_cost": other_cost,
        "profit": profit,
        "margin": profit / P if P > 0 else 0.0,
    }


def _surcharge_rate(scene: dict[str, Any]) -> float:
    if not _bool(_scene_get(scene, "includeSurcharge", "include_surcharge", True), True):
        return 0.0
    return _rate(_scene_get(scene, "surchargeRate", "surcharge_rate", 12))


def _max_shipowner_price(P: float, target_margin: float, scene: dict[str, Any], fn: Callable[[float, float, dict[str, Any]], dict[str, float]]) -> float:
    low = 0.0
    high = max(P * 2, 1.0)
    for _ in range(90):
        mid = (low + high) / 2
        if fn(P, mid, scene)["margin"] >= target_margin:
            low = mid
        else:
            high = mid
    return low


def _min_shipper_price(S: float, target_margin: float, scene: dict[str, Any], fn: Callable[[float, float, dict[str, Any]], dict[str, float]]) -> float:
    low = 0.0
    high = max(S * 3 + 10, 10.0)
    while fn(high, S, scene)["margin"] < target_margin and high < 1_000_000:
        high *= 2
    for _ in range(90):
        mid = (low + high) / 2
        if fn(mid, S, scene)["margin"] >= target_margin:
            high = mid
        else:
            low = mid
    return high


def _status_by_shipper(plan_s: float, redline: float, target_line: float, current: dict[str, float]) -> tuple[str, str, str]:
    if plan_s > redline + 1e-8:
        return "LOSS", "亏损", f"计划给船户 {_round(plan_s, 4)} 元/吨，高于保本红线 {_round(redline, 4)} 元/吨，当前亏损 {_round(abs(current['profit']), 4)} 元/吨。"
    if plan_s > target_line + 1e-8:
        return "UNDER_TARGET", "赚钱但未达标", f"计划给船户 {_round(plan_s, 4)} 元/吨，未亏损但高于目标毛利上限 {_round(target_line, 4)} 元/吨，当前毛利率 {_round(current['margin'] * 100, 2)}%。"
    return "MEET_TARGET", "已达标", f"计划给船户 {_round(plan_s, 4)} 元/吨，低于目标毛利上限 {_round(target_line, 4)} 元/吨，当前毛利率 {_round(current['margin'] * 100, 2)}%。"


def _status_by_shipowner(plan_p: float, redline: float, target_line: float, current: dict[str, float]) -> tuple[str, str, str]:
    if plan_p + 1e-8 < redline:
        return "LOSS", "亏损", f"计划报货主 {_round(plan_p, 4)} 元/吨，低于保本红线 {_round(redline, 4)} 元/吨，当前亏损 {_round(abs(current['profit']), 4)} 元/吨。"
    if plan_p + 1e-8 < target_line:
        return "UNDER_TARGET", "赚钱但未达标", f"计划报货主 {_round(plan_p, 4)} 元/吨，未亏损但低于目标毛利报价 {_round(target_line, 4)} 元/吨，当前毛利率 {_round(current['margin'] * 100, 2)}%。"
    return "MEET_TARGET", "已达标", f"计划报货主 {_round(plan_p, 4)} 元/吨，达到目标毛利，当前毛利率 {_round(current['margin'] * 100, 2)}%。"


def _scheme_rank(item: dict[str, Any]) -> tuple[int, float]:
    status_rank = {"MEET_TARGET": 3, "UNDER_TARGET": 2, "LOSS": 1}.get(str(item["status_code"]), 0)
    return status_rank, float(item.get("profit") or -1_000_000)


def _decision_text(best_scheme: dict[str, Any]) -> tuple[str, str]:
    if best_scheme["status_code"] == "MEET_TARGET":
        return "ACCEPT", f"{best_scheme['scheme_title']}已达到目标毛利，可进入报价确认。"
    if best_scheme["status_code"] == "UNDER_TARGET":
        return "NEGOTIATE", f"{best_scheme['scheme_title']}不亏损但未达到目标毛利，建议按目标线议价。"
    return "REJECT", "两种税务方案均低于保本要求，建议拒绝或重新议价。"


def _round_tax_breakdown(values: dict[str, float]) -> dict[str, float | None]:
    return {key: _round(value, 4) for key, value in values.items()}
