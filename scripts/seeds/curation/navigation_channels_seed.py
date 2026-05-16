"""Curate navigation-channel seed JSON.

The runtime production seed reads only curated JSON. This tool can copy and
validate the current curated result, and can inspect a future revier.zip source
without importing it into production seed.
"""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path
from typing import Any

from scripts.seeds.loaders.navigation_channels import (
    BOUNDARY_COUNT,
    CHANNEL_COUNT,
    NAVIGATION_CHANNEL_DATA_FILE,
    SEGMENT_COUNT,
    SOURCE_AUDIT_COUNT,
    load_navigation_channel_seed,
)


def _validate_payload(payload: dict[str, Any]) -> dict[str, int]:
    records = payload.get("records")
    audits = payload.get("excluded_source_audit")
    if not isinstance(records, list) or not isinstance(audits, list):
        raise RuntimeError("navigation payload must contain records and excluded_source_audit lists")
    counts = {
        "channels": len(records),
        "boundaries": sum(1 for item in records if item["boundary"]["geometry_status_code"] == "AVAILABLE"),
        "segments": sum(len(item["segments"]) for item in records),
        "source_audits": sum(len(item["source_audit"]) for item in records) + len(audits),
    }
    expected = {
        "channels": CHANNEL_COUNT,
        "boundaries": BOUNDARY_COUNT,
        "segments": SEGMENT_COUNT,
        "source_audits": SOURCE_AUDIT_COUNT,
    }
    mismatched = {
        key: (counts[key], expected[key])
        for key in expected
        if counts[key] != expected[key]
    }
    if mismatched:
        raise RuntimeError(f"navigation payload count mismatch: {mismatched}")
    return counts


def _inspect_source_zip(source_zip: Path) -> dict[str, Any]:
    with zipfile.ZipFile(source_zip) as archive:
        names = archive.namelist()
    suffix_counts: dict[str, int] = {}
    shp_groups: set[str] = set()
    for name in names:
        suffix = Path(name).suffix.lower() or "<none>"
        suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1
        if suffix in {".shp", ".dbf", ".shx", ".prj", ".cpg"}:
            shp_groups.add(str(Path(name).with_suffix("")))
    return {
        "source_zip": str(source_zip),
        "file_count": len(names),
        "suffix_counts": suffix_counts,
        "shapefile_group_count": len(shp_groups),
    }


def curate_navigation_channels(
    *,
    current_json: Path = NAVIGATION_CHANNEL_DATA_FILE,
    output: Path | None = None,
    source_zip: Path | None = None,
    write_curated: bool = False,
) -> dict[str, Any]:
    payload = load_navigation_channel_seed(current_json)
    counts = _validate_payload(payload)
    report: dict[str, Any] = {"curated_json": str(current_json), "counts": counts}
    if source_zip is not None:
        report["source_zip_inspection"] = _inspect_source_zip(source_zip)
    if write_curated:
        if output is None:
            raise RuntimeError("--output is required with --write-curated")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        report["written"] = str(output)
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate or write curated navigation-channel seed JSON.")
    parser.add_argument("--current-json", type=Path, default=NAVIGATION_CHANNEL_DATA_FILE)
    parser.add_argument("--source-zip", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--write-curated", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report = curate_navigation_channels(
        current_json=args.current_json,
        output=args.output,
        source_zip=args.source_zip,
        write_curated=args.write_curated,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
