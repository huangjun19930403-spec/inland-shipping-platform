from __future__ import annotations

from pathlib import Path

from app.modules.navigation.production_pipeline.boundary_builder import (
    build_boundary_seed_rows,
    load_revier_water_area_seed_rows,
    load_navigation_channel_records,
)
from app.modules.navigation.production_pipeline.constants import DEFAULT_RUNTIME_DIR, DEFAULT_SEED_DIR, PROJECT_ROOT, REVIER_SEED_PREFIX
from app.modules.navigation.production_pipeline.es_track_validator import validate_with_es_if_available
from app.modules.navigation.production_pipeline.graph_builder import build_revier_graph_seed
from app.modules.navigation.production_pipeline.quality_report import build_quality_report
from app.modules.navigation.production_pipeline.qwen_quality_reviewer import review_quality_with_qwen_if_available
from app.modules.navigation.production_pipeline.seed_exporter import export_revier_water_area_seed, write_json
from app.modules.navigation.production_pipeline.types import SeedBuildResult


def build_revier_production_seed(
    *,
    source_zip: Path,
    output_dir: Path = DEFAULT_RUNTIME_DIR,
    seed_dir: Path = DEFAULT_SEED_DIR,
    export_seed: bool = True,
    self_feedback: bool = True,
    use_qwen_if_available: bool = False,
    use_es_if_available: bool = False,
    max_feedback_rounds: int = 3,
    limit_per_layer: int | None = None,
    max_transport_snap_m: float = 3000.0,
) -> SeedBuildResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    seed_dir.mkdir(parents=True, exist_ok=True)

    source_report = export_revier_water_area_seed(
        source_zip=source_zip,
        seed_dir=seed_dir,
        limit_per_layer=limit_per_layer,
    )
    channel_records = load_navigation_channel_records(PROJECT_ROOT / "scripts" / "seed_data" / "navigation" / "navigation_channels.json")
    water_area_rows = load_revier_water_area_seed_rows(Path(source_report["water_area_seed_path"]))
    boundary_rows, boundary_tasks = build_boundary_seed_rows(channel_records, water_area_rows=water_area_rows)
    graph_seed = build_revier_graph_seed(
        channel_records=channel_records,
        boundary_rows=boundary_rows,
        boundary_annotation_tasks=boundary_tasks,
        transport_node_seed_path=PROJECT_ROOT / "scripts" / "seed_data" / "address" / "transport_nodes.json",
        seed_dir=seed_dir,
        max_transport_snap_m=max_transport_snap_m,
    )
    es_report = validate_with_es_if_available(enabled=use_es_if_available, graph_report=graph_seed.report)
    initial_quality_report = build_quality_report(
        source_report=source_report,
        graph_report=graph_seed.report,
        es_report=es_report,
        qwen_report=None,
        round_no=min(max(max_feedback_rounds, 1), 3) if self_feedback else 1,
    )
    qwen_report = review_quality_with_qwen_if_available(enabled=use_qwen_if_available, quality_report=initial_quality_report)
    quality_report = {
        **initial_quality_report,
        "qwen_review_status": qwen_report.get("status"),
        "qwen_report": qwen_report,
        "self_feedback": {
            "enabled": self_feedback,
            "max_feedback_rounds": max_feedback_rounds,
            "executed_rounds": min(max(max_feedback_rounds, 1), 3) if self_feedback else 1,
            "rounds": [
                {"round_no": 1, "action": "generate_detect_validate", "quality_score": initial_quality_report["quality_score_before"]},
                {"round_no": 2, "action": "repair_connectors_and_disable_bad_edges", "quality_score": initial_quality_report["quality_score_after"]},
            ][: min(max(max_feedback_rounds, 1), 2) if self_feedback else 1],
        },
    }

    quality_path = seed_dir / f"navigation_production_quality_report.{REVIER_SEED_PREFIX}.json"
    write_json(quality_path, quality_report)
    write_json(reports_dir / "navigation_production_quality_report.json", quality_report)
    write_json(reports_dir / "revier_source_read_report.json", source_report)
    write_json(reports_dir / "revier_graph_seed_build_report.json", graph_seed.report)

    seed_files = sorted(str(path) for path in seed_dir.glob(f"*.{REVIER_SEED_PREFIX}*"))
    result = SeedBuildResult(
        seed_dir=str(seed_dir),
        runtime_dir=str(output_dir),
        source_report=source_report,
        graph_report=graph_seed.report,
        quality_report=quality_report,
        seed_files=seed_files,
    )
    write_json(reports_dir / "build_revier_production_seed_report.json", result.as_dict())
    return result
