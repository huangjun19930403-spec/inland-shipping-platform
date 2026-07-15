from __future__ import annotations

from app.modules.navigation.engine.route_post_processor import RoutePostProcessor
from app.modules.navigation.engine.types import SnapResult


def _line(*points: tuple[float, float]) -> dict:
    return {"type": "LineString", "coordinates": [[lng, lat] for lng, lat in points]}


def _snap(role: str) -> SnapResult:
    return SnapResult(
        role=role,
        snap_type="GRAPH_NODE",
        snap_distance_m=0,
        snap_confidence=100,
        snap_point=(120.0, 31.0),
        quality_code="HIGH",
    )


def _issue_codes(geometry: dict) -> set[str]:
    issues = RoutePostProcessor().validate(geometry, origin_snap=_snap("ORIGIN"), destination_snap=_snap("DESTINATION"))
    return {issue.issue_type_code for issue in issues}


def test_two_point_long_route_is_rejected_as_straight_line_fallback() -> None:
    assert "ROUTE_STRAIGHT_LINE_FALLBACK" in _issue_codes(_line((120.0, 31.0), (120.2, 31.0)))


def test_self_intersection_route_is_rejected() -> None:
    assert "ROUTE_SELF_INTERSECTION_REVIEW" in _issue_codes(
        _line((120.0, 31.0), (120.1, 31.1), (120.0, 31.1), (120.1, 31.0))
    )


def test_foldback_turn_is_rejected() -> None:
    assert "ROUTE_FOLDBACK_REVIEW" in _issue_codes(
        _line((120.0, 31.0), (120.05, 31.0), (120.0001, 31.00001), (120.1, 31.02))
    )


def test_long_single_segment_is_review_warning_not_straight_fallback() -> None:
    codes = _issue_codes(_line((120.0, 31.0), (120.2, 31.0), (120.3, 31.02)))

    assert "ROUTE_LONG_STRAIGHT_SEGMENT_REVIEW" in codes
    assert "ROUTE_STRAIGHT_LINE_FALLBACK" not in codes
