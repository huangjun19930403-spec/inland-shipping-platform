from __future__ import annotations

from app.tasks.celery_app import celery_app


def test_celery_registry_contains_route_and_production_precompute_tasks() -> None:
    celery_app.loader.import_default_modules()
    registered = set(celery_app.tasks.keys())

    assert "route.generate_track_version" in registered
    assert "vessel.precompute_production_candidate_analyses" in registered
    assert "analysis.run_job" in registered
    assert "freight.parse_wechat_batch" in registered
    assert "vessel.recognize_certificate_image" in registered
