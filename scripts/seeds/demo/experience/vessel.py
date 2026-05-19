"""Vessel, spatial and matching seed for Round 11 experience scenarios."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.integrations.config_keys import ES_R_INDEX, ES_REALTIME_CONFIG_PROFILE
from app.integrations.es.realtime_client import RealtimeEsClient
from app.models.freight import Freight
from app.models.vessel import (
    VesselAisCitySnapshotItem,
    VesselAisSnapshot,
    VesselCandidateAnalysis,
    VesselCandidateAnalysisItem,
    VesselLatestPositionSnapshot,
    VesselNavigationConstraintEvidence,
    VesselNodeObservationItem,
    VesselNodeObservationVessel,
    VesselProfileSummary,
    VesselRouteSegmentMatchSample,
    VesselRouteSegmentObservationItem,
    VesselSpatialObservationSnapshot,
)
from app.modules.system.runtime_config import RuntimeConfigService
from scripts.seeds.demo.experience.shared import (
    AIS_SNAPSHOT_ID,
    DEMO_SOURCE_INDEX,
    NODE_SNAPSHOT_IDS,
    ROUTE_SNAPSHOT_IDS,
    SCENARIO_VERSION,
    DemoPosition,
    _constraint,
    _coord,
    _hash,
    _interpolate,
    _money,
    _node,
    _offset,
)

async def _query_realtime_positions(session, summaries: list[VesselProfileSummary]) -> tuple[dict[str, dict[str, Any]], str | None]:
    mmsi_values = [str(row.current_mmsi or "").strip() for row in summaries if row.current_mmsi]
    if not mmsi_values:
        return {}, "no mmsi values available"
    runtime_config = RuntimeConfigService(session)
    client = RealtimeEsClient(runtime_config=runtime_config, max_retries=0)
    index = (
        await runtime_config.get_value(
            ES_R_INDEX,
            settings.ES_R_INDEX or "ship_positions",
            profile_code=ES_REALTIME_CONFIG_PROFILE,
        )
        or "ship_positions"
    ).strip()
    query_body = {
        "size": min(max(len(mmsi_values) * 2, 200), 1000),
        "track_total_hits": False,
        "_source": [
            "shipMmsi",
            "mmsi",
            "lon",
            "lng",
            "longitude",
            "lat",
            "latitude",
            "speed",
            "sog",
            "course",
            "heading",
            "posTime",
            "updateTime",
            "timestamp",
            "@timestamp",
            "city_name",
            "city",
            "city_code",
            "cityCode",
            "adcode",
        ],
        "query": {
            "bool": {
                "should": [{"terms": {field: mmsi_values}} for field in ("shipMmsi", "mmsi", "MMSI")],
                "minimum_should_match": 1,
            }
        },
    }
    try:
        payload = await client.search(index, query_body)
    except Exception as exc:  # noqa: BLE001
        return {}, str(exc)
    hits = ((payload.get("hits") or {}).get("hits") or []) if isinstance(payload, dict) else []
    positions: dict[str, dict[str, Any]] = {}
    for hit in hits:
        source = hit.get("_source") if isinstance(hit, dict) else None
        if not isinstance(source, dict):
            continue
        mmsi = str(source.get("shipMmsi") or source.get("mmsi") or source.get("MMSI") or "").strip()
        if not mmsi:
            continue
        lng = source.get("lon") or source.get("lng") or source.get("longitude")
        lat = source.get("lat") or source.get("latitude")
        if lng in (None, "") or lat in (None, ""):
            continue
        positions[mmsi] = {
            "longitude": _coord(lng),
            "latitude": _coord(lat),
            "speed_kn": _money(source.get("speed") or source.get("sog") or 0),
            "course_deg": _money(source.get("course") or 90),
            "heading_deg": _money(source.get("heading") or source.get("course") or 90),
            "source_index": hit.get("_index") or index,
            "raw_city_code": source.get("city_code") or source.get("cityCode") or source.get("adcode"),
            "raw_city_name": source.get("city_name") or source.get("city"),
        }
    return positions, None


async def _load_summaries(session) -> list[VesselProfileSummary]:
    rows = (
        await session.execute(
            select(VesselProfileSummary)
            .where(VesselProfileSummary.current_mmsi.is_not(None))
            .order_by(
                VesselProfileSummary.data_quality_score.desc().nullslast(),
                VesselProfileSummary.profile_completeness_rate.desc().nullslast(),
                VesselProfileSummary.contact_available.desc().nullslast(),
                VesselProfileSummary.deadweight_ton.desc().nullslast(),
                VesselProfileSummary.risk_level.asc(),
                VesselProfileSummary.vessel_profile_id.asc(),
            )
            .limit(90)
        )
    ).scalars().all()
    if len(rows) < 60:
        raise RuntimeError("experience seed requires at least 60 vessel profile summaries")
    return list(rows)


async def _seed_ais_and_positions(
    session,
    *,
    now: datetime,
    nodes_by_key: dict[str, TransportNode],
) -> list[DemoPosition]:
    summaries = await _load_summaries(session)
    real_positions, es_error = await _query_realtime_positions(session, summaries[:60])
    use_real_es = len(real_positions) >= 8
    source_indices = sorted({str(item.get("source_index")) for item in real_positions.values() if item.get("source_index")})
    if not use_real_es:
        source_indices = [DEMO_SOURCE_INDEX]

    demo_positions: list[DemoPosition] = []
    node_cycle = [
        nodes_by_key["TAICANG"],
        nodes_by_key["JIANGYIN"],
        nodes_by_key["NANJING"],
        nodes_by_key["WUHU"],
    ]
    for index, summary in enumerate(summaries[:72]):
        node = node_cycle[index % len(node_cycle)]
        mmsi = str(summary.current_mmsi or "")
        if use_real_es and mmsi in real_positions:
            real = real_positions[mmsi]
            lng = real["longitude"]
            lat = real["latitude"]
            source_index = str(real.get("source_index") or "ES_REALTIME")
            city_code = str(real.get("raw_city_code") or node.city_code or "")
            city_name = str(real.get("raw_city_name") or node.name or "")
            speed_kn = _money(real.get("speed_kn") or 5)
            course_deg = _money(real.get("course_deg") or 90)
            heading_deg = _money(real.get("heading_deg") or 90)
        else:
            lng, lat = _offset(node.longitude, node.latitude, index)
            source_index = DEMO_SOURCE_INDEX
            city_code = node.city_code
            city_name = node.name
            speed_kn = _money(2 + index % 8)
            course_deg = _money(65 + (index % 16) * 7)
            heading_deg = course_deg
        freshness = "FRESH"
        position_time = now - timedelta(minutes=8 + index)
        if index % 11 == 0:
            freshness = "STALE"
            position_time = now - timedelta(hours=5, minutes=index)
        if index % 23 == 0:
            freshness = "EXPIRED"
            position_time = now - timedelta(days=2, minutes=index)
        demo_positions.append(
            DemoPosition(
                summary=summary,
                longitude=lng,
                latitude=lat,
                city_code=city_code,
                city_name=city_name,
                position_time=position_time,
                freshness_level=freshness,
                source_index=source_index,
                speed_kn=speed_kn,
                course_deg=course_deg,
                heading_deg=heading_deg,
            )
        )

    freshness_counts: dict[str, int] = {}
    for item in demo_positions:
        freshness_counts[item.freshness_level] = freshness_counts.get(item.freshness_level, 0) + 1
    session.add(
        VesselAisSnapshot(
            snapshot_id=AIS_SNAPSHOT_ID,
            query_hash="demo-experience-current-ais",
            query_params_json={
                "profile": "local-demo",
                "scenario_version": SCENARIO_VERSION,
                "es_strategy": "REAL_ES" if use_real_es else "DEMO_ES_MIRROR",
                "es_error": None if use_real_es else es_error,
            },
            status_code="READY",
            generated_at=now,
            expires_at=now + timedelta(days=30),
            cache_backend_code="local-demo",
            scanned_profile_count=len(summaries[:72]),
            queried_mmsi_count=len(summaries[:72]),
            matched_profile_count=len(demo_positions),
            matched_position_count=len(demo_positions),
            unmatched_mmsi_count=0,
            invalid_position_count=0,
            unknown_city_count=0,
            failed_batch_count=0 if use_real_es else 1,
            failed_batches_json=[] if use_real_es else [{"source": "ES_REALTIME", "fallback": DEMO_SOURCE_INDEX, "error": es_error}],
            coverage_rate=Decimal("100.00"),
            freshness_distribution_json=freshness_counts,
            source_indices_json=source_indices,
            uncertainty_notes_json=[] if use_real_es else ["实时 ES 不足 8 条可用场景船位，local-demo 使用 DEMO_ES_MIRROR 镜像数据。"],
            created_at=now,
            updated_at=now,
        )
    )
    await session.flush()

    city_counts: dict[tuple[str | None, str | None], dict[str, int]] = {}
    for item in demo_positions:
        key = (item.city_code, item.city_name)
        bucket = city_counts.setdefault(key, {"FRESH": 0, "STALE": 0, "EXPIRED": 0})
        bucket[item.freshness_level] = bucket.get(item.freshness_level, 0) + 1
    for (city_code, city_name), counts in city_counts.items():
        total = sum(counts.values())
        session.add(
            VesselAisCitySnapshotItem(
                snapshot_id=AIS_SNAPSHOT_ID,
                city_code=city_code,
                city_name=city_name or "体验水域",
                positioned_count=total,
                matched_position_count=total,
                unmatched_mmsi_count=0,
                invalid_position_count=0,
                stale_position_count=counts.get("STALE", 0) + counts.get("EXPIRED", 0),
                freshness_distribution_json=counts,
                boundary_status_code="AVAILABLE",
                has_boundary=True,
                boundary_precision="CITY",
                latest_position_time=now,
                created_at=now,
            )
        )

    for item in demo_positions:
        summary = item.summary
        session.add(
            VesselLatestPositionSnapshot(
                snapshot_id=AIS_SNAPSHOT_ID,
                vessel_profile_id=summary.vessel_profile_id,
                mmsi=str(summary.current_mmsi or ""),
                longitude=item.longitude,
                latitude=item.latitude,
                speed_kn=item.speed_kn,
                course_deg=item.course_deg,
                heading_deg=item.heading_deg,
                position_time=item.position_time,
                source_index=item.source_index,
                freshness_level=item.freshness_level,
                match_status_code="MATCHED_PROFILE",
                city_code=item.city_code,
                city_name=item.city_name,
                valid_position_flag=True,
                created_at=now,
            )
        )
        summary.latest_position_time = item.position_time
        summary.latest_city_code = item.city_code
        summary.latest_city_name = item.city_name
        summary.ais_freshness_level = item.freshness_level
        summary.source_layer = "LOCAL_DEMO"
        summary.data_sources_json = [
            {
                "source_layer": "LOCAL_DEMO",
                "source_index": item.source_index,
                "snapshot_id": AIS_SNAPSHOT_ID,
            }
        ]
        summary.refreshed_at = now
        summary.updated_at = now
    await session.flush()
    return demo_positions


def _position_by_profile(demo_positions: list[DemoPosition]) -> dict[int, DemoPosition]:
    return {int(item.summary.vessel_profile_id): item for item in demo_positions}


async def _seed_node_observations(
    session,
    *,
    now: datetime,
    nodes_by_key: dict[str, TransportNode],
    demo_positions: list[DemoPosition],
) -> None:
    for index, (node_key, snapshot_id) in enumerate(NODE_SNAPSHOT_IDS.items()):
        node = nodes_by_key[node_key]
        vessels = demo_positions[index * 12 : (index + 1) * 12]
        freshness_counts: dict[str, int] = {}
        for item in vessels:
            freshness_counts[item.freshness_level] = freshness_counts.get(item.freshness_level, 0) + 1
        stale_count = freshness_counts.get("STALE", 0) + freshness_counts.get("EXPIRED", 0)
        session.add(
            VesselSpatialObservationSnapshot(
                snapshot_id=snapshot_id,
                source_snapshot_id=AIS_SNAPSHOT_ID,
                observation_type_code="NODE_SURROUNDING",
                query_hash=_hash(f"demo-node-{node.code}"),
                query_params_json={"node_id": node.id, "node_code": node.code, "radius_km": 12, "source_layer": "LOCAL_DEMO"},
                status_code="READY",
                source_status_code="AVAILABLE",
                stat_time=now,
                window_start=now - timedelta(hours=6),
                window_end=now,
                generated_at=now,
                expires_at=now + timedelta(days=30),
                coverage_rate=Decimal("96.00"),
                confidence_level="HIGH",
                freshness_distribution_json=freshness_counts,
                source_indices_json=[DEMO_SOURCE_INDEX],
                stale_position_count=stale_count,
                matched_position_count=len(vessels),
                active_vessel_count=len(vessels),
                quality_warnings_json=[] if stale_count < 4 else ["部分 AIS 已过期，需复核可用性。"],
                uncertainty_notes_json=["DEMO_ES_MIRROR mirrors realtime ES schema for local-demo only."],
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        session.add(
            VesselNodeObservationItem(
                snapshot_id=snapshot_id,
                node_id=node.id,
                node_name=node.name,
                node_type_code=node.node_type_code,
                city_code=node.city_code,
                radius_km=Decimal("12.00"),
                longitude=_coord(node.longitude),
                latitude=_coord(node.latitude),
                active_vessel_count=len(vessels),
                stay_vessel_count=4 + index,
                passby_vessel_count=len(vessels) - 4 - index,
                inflow_count=3 + index,
                outflow_count=2 + index,
                stale_position_count=stale_count,
                coverage_rate=Decimal("96.00"),
                confidence_level="HIGH",
                freshness_distribution_json=freshness_counts,
                ship_type_distribution_json=[
                    {"ship_type_code": "DRY_BULK", "count": 5},
                    {"ship_type_code": "SELF_UNLOADING_SAND", "count": 4},
                    {"ship_type_code": "GENERAL_CARGO", "count": 3},
                ],
                risk_distribution_json=[
                    {"risk_level": "LOW", "count": 8},
                    {"risk_level": "MEDIUM", "count": 3},
                    {"risk_level": "HIGH", "count": 1},
                ],
                latest_position_time=now,
                created_at=now,
            )
        )
        for vessel_index, item in enumerate(vessels, start=1):
            lng, lat = _offset(node.longitude, node.latitude, vessel_index)
            session.add(
                VesselNodeObservationVessel(
                    snapshot_id=snapshot_id,
                    node_id=node.id,
                    vessel_profile_id=item.summary.vessel_profile_id,
                    mmsi=str(item.summary.current_mmsi or ""),
                    ship_name=item.summary.ship_name,
                    ship_type_code=item.summary.ship_type_code,
                    deadweight_ton=item.summary.deadweight_ton,
                    longitude=lng,
                    latitude=lat,
                    distance_km=Decimal(str(0.8 + vessel_index * 0.45)).quantize(Decimal("0.001")),
                    position_time=item.position_time,
                    source_index=item.source_index,
                    freshness_level=item.freshness_level,
                    match_status_code="NEARBY",
                    stay_duration_minutes=35 + vessel_index * 6,
                    direction_status_code="STAYING" if vessel_index % 3 == 0 else "PASSING",
                    risk_level=item.summary.risk_level,
                    quality_level=item.summary.data_quality_level,
                    created_at=now,
                )
            )


async def _seed_route_segment_observations(
    session,
    *,
    now: datetime,
    demo_positions: list[DemoPosition],
) -> None:
    return


async def _seed_constraint_evidence(
    session,
    *,
    now: datetime,
    nodes_by_key: dict[str, TransportNode],
) -> None:
    constraints = [
        await _constraint(session, "NC_JIANGYIN_BRIDGE_CLEARANCE"),
        await _constraint(session, "NC_CHANGZHOU_BENNIU_LOCK"),
        await _constraint(session, "NC_TAICANG_WATER_DEPTH"),
    ]
    statuses = ["PASS", "WARNING", "BLOCKED", "UNKNOWN"]
    contexts: list[tuple[str, str, int, NavigationConstraintPoint]] = []
    for node_key, snapshot_id in NODE_SNAPSHOT_IDS.items():
        node = nodes_by_key[node_key]
        contexts.append((snapshot_id, "NODE", node.id, constraints[len(contexts) % len(constraints)]))
    while len(contexts) < 18:
        node = list(nodes_by_key.values())[len(contexts) % len(nodes_by_key)]
        contexts.append((NODE_SNAPSHOT_IDS["TAICANG"], "NODE", node.id, constraints[len(contexts) % len(constraints)]))
    for index, (snapshot_id, context_type, context_id, constraint) in enumerate(contexts[:18], start=1):
        status = statuses[(index - 1) % len(statuses)]
        value = {
            "required_draft_m": round(2.0 + (index % 5) * 0.3, 2),
            "observed_water_depth_m": round(3.0 + (index % 4) * 0.25, 2),
            "shipowner_quote_impact": "blocked" if status == "BLOCKED" else "review" if status == "WARNING" else "none",
            "source_layer": "LOCAL_DEMO",
        }
        session.add(
            VesselNavigationConstraintEvidence(
                snapshot_id=snapshot_id,
                context_type_code=context_type,
                context_id=context_id,
                constraint_point_id=constraint.id,
                constraint_name=constraint.name,
                constraint_type_code=constraint.constraint_type_code,
                status_code=status,
                source_type_code="LOCAL_DEMO",
                source_ref="round11-experience-constraint",
                observed_at=now - timedelta(minutes=index),
                expires_at=now + timedelta(days=7),
                value_json=value,
                confidence_level="HIGH" if status in {"PASS", "BLOCKED"} else "MEDIUM",
                unavailable_reason="demo unknown provider state" if status == "UNKNOWN" else None,
                created_at=now,
            )
        )


async def _seed_candidate_analyses(
    session,
    *,
    now: datetime,
    freight_rows: list[Freight],
    demo_positions: list[DemoPosition],
) -> None:
    return
