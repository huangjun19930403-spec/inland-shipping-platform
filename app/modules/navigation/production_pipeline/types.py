from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class LayerSourceStats:
    layer_name: str
    source_file_name: str | None = None
    feature_count: int = 0
    valid_count: int = 0
    repaired_count: int = 0
    invalid_count: int = 0
    low_value_count: int = 0
    crs_code: str = "EPSG:4326"
    crs_missing: bool = False
    geometry_type_counts: dict[str, int] = field(default_factory=dict)
    bbox_min_lng: float | None = None
    bbox_min_lat: float | None = None
    bbox_max_lng: float | None = None
    bbox_max_lat: float | None = None

    def include_bbox(self, *, min_lng: Any, min_lat: Any, max_lng: Any, max_lat: Any) -> None:
        try:
            min_lng_float = float(min_lng)
            min_lat_float = float(min_lat)
            max_lng_float = float(max_lng)
            max_lat_float = float(max_lat)
        except (TypeError, ValueError):
            return
        self.bbox_min_lng = min_lng_float if self.bbox_min_lng is None else min(self.bbox_min_lng, min_lng_float)
        self.bbox_min_lat = min_lat_float if self.bbox_min_lat is None else min(self.bbox_min_lat, min_lat_float)
        self.bbox_max_lng = max_lng_float if self.bbox_max_lng is None else max(self.bbox_max_lng, max_lng_float)
        self.bbox_max_lat = max_lat_float if self.bbox_max_lat is None else max(self.bbox_max_lat, max_lat_float)

    def as_dict(self) -> dict[str, Any]:
        return {
            "layer_name": self.layer_name,
            "source_file_name": self.source_file_name,
            "feature_count": self.feature_count,
            "valid_count": self.valid_count,
            "repaired_count": self.repaired_count,
            "invalid_count": self.invalid_count,
            "low_value_count": self.low_value_count,
            "crs_code": self.crs_code,
            "crs_missing": self.crs_missing,
            "geometry_type_counts": dict(sorted(self.geometry_type_counts.items())),
            "bbox": {
                "min_lng": self.bbox_min_lng,
                "min_lat": self.bbox_min_lat,
                "max_lng": self.bbox_max_lng,
                "max_lat": self.bbox_max_lat,
            },
        }


@dataclass(slots=True)
class SeedBuildResult:
    seed_dir: str
    runtime_dir: str
    source_report: dict[str, Any]
    graph_report: dict[str, Any]
    quality_report: dict[str, Any]
    seed_files: list[str]
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed_dir": self.seed_dir,
            "runtime_dir": self.runtime_dir,
            "source_report": self.source_report,
            "graph_report": self.graph_report,
            "quality_report": self.quality_report,
            "seed_files": self.seed_files,
            "warnings": self.warnings,
        }
