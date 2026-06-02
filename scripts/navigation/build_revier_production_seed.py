from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.modules.navigation.production_pipeline.constants import DEFAULT_RUNTIME_DIR
from app.modules.navigation.production_pipeline.pipeline import build_revier_production_seed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build curated revier navigation production seed.")
    parser.add_argument("--source-zip", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_RUNTIME_DIR)
    parser.add_argument("--export-seed", action="store_true")
    parser.add_argument("--self-feedback", action="store_true")
    parser.add_argument("--use-qwen-if-available", action="store_true")
    parser.add_argument("--use-es-if-available", action="store_true")
    parser.add_argument("--max-feedback-rounds", type=int, default=3)
    parser.add_argument("--limit-per-layer", type=int, default=None)
    parser.add_argument("--max-transport-snap-m", type=float, default=3000.0)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = build_revier_production_seed(
        source_zip=args.source_zip,
        output_dir=args.output_dir,
        export_seed=args.export_seed,
        self_feedback=args.self_feedback,
        use_qwen_if_available=args.use_qwen_if_available,
        use_es_if_available=args.use_es_if_available,
        max_feedback_rounds=args.max_feedback_rounds,
        limit_per_layer=args.limit_per_layer,
        max_transport_snap_m=args.max_transport_snap_m,
    )
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

