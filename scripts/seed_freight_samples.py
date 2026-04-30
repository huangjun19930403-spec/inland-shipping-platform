"""货源采集与 AI 候选链路本地验证样例 seed。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.address import RegionCityRelation, TransportNode
from app.models.commodity import CommodityStandard
from app.models.freight import (
    Freight,
    FreightAiParseTask,
    FreightCandidate,
    FreightCandidateFeedback,
    FreightClue,
    FreightContact,
    FreightSourceInbound,
    FreightTagRelation,
)


PUBLISHERS = [
    "南京港航货运服务有限公司",
    "芜湖长江散货物流有限公司",
    "武汉江海联运有限公司",
    "湖州内河供应链有限公司",
    "苏南运河物流有限公司",
    "岳阳港航大宗货源中心",
    "珠江内河运输服务有限公司",
]

SOURCE_PLAN = [
    ("MANUAL", "MANUAL_FORM"),
    ("WECHAT", "WECHAT_TEXT"),
    ("TMS", "TMS_API"),
    ("IMPORT", "IMPORT_FILE"),
]

STATUS_PLAN = ["PUBLISHED", "PUBLISHED", "PUBLISHED", "MATCHING", "DRAFT", "EXPIRED"]
TAG_PLAN = ["URGENT", "HIGH_VALUE", "FIXED_ROUTE", "LONG_TERM"]


def _money(value: int | float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _tonnage(idx: int) -> Decimal:
    return _money(600 + ((idx * 137) % 9400))


async def _load_nodes(session) -> list[TransportNode]:
    rows = (
        await session.execute(
            select(TransportNode)
            .where(TransportNode.deleted_at.is_(None), TransportNode.status == 1)
            .order_by(TransportNode.is_hot_node.desc(), TransportNode.sort_order.asc(), TransportNode.id.asc())
        )
    ).scalars().all()
    return list(rows)


async def _load_commodities(session) -> list[CommodityStandard]:
    rows = (
        await session.execute(
            select(CommodityStandard)
            .where(CommodityStandard.deleted_at.is_(None), CommodityStandard.is_active.is_(True))
            .order_by(CommodityStandard.sort_order.asc() if hasattr(CommodityStandard, "sort_order") else CommodityStandard.id.asc())
        )
    ).scalars().all()
    return list(rows)


async def _business_region_id(session, node: TransportNode) -> int | None:
    relation = await session.scalar(
        select(RegionCityRelation)
        .where(RegionCityRelation.city_region_id == node.city_region_id)
        .order_by(RegionCityRelation.is_primary.desc(), RegionCityRelation.sort_order.asc())
    )
    return int(relation.region_id) if relation is not None else None


async def _clear_sample_data(session) -> None:
    sample_candidates = (
        await session.execute(select(FreightCandidate.id).where(FreightCandidate.candidate_no.like("FCA-LOCAL-%")))
    ).scalars().all()
    sample_task_ids = (
        await session.execute(select(FreightAiParseTask.id).where(FreightAiParseTask.task_no.like("FPT-LOCAL-%")))
    ).scalars().all()
    sample_freight_ids = (
        await session.execute(select(Freight.id).where(Freight.freight_no.like("FR-LOCAL-%")))
    ).scalars().all()
    if sample_candidates:
        await session.execute(delete(FreightCandidateFeedback).where(FreightCandidateFeedback.candidate_id.in_(sample_candidates)))
    if sample_freight_ids:
        await session.execute(delete(FreightContact).where(FreightContact.freight_id.in_(sample_freight_ids)))
        await session.execute(delete(FreightTagRelation).where(FreightTagRelation.freight_id.in_(sample_freight_ids)))
        await session.execute(delete(Freight).where(Freight.id.in_(sample_freight_ids)))
    if sample_candidates:
        await session.execute(delete(FreightCandidate).where(FreightCandidate.id.in_(sample_candidates)))
    if sample_task_ids:
        await session.execute(delete(FreightClue).where(FreightClue.parse_task_id.in_(sample_task_ids)))
        await session.execute(delete(FreightAiParseTask).where(FreightAiParseTask.id.in_(sample_task_ids)))
    await session.execute(delete(FreightSourceInbound).where(FreightSourceInbound.inbound_no.like("FSI-LOCAL-%")))


async def seed_freight_samples() -> None:
    async with AsyncSessionLocal() as session:
        nodes = await _load_nodes(session)
        commodities = await _load_commodities(session)
        if len(nodes) < 2 or not commodities:
            raise RuntimeError("seed_freight_samples requires seeded transport nodes and commodities")

        await _clear_sample_data(session)
        now = datetime.utcnow()
        node_region_cache: dict[int, int | None] = {}

        async def region_id(node: TransportNode) -> int | None:
            if node.id not in node_region_cache:
                node_region_cache[node.id] = await _business_region_id(session, node)
            return node_region_cache[node.id]

        freight_rows: list[Freight] = []
        for idx in range(1, 241):
            origin = nodes[(idx * 3) % len(nodes)]
            destination = nodes[(idx * 7 + 5) % len(nodes)]
            if origin.id == destination.id:
                destination = nodes[(idx * 7 + 6) % len(nodes)]
            commodity = commodities[(idx * 5) % len(commodities)]
            source_type, source_channel = SOURCE_PLAN[idx % len(SOURCE_PLAN)]
            tonnage = _tonnage(idx)
            unit_price = _money(18 + ((idx * 11) % 55))
            status = STATUS_PLAN[idx % len(STATUS_PLAN)]
            published_at = now - timedelta(days=idx % 60)
            expired_at = published_at + timedelta(days=5 + idx % 25)
            freight = Freight(
                freight_no=f"FR-LOCAL-{idx:04d}",
                source_type_code=source_type,
                source_channel_code=source_channel,
                source_ref_no=f"{source_channel}-{idx:04d}",
                cargo_title=f"{origin.short_name or origin.name}至{destination.short_name or destination.name}{commodity.short_name or commodity.name}",
                cargo_description=f"{commodity.name}内河运输，起运 {origin.name}，到达 {destination.name}，适合散货/件杂货常规船型。",
                commodity_standard_id=commodity.id,
                packaging_form_code="CONTAINER" if "箱" in commodity.name else "BULK",
                estimated_tonnage=tonnage,
                min_tonnage=(tonnage * Decimal("0.85")).quantize(Decimal("0.01")),
                max_tonnage=(tonnage * Decimal("1.15")).quantize(Decimal("0.01")),
                unit_price=unit_price,
                total_price=(tonnage * unit_price).quantize(Decimal("0.01")),
                price_unit="元/吨",
                settlement_method_code=None,
                origin_node_id=origin.id,
                destination_node_id=destination.id,
                origin_province_code=origin.province_code,
                origin_city_code=origin.city_code,
                origin_district_code=origin.district_code,
                destination_province_code=destination.province_code,
                destination_city_code=destination.city_code,
                destination_district_code=destination.district_code,
                origin_region_id_cache=await region_id(origin),
                destination_region_id_cache=await region_id(destination),
                loading_time_from=published_at + timedelta(days=1),
                loading_time_to=published_at + timedelta(days=4),
                unloading_time_from=published_at + timedelta(days=3),
                unloading_time_to=published_at + timedelta(days=8),
                publisher_org_name=PUBLISHERS[idx % len(PUBLISHERS)],
                status_code=status,
                published_at=published_at if status != "DRAFT" else None,
                expired_at=expired_at,
                audit_status="APPROVED",
                audited_at=published_at,
            )
            session.add(freight)
            await session.flush()
            freight_rows.append(freight)
            session.add(
                FreightContact(
                    freight_id=freight.id,
                    contact_name=f"货源经理{idx:03d}",
                    contact_role_code="FREIGHT_CONTACT",
                    mobile_phone=f"13{idx % 10}{(idx * 7919) % 100000000:08d}"[:11],
                    landline_phone=None,
                    wechat=f"cargo{idx:04d}",
                    is_primary=True,
                )
            )
            session.add(
                FreightTagRelation(
                    freight_id=freight.id,
                    tag_code=TAG_PLAN[idx % len(TAG_PLAN)],
                    created_at=published_at,
                )
            )

        for idx in range(1, 41):
            origin = nodes[(idx * 4) % len(nodes)]
            destination = nodes[(idx * 9 + 3) % len(nodes)]
            commodity = commodities[(idx * 7) % len(commodities)]
            tonnage = _tonnage(idx + 300)
            price = _money(20 + ((idx * 13) % 48))
            received_at = now - timedelta(hours=idx * 3)
            raw_text = (
                f"{origin.name}装{commodity.name}{int(tonnage)}吨，到{destination.name}，"
                f"运价{price}元/吨，三天内装，联系李经理13{idx % 10}{(idx * 4567) % 100000000:08d}"
            )
            inbound = FreightSourceInbound(
                inbound_no=f"FSI-LOCAL-{idx:04d}",
                source_type_code="WECHAT" if idx % 3 else "TMS",
                source_channel_code="WECHAT_TEXT" if idx % 3 else "TMS_API",
                external_ref_no=f"WX-GROUP-{idx:04d}" if idx % 3 else f"TMS-IN-{idx:04d}",
                sender_name="长江货源群" if idx % 3 else "区域 TMS",
                sender_contact=f"wechat-group-{idx:03d}" if idx % 3 else "tms-api",
                raw_title=f"{origin.short_name or origin.name}至{destination.short_name or destination.name}货源",
                raw_content=raw_text,
                received_at=received_at,
                status_code="PARSED",
            )
            session.add(inbound)
            await session.flush()

            task = FreightAiParseTask(
                task_no=f"FPT-LOCAL-{idx:04d}",
                source_inbound_id=inbound.id,
                source_type_code=inbound.source_type_code,
                source_channel_code=inbound.source_channel_code,
                raw_content=raw_text,
                status_code="SUCCESS",
                ai_provider_code="DASHSCOPE_QWEN",
                ai_model="qwen-plus",
                prompt_version="freight_parse_v1",
                requested_by=1,
                started_at=received_at + timedelta(minutes=1),
                finished_at=received_at + timedelta(minutes=2),
                raw_response_json={
                    "parsed_payload": {
                        "segments": [
                            {
                                "raw_text": raw_text,
                                "cargo_title": f"{origin.short_name or origin.name}至{destination.short_name or destination.name}{commodity.name}",
                                "commodity_name": commodity.name,
                                "origin_text": origin.name,
                                "destination_text": destination.name,
                                "estimated_tonnage": int(tonnage),
                                "unit_price": str(price),
                                "price_unit": "元/吨",
                                "contact_name": "李经理",
                                "confidence_score": 0.86,
                            }
                        ]
                    }
                },
            )
            session.add(task)
            await session.flush()
            inbound.parse_task_id = task.id

            clue = FreightClue(
                clue_no=f"FCU-LOCAL-{idx:04d}",
                parse_task_id=task.id,
                source_inbound_id=inbound.id,
                segment_index=1,
                raw_text=raw_text,
                status_code="CANDIDATE_CREATED",
                parse_result_json={"commodity_name": commodity.name, "origin_text": origin.name, "destination_text": destination.name},
            )
            session.add(clue)
            await session.flush()
            status = "PENDING"
            confirmed_freight_id = None
            confirmed_at = None
            if idx <= 12:
                status = "CONFIRMED"
                confirmed_freight_id = freight_rows[idx - 1].id
                confirmed_at = received_at + timedelta(minutes=30)
                freight_rows[idx - 1].source_candidate_id = None
                freight_rows[idx - 1].confirmed_at = confirmed_at
                freight_rows[idx - 1].confirmed_by = 1
            elif idx % 7 == 0:
                status = "REJECTED"

            candidate = FreightCandidate(
                candidate_no=f"FCA-LOCAL-{idx:04d}",
                parse_task_id=task.id,
                clue_id=clue.id,
                source_inbound_id=inbound.id,
                cargo_title=f"{origin.short_name or origin.name}至{destination.short_name or destination.name}{commodity.name}",
                cargo_description=f"AI 样例候选：{raw_text}",
                commodity_standard_id=commodity.id,
                commodity_match_name=commodity.name,
                commodity_match_score=Decimal("1.0000"),
                packaging_form_code="CONTAINER" if "箱" in commodity.name else "BULK",
                estimated_tonnage=tonnage,
                unit_price=price,
                total_price=(tonnage * price).quantize(Decimal("0.01")),
                price_unit="元/吨",
                origin_text=origin.name,
                destination_text=destination.name,
                origin_node_id=origin.id,
                destination_node_id=destination.id,
                origin_province_code=origin.province_code,
                origin_city_code=origin.city_code,
                origin_district_code=origin.district_code,
                destination_province_code=destination.province_code,
                destination_city_code=destination.city_code,
                destination_district_code=destination.district_code,
                origin_region_id_cache=await region_id(origin),
                destination_region_id_cache=await region_id(destination),
                publisher_org_name=PUBLISHERS[idx % len(PUBLISHERS)],
                contact_name="李经理",
                contact_phone=f"13{idx % 10}{(idx * 4567) % 100000000:08d}"[:11],
                confidence_score=Decimal("0.8600"),
                match_basis_json={
                    "commodity": {"status": "STANDARD_EXACT", "name": commodity.name},
                    "origin": {"status": "NODE_EXACT", "name": origin.name},
                    "destination": {"status": "NODE_EXACT", "name": destination.name},
                    "evidence": [raw_text],
                },
                status_code=status,
                confirmed_freight_id=confirmed_freight_id,
                confirmed_at=confirmed_at,
            )
            session.add(candidate)
            await session.flush()
            if idx <= 12:
                freight_rows[idx - 1].source_candidate_id = candidate.id
                session.add(
                    FreightCandidateFeedback(
                        candidate_id=candidate.id,
                        action_code="CONFIRM",
                        before_json={"status_code": "PENDING"},
                        after_json={"status_code": "CONFIRMED", "freight_id": confirmed_freight_id},
                        feedback_remark="本地样例：AI 候选确认入库",
                        operator_id=1,
                        operated_at=confirmed_at or now,
                        created_at=confirmed_at or now,
                    )
                )
            elif status == "REJECTED":
                session.add(
                    FreightCandidateFeedback(
                        candidate_id=candidate.id,
                        action_code="REJECT",
                        before_json={"status_code": "PENDING"},
                        after_json={"status_code": "REJECTED"},
                        feedback_remark="本地样例：起终点描述不完整，业务驳回",
                        operator_id=1,
                        operated_at=received_at + timedelta(minutes=35),
                        created_at=received_at + timedelta(minutes=35),
                    )
                )

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_freight_samples())
