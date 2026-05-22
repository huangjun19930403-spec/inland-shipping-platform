"""Read-only Celery task registration health check."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.tasks.celery_app import celery_app


EXPECTED_TASKS = {
    "analysis.run_job",
    "analysis.precompute_flow_route_cache",
    "freight.clean_normalization",
    "freight.parse_tms_inbound",
    "freight.parse_wechat_batch",
    "route.generate_track_version",
    "vessel.precompute_ais_situation",
    "vessel.precompute_channel_situation",
    "vessel.precompute_city_situation",
    "vessel.precompute_production_candidate_analyses",
    "vessel.recognize_certificate_image",
    "vessel.recognize_owner_document_image",
    "vessel.recognize_person_certificate_image",
}
EXPECTED_QUEUES = {"analysis", "freight_ai", "vessel_ai"}


def _task_names(values: Iterable[str]) -> set[str]:
    return {item.strip() for item in values if item and not item.startswith("celery.")}


def _print_missing(title: str, missing: set[str]) -> None:
    if not missing:
        print(f"{title}: OK")
        return
    print(f"{title}: MISSING")
    for item in sorted(missing):
        print(f"  - {item}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local and worker Celery task registrations.")
    parser.add_argument("--inspect-workers", action="store_true", help="Also inspect online workers through the Celery broker.")
    parser.add_argument("--timeout", type=float, default=2.0, help="Celery inspect timeout in seconds.")
    args = parser.parse_args()

    celery_app.loader.import_default_modules()
    local_registered = _task_names(celery_app.tasks.keys())
    local_missing = EXPECTED_TASKS - local_registered
    _print_missing("Local app registry", local_missing)

    failed = bool(local_missing)
    if not args.inspect_workers:
        return 1 if failed else 0

    inspector = celery_app.control.inspect(timeout=args.timeout)
    worker_registered = inspector.registered() or {}
    worker_queues = inspector.active_queues() or {}
    if not worker_registered:
        print("Worker inspect: no online workers responded")
        return 1

    for worker_name, tasks in sorted(worker_registered.items()):
        missing = EXPECTED_TASKS - _task_names(tasks)
        _print_missing(f"Worker registry {worker_name}", missing)
        failed = failed or bool(missing)

    for worker_name, queues in sorted(worker_queues.items()):
        queue_names = {str(item.get("name")) for item in queues if isinstance(item, dict)}
        missing_queues = EXPECTED_QUEUES - queue_names
        _print_missing(f"Worker queues {worker_name}", missing_queues)
        failed = failed or bool(missing_queues)

    if failed:
        print("Hint: stop old Celery workers, then restart from the backend repo root with .venv/bin/celery.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
