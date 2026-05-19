"""Dashboard, chart query, route-estimate, and job-view service boundary.

The implementation still lives in `service.py` for compatibility while callers
move to this explicit analysis domain entrypoint.
"""

from __future__ import annotations

from app.modules.analysis.service import AnalysisDashboardService, QuoteRouteEstimateService

__all__ = ["AnalysisDashboardService", "QuoteRouteEstimateService"]
