"""Import real OSM waterway GeoJSON as centerline candidates.

The importer only creates NEED_REVIEW OSM_WATERWAY candidates. It never marks
them current and never builds graph edges. Accepted input is GeoJSON exported
from a real OSM extract with LineString/MultiLineString waterway features.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models import NavigationChannelCenterline
from app.models.address import NavigationChannel
from scripts.navigation.build_channel_water_area_matches import DEFAULT_ALIAS_CONFIG, _bbox_intersects, _norm, _terms_for_channel, load_json


@dataclass(slots=True)
class OsmWaterwayImportSummary:
    source_path: str
    dry_run: bool
    feature_count: int
    candidate_count: int
    skipped_count: int
    matched_channel_count: int
    warnings: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _feature_geometry(feature: dict[str, Any]) -> dict[str, Any] | None:
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        return None
    if geometry.get("type") == "LineString":
        return geometry
    if geometry.get("type") == "MultiLineString":
        lines = geometry.get("coordinates") or []
        longest = max((line for line in lines if isinstance(line, list)), key=len, default=None)
        if longest and len(longest) >= 2:
            return {"type": "LineString", "coordinates": longest}
    return None


def _geometry_bbox(geometry: dict[str, Any]) -> dict[str, float | None]:
    coords = geometry.get("coordinates") or []
    points = [point for point in coords if isinstance(point, list) and len(point) >= 2]
    if not points:
        return {"bbox_min_lng": None, "bbox_min_lat": None, "bbox_max_lng": None, "bbox_max_lat": None}
    lngs = [float(point[0]) for point in points]
    lats = [float(point[1]) for point in points]
    return {
        "bbox_min_lng": min(lngs),
        "bbox_min_lat": min(lats),
        "bbox_max_lng": max(lngs),
        "bbox_max_lat": max(lats),
    }


def _bbox_list(bbox: dict[str, float | None]) -> list[float | None]:
    return [bbox["bbox_min_lng"], bbox["bbox_min_lat"], bbox["bbox_max_lng"], bbox["bbox_max_lat"]]


def _feature_name(properties: dict[str, Any]) -> str | None:
    for key in ("name", "name:zh", "name:zh-Hans", "name:en"):
        value = properties.get(key)
        if value:
            return str(value)
    return None


def _candidate_channels(
    *,
    feature: dict[str, Any],
    bbox: dict[str, float | None],
    channels: list[NavigationChannel],
    terms_by_channel: dict[int, dict[str, set[str]]],
) -> list[tuple[NavigationChannel, int, str]]:
    properties = feature.get("properties") or {}
    direct_code = properties.get("channel_code")
    if direct_code:
        matched = [channel for channel in channels if channel.channel_code == str(direct_code)]
        return [(channel, 95, "CHANNEL_CODE") for channel in matched]

    name = _norm(_feature_name(properties))
    if not name:
        return []
    matches: list[tuple[NavigationChannel, int, str]] = []
    feature_bbox = _bbox_list(bbox)
    for channel in channels:
        channel_bbox = [
            float(channel.bbox_min_lng) if getattr(channel, "bbox_min_lng", None) is not None else None,
            float(channel.bbox_min_lat) if getattr(channel, "bbox_min_lat", None) is not None else None,
            float(channel.bbox_max_lng) if getattr(channel, "bbox_max_lng", None) is not None else None,
            float(channel.bbox_max_lat) if getattr(channel, "bbox_max_lat", None) is not None else None,
        ]
        if not _bbox_intersects(feature_bbox, channel_bbox):
            continue
        terms = terms_by_channel[channel.id]
        if name in terms["exact"]:
            matches.append((channel, 88, "EXACT_NAME"))
        elif name in terms["alias"]:
            matches.append((channel, 82, "ALIAS_NAME"))
        else:
            for term in terms["exact"] | terms["alias"]:
                if len(term) >= 2 and (term in name or name in term):
                    matches.append((channel, 62, "CONTAINS_NAME"))
                    break
    matches.sort(key=lambda item: item[1], reverse=True)
    return matches[:3]


async def import_osm_waterways(
    *,
    session: AsyncSession,
    source_path: Path,
    alias_config_path: Path = DEFAULT_ALIAS_CONFIG,
    scope_code: str = "REAL-JS-YRD",
    dry_run: bool = True,
) -> OsmWaterwayImportSummary:
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        raise ValueError("OSM waterway input must be a GeoJSON FeatureCollection")

    alias_config = load_json(alias_config_path)
    channels = list(
        (
            await session.execute(
                select(NavigationChannel)
                .where(NavigationChannel.is_enabled.is_(True))
                .order_by(NavigationChannel.sort_order, NavigationChannel.id)
            )
        ).scalars()
    )
    terms_by_channel = {channel.id: _terms_for_channel(channel, alias_config) for channel in channels}
    matched_channel_ids: set[int] = set()
    candidate_count = 0
    skipped_count = 0
    warnings: list[str] = []
    batch_code = f"OSM-WATERWAY-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"

    for index, feature in enumerate(features, start=1):
        if not isinstance(feature, dict):
            skipped_count += 1
            continue
        geometry = _feature_geometry(feature)
        if geometry is None:
            skipped_count += 1
            continue
        bbox = _geometry_bbox(geometry)
        candidates = _candidate_channels(
            feature=feature,
            bbox=bbox,
            channels=channels,
            terms_by_channel=terms_by_channel,
        )
        if not candidates:
            skipped_count += 1
            continue
        properties = feature.get("properties") or {}
        name = _feature_name(properties)
        osm_id = properties.get("osm_id") or properties.get("@id") or properties.get("id") or index
        for channel, score, match_type in candidates:
            matched_channel_ids.add(channel.id)
            candidate_count += 1
            if dry_run:
                continue
            code = f"OSM-{channel.channel_code}-{osm_id}".replace("/", "-")[:96]
            existing = (
                await session.execute(
                    select(NavigationChannelCenterline).where(NavigationChannelCenterline.centerline_code == code)
                )
            ).scalar_one_or_none()
            values = {
                "channel_id": channel.id,
                "centerline_name": name or f"{channel.channel_name} OSM 候选中心线",
                "geometry_json": geometry,
                "source_type_code": "OSM_WATERWAY",
                "direction_code": "BIDIRECTIONAL",
                "is_main_line": True,
                "confidence_score": score,
                "quality_code": "NEED_REVIEW",
                "review_status_code": "NEED_REVIEW",
                "is_current": False,
                "source_trace_json": {
                    "batch_code": batch_code,
                    "source_path": str(source_path),
                    "scope_code": scope_code,
                    "match_type_code": match_type,
                    "osm_properties": properties,
                },
                **bbox,
            }
            if existing is None:
                session.add(NavigationChannelCenterline(centerline_code=code, **values))
            else:
                for key, value in values.items():
                    setattr(existing, key, value)

    if not dry_run:
        await session.commit()
    if candidate_count == 0:
        warnings.append("未从真实 OSM 输入匹配到任何航道中心线候选。")
    return OsmWaterwayImportSummary(
        source_path=str(source_path),
        dry_run=dry_run,
        feature_count=len(features),
        candidate_count=candidate_count,
        skipped_count=skipped_count,
        matched_channel_count=len(matched_channel_ids),
        warnings=warnings,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import real OSM waterway GeoJSON as navigation centerline candidates.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--scope-code", default="REAL-JS-YRD")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    async with AsyncSessionLocal() as session:
        summary = await import_osm_waterways(
            session=session,
            source_path=args.input,
            scope_code=args.scope_code,
            dry_run=args.dry_run,
        )
    print(json.dumps(summary.as_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
