from __future__ import annotations

from dataclasses import dataclass

from app.modules.navigation.engine.types import RouteIssue, SearchResult, SnapResult


@dataclass(slots=True)
class QualityResult:
    quality_score: int
    quality_code: str
    issues: list[RouteIssue]


def _snap_penalty(snap: SnapResult) -> tuple[int, RouteIssue | None]:
    if snap.snap_distance_m <= 200:
        return 0, None
    if snap.snap_distance_m <= 500:
        return 5, RouteIssue(f"{snap.role}_SNAP_MEDIUM_CONFIDENCE", "WARNING", f"{snap.role.title()} snap distance is {snap.snap_distance_m:.1f}m")
    return 15, RouteIssue(f"{snap.role}_SNAP_LOW_CONFIDENCE", "WARNING", f"{snap.role.title()} snap distance is {snap.snap_distance_m:.1f}m")


def _quality_code(score: int, issues: list[RouteIssue]) -> str:
    if any(issue.severity_code == "ERROR" for issue in issues):
        return "FAILED"
    if score >= 90:
        if any(issue.issue_type_code == "UNKNOWN_CONSTRAINT_DATA" for issue in issues):
            return "READY_WITH_WARNING"
        return "READY"
    if score >= 75:
        return "READY_WITH_WARNING"
    if score >= 60:
        return "NEED_REVIEW"
    return "FAILED"


class QualityScorer:
    def score(
        self,
        *,
        origin_snap: SnapResult,
        destination_snap: SnapResult,
        search_result: SearchResult,
        validation_issues: list[RouteIssue],
    ) -> QualityResult:
        score = 100
        issues: list[RouteIssue] = [*search_result.issues, *validation_issues]

        for snap in (origin_snap, destination_snap):
            penalty, issue = _snap_penalty(snap)
            score -= penalty
            if issue:
                issues.append(issue)

        seen_unknown_edges: set[int] = set()
        unknown_constraint_penalty = 0
        for segment in search_result.segments:
            if segment.quality_code in {"LOW_CONFIDENCE"}:
                score -= 3
                issues.append(
                    RouteIssue("LOW_CONFIDENCE_EDGE", "WARNING", "Path uses a low-confidence graph edge", related_edge_id=segment.edge_id)
                )
            if segment.quality_code in {"NEED_REVIEW", "SHORT_EDGE_REVIEW"}:
                score -= 5
                issues.append(
                    RouteIssue("EDGE_NEED_MANUAL_REVIEW", "WARNING", "Path uses an edge that needs production repair", related_edge_id=segment.edge_id)
                )
            if segment.unknown_constraint_flag and segment.edge_id not in seen_unknown_edges:
                if unknown_constraint_penalty < 20:
                    score -= 2
                    unknown_constraint_penalty += 2
                seen_unknown_edges.add(segment.edge_id or -1)
                issues.append(
                    RouteIssue(
                        "UNKNOWN_CONSTRAINT_DATA",
                        "WARNING",
                        "Constraint data is incomplete; this result is not a navigation safety confirmation",
                        related_edge_id=segment.edge_id,
                    )
                )

        score = max(0, min(100, score))
        return QualityResult(quality_score=score, quality_code=_quality_code(score, issues), issues=issues)
