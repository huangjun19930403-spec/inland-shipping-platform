"""Orchestrator for Round 11 local-demo experience scenarios."""

from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.freight import Freight
from app.models.vessel import VesselCandidateAnalysis
from scripts.experience_seed.cleanup import _clear_experience_rows
from scripts.experience_seed.freight import _seed_freight_scenarios
from scripts.experience_seed.routes import _seed_routes
from scripts.experience_seed.shared import AIS_SNAPSHOT_ID, _node
from scripts.experience_seed.vessel import (
    _seed_ais_and_positions,
    _seed_candidate_analyses,
    _seed_constraint_evidence,
    _seed_node_observations,
    _seed_route_segment_observations,
)


async def seed_experience_scenarios() -> None:
    async with AsyncSessionLocal() as session:
        now = datetime.utcnow()
        await _clear_experience_rows(session)
        route_infos = await _seed_routes(session, now)
        nodes_by_key = {
            "TAICANG": await _node(session, "NODE_SUZHOU_TAICANG_PORT"),
            "JIANGYIN": await _node(session, "NODE_WX_JIANGYIN_PORT"),
            "NANJING": await _node(session, "NODE_NJ_LONGTAN_PORT"),
            "WUHU": await _node(session, "NODE_WUHU_ZHUJIAQIAO_PORT"),
        }
        freight_rows = await _seed_freight_scenarios(session, now=now, route_infos=route_infos)
        demo_positions = await _seed_ais_and_positions(session, now=now, nodes_by_key=nodes_by_key)
        await _seed_node_observations(session, now=now, nodes_by_key=nodes_by_key, demo_positions=demo_positions)
        await _seed_route_segment_observations(session, now=now, route_infos=route_infos, demo_positions=demo_positions)
        await _seed_constraint_evidence(session, now=now, route_infos=route_infos, nodes_by_key=nodes_by_key)
        await _seed_candidate_analyses(
            session,
            now=now,
            freight_rows=freight_rows,
            route_infos=route_infos,
            demo_positions=demo_positions,
        )
        await session.commit()

        demo_freight_count = await session.scalar(select(func.count(Freight.id)).where(Freight.freight_no.like("FR-DEMO-%")))
        demo_analysis_count = await session.scalar(
            select(func.count(VesselCandidateAnalysis.id)).where(
                VesselCandidateAnalysis.query_hash.like("demo-experience-%")
            )
        )
        print(
            "seed_experience_scenarios completed: "
            f"freights={int(demo_freight_count or 0)}, "
            f"candidate_analyses={int(demo_analysis_count or 0)}, "
            f"ais_snapshot={AIS_SNAPSHOT_ID}"
        )


if __name__ == "__main__":
    asyncio.run(seed_experience_scenarios())
