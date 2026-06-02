from __future__ import annotations

from typing import Any

from app.core.config import settings


def validate_with_es_if_available(*, enabled: bool, graph_report: dict[str, Any]) -> dict[str, Any]:
    if not enabled:
        return {"status": "ES_SKIPPED", "reason": "use_es_if_available=false"}
    host = (settings.ES_R_HOST or settings.ES_HOST or "").strip()
    if not host:
        return {"status": "ES_SKIPPED", "reason": "ES host is not configured"}
    # The production seed is deterministic and must not depend on AIS/ES. This
    # hook records the configured index and leaves runtime traffic evidence as a
    # non-blocking warning unless a dedicated validator is run in an environment
    # with network access.
    return {
        "status": "ES_READY_FOR_OPTIONAL_VALIDATION",
        "index": settings.ES_R_INDEX or settings.ES_HISTORY_INDEX_PREFIX,
        "validated_edge_count": 0,
        "validated_route_count": 0,
        "issues": ["ES_PROBE_NOT_EXECUTED_IN_SEED_BUILD"],
        "graph_edge_count": graph_report.get("graph_edge_count", 0),
    }

