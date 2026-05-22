from __future__ import annotations

from shapely.geometry import LineString, shape

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
