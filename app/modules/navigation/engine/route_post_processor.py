from __future__ import annotations

import math

from shapely.geometry import LineString, Point, shape

from app.modules.navigation.engine.geo import line_length_km, point_distance_m
from app.modules.navigation.engine.types import RouteIssue, SnapResult


class RoutePostProcessor:
    STRAIGHT_FALLBACK_MIN_KM = 2.0
    LONG_SEGMENT_REVIEW_KM = 15.0
    FOLDBACK_ANGLE_DEGREE = 8.0
    FOLDBACK_MIN_LEG_M = 100.0

    def validate(
        self,
        geometry_json: dict,
        *,
        origin_snap: SnapResult,
        destination_snap: SnapResult,
    ) -> list[RouteIssue]:
        geometry = shape(geometry_json)
        if not isinstance(geometry, LineString) or geometry.is_empty:
            return []
        issues: list[RouteIssue] = []
        coords = [(float(lng), float(lat)) for lng, lat, *_ in geometry.coords]
        issues.extend(self._structural_issues(geometry, coords))
        seen_short_segment = False
        for start, end in zip(coords[:-1], coords[1:]):
            distance_m = point_distance_m(Point(start), Point(end))
            if distance_m < 5:
                seen_short_segment = True
                issues.append(
                    RouteIssue(
                        "ROUTE_TOO_SHORT_SEGMENT",
                        "WARNING",
                        "Route contains a segment shorter than 5m",
                        geometry_json={"type": "Point", "coordinates": [end[0], end[1]]},
                    )
                )
                break
        if not seen_short_segment:
            issues.extend(self._sharp_turn_issues(coords))
        for snap in (origin_snap, destination_snap):
            if snap.snap_distance_m > 500:
                issues.append(
                    RouteIssue(
                        f"{snap.role}_ACCESS_LONG_REVIEW",
                        "WARNING",
                        f"{snap.role.title()} access distance to graph is {snap.snap_distance_m:.1f}m",
                        geometry_json={"type": "Point", "coordinates": [snap.snap_point[0], snap.snap_point[1]]},
                    )
                )
        return issues

    def _structural_issues(self, geometry: LineString, coords: list[tuple[float, float]]) -> list[RouteIssue]:
        issues: list[RouteIssue] = []
        total_length_km = line_length_km(geometry)
        if len(coords) <= 2 and total_length_km >= self.STRAIGHT_FALLBACK_MIN_KM:
            issues.append(
                RouteIssue(
                    "ROUTE_STRAIGHT_LINE_FALLBACK",
                    "ERROR",
                    "Route only contains origin and destination points; this is a straight-line fallback, not a navigable waterway path",
                    geometry_json={"type": "LineString", "coordinates": [[lng, lat] for lng, lat in coords]},
                )
            )
        if not geometry.is_simple:
            issues.append(
                RouteIssue(
                    "ROUTE_SELF_INTERSECTION_REVIEW",
                    "ERROR",
                    "Route geometry intersects itself and needs seed/graph repair",
                    geometry_json={"type": "LineString", "coordinates": [[lng, lat] for lng, lat in coords]},
                )
            )
        long_segment = self._longest_segment(coords)
        if long_segment and long_segment[0] >= self.LONG_SEGMENT_REVIEW_KM:
            distance_km, start, end = long_segment
            issues.append(
                RouteIssue(
                    "ROUTE_LONG_STRAIGHT_SEGMENT_REVIEW",
                    "WARNING",
                    f"Route contains a single segment of {distance_km:.1f}km; verify it does not cross land or missing boundary geometry",
                    geometry_json={"type": "LineString", "coordinates": [[start[0], start[1]], [end[0], end[1]]]},
                )
            )
        return issues

    def _sharp_turn_issues(self, coords: list[tuple[float, float]]) -> list[RouteIssue]:
        issues: list[RouteIssue] = []
        for prev_point, point, next_point in zip(coords[:-2], coords[1:-1], coords[2:]):
            angle = _turn_angle_degree(prev_point, point, next_point)
            if angle is not None and angle <= self.FOLDBACK_ANGLE_DEGREE:
                prev_len = point_distance_m(Point(prev_point), Point(point))
                next_len = point_distance_m(Point(point), Point(next_point))
                if min(prev_len, next_len) >= self.FOLDBACK_MIN_LEG_M:
                    issues.append(
                        RouteIssue(
                            "ROUTE_FOLDBACK_REVIEW",
                            "ERROR",
                            f"Route contains a foldback turn of {angle:.1f} degrees",
                            geometry_json={"type": "Point", "coordinates": [point[0], point[1]]},
                        )
                    )
                    break
            if angle is not None and angle < 25:
                issues.append(
                    RouteIssue(
                        "ROUTE_SHARP_TURN_REVIEW",
                        "WARNING",
                        f"Route contains a sharp turn of {angle:.1f} degrees",
                        geometry_json={"type": "Point", "coordinates": [point[0], point[1]]},
                    )
                )
                break
        return issues

    def _longest_segment(
        self,
        coords: list[tuple[float, float]],
    ) -> tuple[float, tuple[float, float], tuple[float, float]] | None:
        longest: tuple[float, tuple[float, float], tuple[float, float]] | None = None
        for start, end in zip(coords[:-1], coords[1:]):
            distance_km = point_distance_m(Point(start), Point(end)) / 1000.0
            if longest is None or distance_km > longest[0]:
                longest = (distance_km, start, end)
        return longest


def _turn_angle_degree(
    prev_point: tuple[float, float],
    point: tuple[float, float],
    next_point: tuple[float, float],
) -> float | None:
    v1 = (prev_point[0] - point[0], prev_point[1] - point[1])
    v2 = (next_point[0] - point[0], next_point[1] - point[1])
    norm1 = math.hypot(v1[0], v1[1])
    norm2 = math.hypot(v2[0], v2[1])
    if norm1 <= 0 or norm2 <= 0:
        return None
    cosine = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (norm1 * norm2)))
    return math.degrees(math.acos(cosine))
