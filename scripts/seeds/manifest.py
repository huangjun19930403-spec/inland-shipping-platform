"""Production seed data manifest validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEED_DATA_ROOT = PROJECT_ROOT / "scripts" / "seed_data"
PRODUCTION_DATA_MANIFEST = SEED_DATA_ROOT / "production_manifest.json"


class SeedManifestError(RuntimeError):
    """Raised when a seed data manifest is invalid."""


def load_seed_manifest(path: Path = PRODUCTION_DATA_MANIFEST) -> dict[str, Any]:
    if not path.exists():
        raise SeedManifestError(f"seed manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_seed_manifest(path: Path = PRODUCTION_DATA_MANIFEST) -> dict[str, Any]:
    manifest = load_seed_manifest(path)
    resources = manifest.get("resources")
    if not isinstance(resources, list) or not resources:
        raise SeedManifestError("seed manifest must contain a non-empty resources list")

    missing: list[str] = []
    invalid: list[str] = []
    for item in resources:
        if not isinstance(item, dict):
            invalid.append(str(item))
            continue
        rel_path = str(item.get("path") or "").strip()
        if not rel_path:
            invalid.append(str(item))
            continue
        data_path = Path(rel_path)
        if not data_path.is_absolute():
            data_path = PROJECT_ROOT / data_path
        if not data_path.exists():
            missing.append(rel_path)

    if invalid:
        raise SeedManifestError(f"invalid seed manifest resource rows: {invalid}")
    if missing:
        raise SeedManifestError(f"seed manifest references missing files: {', '.join(missing)}")
    return manifest
