from __future__ import annotations

from collections.abc import Iterable

from shapely.geometry import LineString, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from app.modules.navigation.engine.types import RouteIssue


class PathValidator:
    def validate_geometry(self, geometry_json: dict) -> list[RouteIssue]:
        issues: list[RouteIssue] = []
        geometry = shape(geometry_json)
        if not isinstance(geometry, LineString) or geometry.is_empty:
            return [RouteIssue("PATH_ASSEMBLY_FAILED", "ERROR", "Route geometry is empty or not a LineString")]
        if len(geometry.coords) < 2:
            issues.append(RouteIssue("PATH_ASSEMBLY_FAILED", "ERROR", "Route geometry has fewer than two points"))
        if not geometry.is_valid:
            issues.append(RouteIssue("PATH_GEOMETRY_INVALID", "WARNING", "Route geometry is invalid"))
        return issues

    def validate_spatial_context(
        self,
        geometry_json: dict,
        *,
        water_geometries: Iterable[BaseGeometry],
        boundary_geometries: Iterable[BaseGeometry],
    ) -> list[RouteIssue]:
        geometry = shape(geometry_json)
        if not isinstance(geometry, LineString) or geometry.is_empty or geometry.length <= 0:
            return [RouteIssue("PATH_ASSEMBLY_FAILED", "ERROR", "Route geometry is empty or not a LineString")]

        issues: list[RouteIssue] = []
        water_union = _safe_union(water_geometries)
        boundary_union = _safe_union(boundary_geometries)
        water_ratio: float | None = None

        if water_union is None:
            issues.append(
                RouteIssue(
                    "UNKNOWN_WATER_AREA_CONTEXT",
                    "WARNING",
                    "Route water-area coverage cannot be checked because no matched production water body was found",
                    suggestion="Confirm water-body matches before treating this route as production-ready.",
                )
            )
        else:
            water_ratio = _line_coverage_ratio(geometry, water_union)
            if water_ratio < 0.70:
                issues.append(
                    RouteIssue(
                        "PATH_OUT_OF_WATER",
                        "ERROR",
                        f"Route water-area coverage is too low: {water_ratio:.1%}",
                        suggestion="Fix channel water-body matches or centerline geometry before rebuilding the graph.",
                    )
                )
            elif water_ratio < 0.95:
                issues.append(
                    RouteIssue(
                        "PATH_WATER_COVERAGE_WARNING",
                        "WARNING",
                        f"Route water-area coverage is {water_ratio:.1%}",
                        suggestion="Review centerline and water-body boundary alignment.",
                    )
                )

        if boundary_union is None:
            issues.append(
                RouteIssue(
                    "UNKNOWN_CHANNEL_BOUNDARY_CONTEXT",
                    "WARNING",
                    "Route boundary coverage cannot be checked because no current channel boundary was found",
                    suggestion="Publish a channel boundary before production route verification.",
                )
            )
        else:
            boundary_ratio = _line_coverage_ratio(geometry, boundary_union)
            if boundary_ratio < 0.70:
                if water_ratio is not None and water_ratio >= 0.70:
                    issues.append(
                        RouteIssue(
                            "PATH_CHANNEL_BOUNDARY_WARNING",
                            "WARNING",
                            f"Route channel-boundary coverage is {boundary_ratio:.1%}; water coverage is {water_ratio:.1%}.",
                            suggestion="Review the published boundary and centerline alignment.",
                        )
                    )
                else:
                    issues.append(
                        RouteIssue(
                            "PATH_OUT_OF_CHANNEL_BOUNDARY",
                            "ERROR",
                            f"Route channel-boundary coverage is too low: {boundary_ratio:.1%}",
                            suggestion="Fix and publish the channel boundary, then rebuild the graph.",
                        )
                    )
            elif boundary_ratio < 0.90:
                issues.append(
                    RouteIssue(
                        "PATH_CHANNEL_BOUNDARY_WARNING",
                        "WARNING",
                        f"Route channel-boundary coverage is {boundary_ratio:.1%}",
                        suggestion="Review the published boundary and centerline alignment.",
                    )
                )

        return issues


def _safe_union(geometries: Iterable[BaseGeometry]) -> BaseGeometry | None:
    cleaned = [geometry for geometry in geometries if geometry and not geometry.is_empty]
    if not cleaned:
        return None
    if len(cleaned) == 1:
        return cleaned[0]
    return unary_union(cleaned)


def _line_coverage_ratio(line: LineString, coverage_geometry: BaseGeometry) -> float:
    try:
        covered = line.intersection(coverage_geometry)
    except Exception:  # noqa: BLE001
        return 0.0
    return max(0.0, min(1.0, covered.length / line.length if line.length else 0.0))
