"""Generate demo/test analysis facts from seeded base data."""

from __future__ import annotations

from datetime import date, timedelta

from app.tasks.analysis_tasks import _run_analysis_job


async def seed_analysis_facts_for_profile(*, profile: str, days: int = 14) -> dict:
    """Run the same analysis aggregation used by the app for demo/test data."""

    end = date.today()
    start = end - timedelta(days=max(1, days) - 1)
    return await _run_analysis_job(
        "ANALYSIS_ALL_DAILY",
        start.isoformat(),
        end.isoformat(),
        True,
        {
            "triggered_by": f"{profile}-seed",
            "seed_profile": profile,
            "source_layer_code": "LOCAL_DEMO" if profile == "local-demo" else "TEST_FIXTURE",
        },
    )
