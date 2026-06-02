"""Build deduplicated navigation water-body assets from raw revier features.

Raw navigation_water_area rows remain the immutable import/audit layer. This
script rebuilds navigation_water_body and navigation_water_body_feature_link as
the production-facing water asset layer.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.strtree import STRtree
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models import NavigationChannelWaterBodyMatch, NavigationWaterArea, NavigationWaterBody, NavigationWaterBodyFeatureLink
from app.modules.navigation.coordinate_transform import bbox_to_gcj02, geometry_to_gcj02_json, wgs84_to_gcj02


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "data_audit" / "navigation_water_body_build_report.json"
REAL_WATER_SOURCE_CODE = "RIVER_SHAPEFILE_2026"
RX_OVERLAP_DUPLICATE_THRESHOLD = 0.80
AREA_KM2_SCALE = Decimal("0.0001")
OVERLAP_RATIO_SCALE = Decimal("0.000001")


@dataclass(slots=True)
class BuildStats:
    raw_feature_count: int = 0
    body_count: int = 0
    hierarchy_body_count: int = 0
    rx_fill_body_count: int = 0
    rx_fill_raw_only_count: int = 0
    rx_duplicate_link_count: int = 0
    rx8_raw_only_count: int = 0
    invalid_raw_only_count: int = 0
    link_count: int = 0
    skipped: bool = False
    skip_reason: str | None = None
    samples: dict[str, dict[str, Any]] = field(default_factory=dict)


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).strip().split())
    return text or None


def _safe_geometry(row: NavigationWaterArea) -> BaseGeometry | None:
    if not row.geometry_json or row.geometry_status_code == "INVALID":
        return None
    try:
        geometry = shape(row.geometry_json)
    except Exception:
        return None
    if geometry.is_empty or geometry.area <= 0:
        return None
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    return None


def _merge_geometry(rows: Iterable[NavigationWaterArea]) -> BaseGeometry | None:
    geometries = [geometry for row in rows if (geometry := _safe_geometry(row)) is not None]
    if not geometries:
        return None
    try:
        return unary_union(geometries)
    except Exception:
        if len(geometries) == 1:
            return geometries[0]
        return MultiPolygon([part for geometry in geometries for part in (geometry.geoms if isinstance(geometry, MultiPolygon) else [geometry])])


def _bbox_from_rows(rows: Iterable[NavigationWaterArea]) -> dict[str, float] | None:
    boxes = []
    for row in rows:
        values = (row.bbox_min_lng, row.bbox_min_lat, row.bbox_max_lng, row.bbox_max_lat)
        if any(value is None for value in values):
            continue
        boxes.append(tuple(float(value) for value in values))
    if not boxes:
        return None
    return {
        "min_lng": min(box[0] for box in boxes),
        "min_lat": min(box[1] for box in boxes),
        "max_lng": max(box[2] for box in boxes),
        "max_lat": max(box[3] for box in boxes),
    }


def _body_code(*parts: Any) -> str:
    raw = "|".join(str(part or "") for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    return f"NWB-{digest}"


def _scaled_decimal(value: float | int | Decimal | None, scale: Decimal) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(scale, rounding=ROUND_HALF_UP)


def _layer_summary(rows: list[NavigationWaterArea]) -> dict[str, Any]:
    counter = Counter(row.source_layer_display_name or row.source_layer_name for row in rows)
    roles = Counter(row.source_layer_role_code or "UNKNOWN" for row in rows)
    return {
        "layers": dict(counter),
        "roles": dict(roles),
        "source_object_ids": [row.source_object_id for row in rows[:100]],
        "source_object_id_count": len(rows),
    }


def _body_payload(
    *,
    code_parts: tuple[Any, ...],
    rows: list[NavigationWaterArea],
    body_role_code: str,
    dedupe_status_code: str,
    quality_code: str | None = None,
) -> dict[str, Any]:
    primary = sorted(rows, key=lambda item: (item.source_layer_order or 999, item.id))[0]
    geometry = _merge_geometry(rows)
    bbox = _bbox_from_rows(rows)
    geometry_json = mapping(geometry) if geometry is not None and not geometry.is_empty else None
    display_geometry = geometry_to_gcj02_json(geometry_json)
    display_bbox = bbox_to_gcj02(bbox)
    center_lng = center_lat = display_center_lng = display_center_lat = None
    if geometry is not None and not geometry.is_empty:
        center = geometry.centroid
        center_lng = float(center.x)
        center_lat = float(center.y)
        display_center_lng, display_center_lat = wgs84_to_gcj02(center_lng, center_lat)
    elif bbox is not None:
        center_lng = (bbox["min_lng"] + bbox["max_lng"]) / 2
        center_lat = (bbox["min_lat"] + bbox["max_lat"]) / 2
        display_center_lng, display_center_lat = wgs84_to_gcj02(center_lng, center_lat)

    area_total = sum(float(row.area_km2 or 0) for row in rows)
    invalid_count = sum(1 for row in rows if row.geometry_status_code == "INVALID")
    repaired_count = sum(1 for row in rows if row.geometry_status_code == "REPAIRED")
    enabled_count = sum(1 for row in rows if row.is_enabled)
    water_levels = [int(row.water_level) for row in rows if row.water_level is not None]
    if quality_code is None:
        if invalid_count and not geometry_json:
            quality_code = "INVALID_BUT_BBOX_AVAILABLE" if bbox else "INVALID"
        elif repaired_count:
            quality_code = "REPAIRED"
        else:
            quality_code = "READY"

    display_name = primary.water_name or primary.normalized_water_name
    is_unnamed = False
    if not display_name:
        display_name = f"未命名水域 {primary.source_layer_display_name or primary.source_layer_name}-{primary.source_object_id}"
        is_unnamed = True

    return {
        "water_body_code": _body_code(*code_parts),
        "water_body_name": display_name,
        "normalized_water_name": primary.normalized_water_name,
        "display_name": display_name,
        "production_name": None if is_unnamed else display_name,
        "name_status_code": "UNNAMED" if is_unnamed else "RAW_NAMED",
        "name_source_code": None if is_unnamed else "REVIER_RAW",
        "name_note": None,
        "source_code": primary.source_code,
        "body_role_code": body_role_code,
        "dedupe_status_code": dedupe_status_code,
        "source_layer_code": primary.source_layer_code,
        "source_layer_name": primary.source_layer_name,
        "source_layer_display_name": primary.source_layer_display_name,
        "source_layer_role_code": primary.source_layer_role_code,
        "source_layer_order": primary.source_layer_order,
        "water_level_min": min(water_levels) if water_levels else None,
        "water_level_max": max(water_levels) if water_levels else None,
        "water_type_code": primary.water_type_code,
        "geometry_wgs84_json": geometry_json,
        "geometry_gcj02_json": display_geometry,
        "bbox_min_lng": bbox["min_lng"] if bbox else None,
        "bbox_min_lat": bbox["min_lat"] if bbox else None,
        "bbox_max_lng": bbox["max_lng"] if bbox else None,
        "bbox_max_lat": bbox["max_lat"] if bbox else None,
        "display_bbox_min_lng": display_bbox["min_lng"] if display_bbox else None,
        "display_bbox_min_lat": display_bbox["min_lat"] if display_bbox else None,
        "display_bbox_max_lng": display_bbox["max_lng"] if display_bbox else None,
        "display_bbox_max_lat": display_bbox["max_lat"] if display_bbox else None,
        "center_lng": center_lng,
        "center_lat": center_lat,
        "display_center_lng": display_center_lng,
        "display_center_lat": display_center_lat,
        "area_km2": _scaled_decimal(area_total, AREA_KM2_SCALE) if area_total else None,
        "feature_count": len(rows),
        "enabled_feature_count": enabled_count,
        "repaired_feature_count": repaired_count,
        "invalid_feature_count": invalid_count,
        "source_layer_summary_json": _layer_summary(rows),
        "source_water_area_ids_json": [int(row.id) for row in rows],
        "quality_code": quality_code,
        "coordinate_system_code": "WGS84",
        "display_coordinate_system_code": "GCJ02_AMAP",
        "is_enabled": bool(geometry_json or bbox),
    }


async def _create_body(
    session: AsyncSession,
    *,
    rows: list[NavigationWaterArea],
    body_role_code: str,
    dedupe_status_code: str,
    link_role_code: str,
    code_parts: tuple[Any, ...],
    is_primary: bool,
    overlap_by_area_id: dict[int, float] | None = None,
) -> NavigationWaterBody:
    body = NavigationWaterBody(
        **_body_payload(
            code_parts=code_parts,
            rows=rows,
            body_role_code=body_role_code,
            dedupe_status_code=dedupe_status_code,
        )
    )
    session.add(body)
    await session.flush()
    for row in rows:
        session.add(
            NavigationWaterBodyFeatureLink(
                water_body_id=body.id,
                water_area_id=row.id,
                link_role_code=link_role_code,
                source_layer_name=row.source_layer_name,
                source_layer_code=row.source_layer_code,
                overlap_ratio=_scaled_decimal((overlap_by_area_id or {}).get(int(row.id)), OVERLAP_RATIO_SCALE),
                is_primary=is_primary,
                source_trace_json={
                    "source_code": row.source_code,
                    "source_layer_name": row.source_layer_name,
                    "source_object_id": row.source_object_id,
                },
            )
        )
    return body


async def _link_duplicate(
    session: AsyncSession,
    *,
    body_id: int,
    row: NavigationWaterArea,
    overlap_ratio: float,
) -> None:
    session.add(
        NavigationWaterBodyFeatureLink(
            water_body_id=body_id,
            water_area_id=row.id,
            link_role_code="RX_DUPLICATE",
            source_layer_name=row.source_layer_name,
            source_layer_code=row.source_layer_code,
            overlap_ratio=_scaled_decimal(overlap_ratio, OVERLAP_RATIO_SCALE),
            is_primary=False,
            source_trace_json={
                "source_code": row.source_code,
                "source_layer_name": row.source_layer_name,
                "source_object_id": row.source_object_id,
                "dedupe_reason": "OVERLAPS_HIERARCHY_WATER_BODY",
            },
        )
    )


def _group_key(row: NavigationWaterArea) -> tuple[Any, ...]:
    name = _norm(row.normalized_water_name or row.water_name)
    identity = name if name else f"UNNAMED:{row.source_layer_name}:{row.source_object_id}"
    return (row.source_code, row.source_layer_code, identity, row.water_type_code)


def _sample_summary(rows: list[NavigationWaterBody], name: str) -> dict[str, Any]:
    matches = [row for row in rows if row.normalized_water_name == name or row.water_body_name == name]
    return {
        "body_count": len(matches),
        "feature_count": sum(int(row.feature_count or 0) for row in matches),
        "roles": dict(Counter(row.body_role_code for row in matches)),
        "quality": dict(Counter(row.quality_code for row in matches)),
        "bbox": [
            {
                "body_code": row.water_body_code,
                "source_layer": row.source_layer_display_name or row.source_layer_name,
                "min_lng": float(row.bbox_min_lng) if row.bbox_min_lng is not None else None,
                "min_lat": float(row.bbox_min_lat) if row.bbox_min_lat is not None else None,
                "max_lng": float(row.bbox_max_lng) if row.bbox_max_lng is not None else None,
                "max_lat": float(row.bbox_max_lat) if row.bbox_max_lat is not None else None,
            }
            for row in matches[:5]
        ],
    }


def _rows_area(rows: Iterable[NavigationWaterArea]) -> float:
    return sum(float(row.area_km2 or 0) for row in rows)


def _is_useful_rx_fill(rows: list[NavigationWaterArea]) -> bool:
    """Decide whether an rx-only gap deserves production water-body status.

    rx is a dense base surface layer. Most rx-only remnants are small unnamed
    slivers after hierarchy dedupe, so production seed keeps only named gaps or
    materially large surfaces. Raw rows remain available in navigation_water_area.
    """
    if any(_norm(row.normalized_water_name or row.water_name) for row in rows):
        return True
    total_area = _rows_area(rows)
    water_types = {row.water_type_code for row in rows}
    if water_types & {"LAKE", "RESERVOIR"}:
        return total_area >= 0.5
    return total_area >= 2.0


async def build_navigation_water_bodies(
    *,
    source_code: str = REAL_WATER_SOURCE_CODE,
    rx_overlap_duplicate_threshold: float = RX_OVERLAP_DUPLICATE_THRESHOLD,
    output_path: Path | None = DEFAULT_OUTPUT,
    force: bool = False,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        existing_match_count = int(
            (await session.scalar(select(func.count()).select_from(NavigationChannelWaterBodyMatch))) or 0
        )
        if existing_match_count and not force:
            stats = BuildStats(
                raw_feature_count=int(
                    (await session.scalar(select(func.count()).select_from(NavigationWaterArea).where(NavigationWaterArea.source_code == source_code)))
                    or 0
                ),
                body_count=int((await session.scalar(select(func.count()).select_from(NavigationWaterBody))) or 0),
                link_count=int((await session.scalar(select(func.count()).select_from(NavigationWaterBodyFeatureLink))) or 0),
                skipped=True,
                skip_reason="navigation_channel_water_body_match exists; use --force only after exporting or intentionally rebuilding assignments",
            )
            report = asdict(stats)
            if output_path:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return report

        await session.execute(delete(NavigationWaterBodyFeatureLink))
        await session.execute(delete(NavigationWaterBody))
        await session.flush()

        rows = list(
            (
                await session.execute(
                    select(NavigationWaterArea).where(NavigationWaterArea.source_code == source_code)
                )
            ).scalars()
        )
        # MySQL sorts full selected rows for ORDER BY; these rows carry large
        # geometry JSON payloads, so keep DB work to filtering and sort locally.
        rows.sort(key=lambda row: (row.source_layer_order or 999, int(row.id or 0)))
        stats = BuildStats(raw_feature_count=len(rows))

        hierarchy_groups: dict[tuple[Any, ...], list[NavigationWaterArea]] = defaultdict(list)
        rx_rows: list[NavigationWaterArea] = []
        rx8_rows: list[NavigationWaterArea] = []
        invalid_rows: list[NavigationWaterArea] = []

        for row in rows:
            if row.geometry_status_code == "INVALID":
                invalid_rows.append(row)
                continue
            if row.source_layer_role_code == "HIERARCHY_LEVEL":
                hierarchy_groups[_group_key(row)].append(row)
            elif row.source_layer_code == "RX":
                rx_rows.append(row)
            elif row.source_layer_code == "RX8":
                rx8_rows.append(row)

        hierarchy_bodies: list[NavigationWaterBody] = []
        hierarchy_geometries: list[BaseGeometry] = []
        hierarchy_ids: list[int] = []
        for key, group_rows in hierarchy_groups.items():
            body = await _create_body(
                session,
                rows=group_rows,
                body_role_code="PRIMARY_HIERARCHY",
                dedupe_status_code="CANONICAL",
                link_role_code="PRIMARY_HIERARCHY",
                code_parts=("HIERARCHY", *key),
                is_primary=True,
            )
            hierarchy_bodies.append(body)
            geometry = _merge_geometry(group_rows)
            if geometry is not None and not geometry.is_empty:
                hierarchy_geometries.append(geometry)
                hierarchy_ids.append(int(body.id))

        stats.hierarchy_body_count = len(hierarchy_bodies)
        await session.flush()

        hierarchy_tree = STRtree(hierarchy_geometries) if hierarchy_geometries else None
        rx_fill_groups: dict[tuple[Any, ...], list[NavigationWaterArea]] = defaultdict(list)
        for row in rx_rows:
            geometry = _safe_geometry(row)
            duplicate_body_id: int | None = None
            duplicate_ratio = 0.0
            if hierarchy_tree is not None and geometry is not None and geometry.area > 0:
                for index in hierarchy_tree.query(geometry):
                    candidate = hierarchy_geometries[int(index)]
                    if not candidate.intersects(geometry):
                        continue
                    ratio = candidate.intersection(geometry).area / geometry.area
                    if ratio > duplicate_ratio:
                        duplicate_ratio = float(ratio)
                        duplicate_body_id = hierarchy_ids[int(index)]
            if duplicate_body_id is not None and duplicate_ratio >= rx_overlap_duplicate_threshold:
                await _link_duplicate(session, body_id=duplicate_body_id, row=row, overlap_ratio=duplicate_ratio)
                stats.rx_duplicate_link_count += 1
                continue
            rx_fill_groups[_group_key(row)].append(row)

        useful_rx_fill_groups = {
            key: group_rows
            for key, group_rows in rx_fill_groups.items()
            if _is_useful_rx_fill(group_rows)
        }
        stats.rx_fill_raw_only_count = sum(len(group_rows) for key, group_rows in rx_fill_groups.items() if key not in useful_rx_fill_groups)

        for key, group_rows in useful_rx_fill_groups.items():
            await _create_body(
                session,
                rows=group_rows,
                body_role_code="RX_FILL_GAP",
                dedupe_status_code="CANONICAL_RX_FILL",
                link_role_code="RX_FILL_GAP",
                code_parts=("RX_FILL", *key),
                is_primary=True,
            )
        stats.rx_fill_body_count = len(useful_rx_fill_groups)
        stats.rx8_raw_only_count = len(rx8_rows)
        stats.invalid_raw_only_count = len(invalid_rows)

        stats.body_count = int((await session.scalar(select(func.count()).select_from(NavigationWaterBody))) or 0)
        stats.link_count = int((await session.scalar(select(func.count()).select_from(NavigationWaterBodyFeatureLink))) or 0)
        body_rows = list((await session.execute(select(NavigationWaterBody))).scalars())
        for sample in ("长江", "西江", "京杭运河", "乌江", "红水河", "黄河"):
            stats.samples[sample] = _sample_summary(body_rows, sample)

        await session.commit()

    report = asdict(stats)
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build deduplicated navigation water-body assets.")
    parser.add_argument("--source-code", default=REAL_WATER_SOURCE_CODE)
    parser.add_argument("--rx-overlap-duplicate-threshold", type=float, default=RX_OVERLAP_DUPLICATE_THRESHOLD)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true", help="Rebuild even when channel-water-body matches already exist.")
    args = parser.parse_args()
    report = asyncio.run(
        build_navigation_water_bodies(
            source_code=args.source_code,
            rx_overlap_duplicate_threshold=args.rx_overlap_duplicate_threshold,
            output_path=args.output,
            force=args.force,
        )
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
