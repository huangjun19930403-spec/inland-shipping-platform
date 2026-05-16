"""Freight lifecycle seed for Round 11 experience scenarios."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from app.models.freight import (
    Freight,
    FreightBatchTask,
    FreightCandidate,
    FreightClue,
    FreightContact,
    FreightNormalizationSuggestion,
    FreightNormalizationTask,
    FreightTagRelation,
    FreightTmsInbound,
)
from scripts.seeds.demo.experience.shared import NODE_CODES, SCENARIOS, RouteInfo, _business_region_id, _commodity, _money, _node

def _raw_text(
    *,
    freight_no: str,
    scenario: ScenarioDef,
    origin_name: str,
    destination_name: str,
    commodity_name: str,
    tonnage: Decimal,
    shipper_price: Decimal,
    owner_price: Decimal,
    loading_day: datetime,
    risk_note: str | None,
) -> str:
    note = f"；风险提示：{risk_note}" if risk_note else ""
    return (
        f"{freight_no} {origin_name}到{destination_name}，{commodity_name}{int(tonnage)}吨，"
        f"预计{loading_day:%m月%d日}装货，货主报价{shipper_price}元/吨，"
        f"船主/船户报价{owner_price}元/吨；高级配置：账期15天，过闸费按实计，"
        f"保险0.30元/吨，允许回程空驶15%，场景{scenario.code}{note}。"
    )


async def _seed_freight_scenarios(
    session,
    *,
    now: datetime,
    route_infos: dict[str, RouteInfo],
) -> list[Freight]:
    freight_rows: list[Freight] = []
    seq = 0
    for scenario in SCENARIOS:
        origin_node = await _node(session, scenario.origin_node_code)
        default_destination = await _node(session, scenario.destination_node_code) if scenario.destination_node_code else None
        for offset in range(scenario.count):
            seq += 1
            freight_no = f"FR-DEMO-{seq:04d}"
            batch_no = f"FBT-DEMO-{seq:04d}"
            inbound_no = f"FTI-DEMO-{seq:04d}"
            clue_no = f"FCU-DEMO-{seq:04d}"
            candidate_no = f"FCA-DEMO-{seq:04d}"
            is_risk = scenario.risk_mode == "RISK"
            missing_destination = is_risk and offset in {1, 6}
            missing_commodity = is_risk and offset in {3, 8}
            blocked_constraint = is_risk and offset in {0, 4, 9}
            destination_node = None if missing_destination else default_destination
            commodity = await _commodity(session, scenario.commodity_codes, offset)
            tonnage = _money(scenario.tonnage_start + offset * scenario.tonnage_step)
            shipper_price = _money(scenario.shipper_price_start + (offset % 5) * 2)
            owner_price = _money(shipper_price + scenario.owner_price_delta + (offset % 3))
            loading_from = now + timedelta(days=1 + offset)
            loading_to = loading_from + timedelta(hours=8)
            risk_note = None
            if missing_destination:
                risk_note = "卸货地只有城市文本，无法直接计算航线和报价"
            elif missing_commodity:
                risk_note = "货品只保留原文，需要治理后才能进入标准货品分析"
            elif blocked_constraint:
                risk_note = "吃水/桥梁净空约束疑似阻断，需要复核船舶适配"
            origin_name = origin_node.name
            destination_name = destination_node.name if destination_node is not None else "芜湖临港待确认卸点"
            commodity_name = commodity.name if not missing_commodity else "矿建材料未标准化"
            raw_text = _raw_text(
                freight_no=freight_no,
                scenario=scenario,
                origin_name=origin_name,
                destination_name=destination_name,
                commodity_name=commodity_name,
                tonnage=tonnage,
                shipper_price=shipper_price,
                owner_price=owner_price,
                loading_day=loading_from,
                risk_note=risk_note,
            )

            batch = FreightBatchTask(
                batch_no=batch_no,
                source_type_code="WECHAT",
                source_channel_code="WECHAT_TEXT",
                raw_text=raw_text,
                status_code="PARSED",
                review_flow_status_code="APPROVED",
                clue_count=1,
                candidate_count=1,
                success_count=1,
                failed_count=0,
                remark="Round 11 experience scenario semantic batch",
                prompt_version="freight_wechat_experience_round11",
                parse_stage_code="DONE",
                parse_stage_name="解析完成",
                parse_stage_message="已抽取货主报价、船户报价、装卸地、吨位和装货时间。",
                parse_progress_percent=100,
                parse_heartbeat_at=now,
                ai_elapsed_seconds=3,
                started_at=now - timedelta(minutes=20),
                finished_at=now - timedelta(minutes=19),
                ai_pipeline_version="freight_ai_experience_round11",
                ai_semantic_map_json={
                    "scenario": scenario.code,
                    "source_layer": "LOCAL_DEMO",
                    "shipper_quote": float(shipper_price),
                    "owner_quote_text": f"{owner_price}元/吨",
                    "advanced_config_text": "账期15天；过闸费按实计；保险0.30元/吨",
                },
                raw_response_json={"source": "LOCAL_DEMO", "freight_no": freight_no},
                created_at=now,
                updated_at=now,
            )
            inbound = FreightTmsInbound(
                inbound_no=inbound_no,
                source_type_code="TMS",
                source_channel_code="TMS_API",
                source_trace_id=f"trace-{freight_no}",
                idempotency_key=f"round11-{freight_no}",
                external_ref_no=freight_no,
                payload_json={
                    "scenario": scenario.code,
                    "freight_no": freight_no,
                    "origin_node_code": origin_node.code,
                    "destination_node_code": destination_node.code if destination_node else None,
                    "commodity_code": None if missing_commodity else commodity.code,
                    "tonnage": float(tonnage),
                    "shipper_quote": float(shipper_price),
                    "shipowner_quote_text": f"{owner_price}元/吨",
                    "source_layer": "LOCAL_DEMO",
                },
                raw_content=raw_text,
                status_code="PARSED",
                clue_count=1,
                candidate_count=1,
                processed_at=now - timedelta(minutes=18),
                prompt_version="freight_tms_experience_round11",
                raw_response_json={"source": "LOCAL_DEMO", "owner_quote_preserved": True},
                created_at=now,
                updated_at=now,
            )
            session.add_all([batch, inbound])
            await session.flush()

            source_type = "WECHAT" if seq % 2 else "TMS"
            source_channel = "WECHAT_TEXT" if source_type == "WECHAT" else "TMS_API"
            clue = FreightClue(
                clue_no=clue_no,
                source_type_code=source_type,
                source_channel_code=source_channel,
                source_batch_id=batch.id if source_type == "WECHAT" else None,
                source_tms_inbound_id=inbound.id if source_type == "TMS" else None,
                segment_index=1,
                semantic_role_code="FREIGHT_DEMAND",
                raw_text=raw_text,
                line_refs_json=[{"line": 1, "source": source_channel}],
                context_summary=f"{origin_name}到{destination_name}{commodity_name}，保留货主/船户报价证据。",
                extracted_fields_json={
                    "scenario": scenario.code,
                    "shipper_quote": float(shipper_price),
                    "shipowner_quote": float(owner_price),
                    "advanced_config": {"credit_days": 15, "insurance_yuan_per_ton": 0.3},
                    "risk_note": risk_note,
                },
                quality_score=Decimal("0.92") if not risk_note else Decimal("0.68"),
                status_code="CANDIDATE_CREATED",
                created_at=now,
                updated_at=now,
            )
            session.add(clue)
            await session.flush()

            origin_region_id = await _business_region_id(session, origin_node)
            destination_region_id = await _business_region_id(session, destination_node)
            commodity_id = None if missing_commodity else commodity.id
            match_level = "STANDARD" if commodity_id else "RAW"
            candidate = FreightCandidate(
                candidate_no=candidate_no,
                source_type_code=source_type,
                source_channel_code=source_channel,
                source_batch_id=batch.id if source_type == "WECHAT" else None,
                source_tms_inbound_id=inbound.id if source_type == "TMS" else None,
                clue_id=clue.id,
                source_ref_no=freight_no,
                raw_text=raw_text,
                raw_commodity_name=commodity_name,
                raw_tonnage_text=f"{int(tonnage)}吨",
                raw_origin_text=origin_name,
                raw_destination_text=destination_name,
                cargo_title=f"{origin_node.short_name or origin_node.name}至{destination_name}{commodity_name}",
                cargo_description=(
                    f"Round 11 {scenario.code} 场景货源，包含货主报价、船主报价和高级配置原文证据。"
                ),
                commodity_standard_id=commodity_id,
                commodity_match_name=commodity.name if commodity_id else None,
                commodity_match_score=Decimal("0.96") if commodity_id else Decimal("0.41"),
                commodity_match_level_code=match_level,
                commodity_options_json=[{"id": commodity.id, "name": commodity.name, "score": 0.96}],
                packaging_form_code="BULK",
                estimated_tonnage=tonnage,
                min_tonnage=(tonnage * Decimal("0.90")).quantize(Decimal("0.01")),
                max_tonnage=(tonnage * Decimal("1.10")).quantize(Decimal("0.01")),
                unit_price=shipper_price,
                total_price=(tonnage * shipper_price).quantize(Decimal("0.01")),
                price_unit="元/吨",
                settlement_method_code="FREIGHT_COLLECT",
                origin_node_id=origin_node.id,
                destination_node_id=destination_node.id if destination_node else None,
                origin_node_match_score=Decimal("0.98"),
                destination_node_match_score=Decimal("0.97") if destination_node else Decimal("0.35"),
                origin_match_level_code="NODE",
                destination_match_level_code="NODE" if destination_node else "RAW",
                origin_options_json=[{"id": origin_node.id, "name": origin_node.name, "score": 0.98}],
                destination_options_json=[{"id": destination_node.id, "name": destination_node.name, "score": 0.97}]
                if destination_node
                else [{"raw": destination_name, "score": 0.35}],
                origin_province_code=origin_node.province_code,
                origin_city_code=origin_node.city_code,
                origin_district_code=origin_node.district_code,
                destination_province_code=destination_node.province_code if destination_node else None,
                destination_city_code=destination_node.city_code if destination_node else None,
                destination_district_code=destination_node.district_code if destination_node else None,
                origin_region_id_cache=origin_region_id,
                destination_region_id_cache=destination_region_id,
                loading_time_from=loading_from,
                loading_time_to=loading_to,
                unloading_time_from=loading_from + timedelta(days=2),
                unloading_time_to=loading_from + timedelta(days=3),
                publisher_org_name=f"{scenario.publisher_prefix}{(offset % 4) + 1}部",
                contact_name="体验调度",
                contact_phone=f"138{seq:08d}"[-11:],
                contact_wechat=f"demo_freight_{seq:04d}",
                confidence_score=Decimal("0.93") if not risk_note else Decimal("0.66"),
                completeness_score=Decimal("0.91") if not risk_note else Decimal("0.62"),
                match_basis_json={
                    "source_layer": "LOCAL_DEMO",
                    "scenario": scenario.code,
                    "owner_quote_evidence": f"船主/船户报价{owner_price}元/吨",
                },
                ai_suggestion_json={
                    "next_actions": ["CREATE_OPPORTUNITY", "MATCH_VESSELS", "QUOTE_DECISION"],
                    "not_computable_reasons": [risk_note] if risk_note else [],
                },
                ai_understanding_json={"scenario": scenario.code, "raw_owner_quote_preserved": True},
                ai_tool_match_json={
                    "origin_match": "NODE",
                    "destination_match": "NODE" if destination_node else "RAW",
                    "commodity_match": match_level,
                },
                ai_review_json={"status": "PASS" if not risk_note else "REVIEW_REQUIRED", "risk_note": risk_note},
                ai_review_status_code="PASS" if not risk_note else "REVIEW_REQUIRED",
                availability_status_code="AVAILABLE" if not risk_note else "REVIEW_REQUIRED",
                manual_review_reason=risk_note,
                ai_warning_json={"warnings": [risk_note]} if risk_note else None,
                status_code="CONFIRMED",
                confirmed_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(candidate)
            await session.flush()

            freight = Freight(
                freight_no=freight_no,
                source_type_code=source_type,
                source_channel_code=source_channel,
                source_ref_no=freight_no,
                source_batch_id=batch.id if source_type == "WECHAT" else None,
                source_tms_inbound_id=inbound.id if source_type == "TMS" else None,
                source_clue_id=clue.id,
                source_candidate_id=candidate.id,
                raw_commodity_name=commodity_name,
                raw_tonnage_text=f"{int(tonnage)}吨",
                raw_origin_text=origin_name,
                raw_destination_text=destination_name,
                cargo_title=f"{origin_node.short_name or origin_node.name}至{destination_name}{commodity_name}",
                cargo_description=(
                    f"LOCAL_DEMO 场景：{scenario.code}；货主报价 {shipper_price} 元/吨；"
                    f"船主/船户报价 {owner_price} 元/吨保留在原始证据，Round 12 正式建模。"
                ),
                commodity_standard_id=commodity_id,
                commodity_match_level_code=match_level,
                packaging_form_code="BULK",
                estimated_tonnage=tonnage,
                min_tonnage=(tonnage * Decimal("0.90")).quantize(Decimal("0.01")),
                max_tonnage=(tonnage * Decimal("1.10")).quantize(Decimal("0.01")),
                unit_price=shipper_price,
                total_price=(tonnage * shipper_price).quantize(Decimal("0.01")),
                price_unit="元/吨",
                settlement_method_code="FREIGHT_COLLECT",
                origin_node_id=origin_node.id,
                destination_node_id=destination_node.id if destination_node else None,
                origin_match_level_code="NODE",
                destination_match_level_code="NODE" if destination_node else "RAW",
                origin_province_code=origin_node.province_code,
                origin_city_code=origin_node.city_code,
                origin_district_code=origin_node.district_code,
                destination_province_code=destination_node.province_code if destination_node else None,
                destination_city_code=destination_node.city_code if destination_node else None,
                destination_district_code=destination_node.district_code if destination_node else None,
                origin_region_id_cache=origin_region_id,
                destination_region_id_cache=destination_region_id,
                loading_time_from=loading_from,
                loading_time_to=loading_to,
                unloading_time_from=loading_from + timedelta(days=2),
                unloading_time_to=loading_from + timedelta(days=3),
                publisher_org_name=f"{scenario.publisher_prefix}{(offset % 4) + 1}部",
                status_code="PUBLISHED",
                published_at=now,
                expired_at=now + timedelta(days=20),
                confirmed_at=now,
                hall_status_code="LISTED",
                hall_published_at=now,
                hall_visible_until=now + timedelta(days=20),
                audit_status="APPROVED",
                audited_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(freight)
            await session.flush()
            candidate.confirmed_freight_id = freight.id
            candidate.confirmed_at = now
            session.add(
                FreightContact(
                    freight_id=freight.id,
                    contact_name="体验调度",
                    contact_role_code="DISPATCH",
                    mobile_phone=f"138{seq:08d}"[-11:],
                    wechat=f"demo_freight_{seq:04d}",
                    is_primary=True,
                    created_at=now,
                    updated_at=now,
                )
            )
            for tag in ("LOCAL_DEMO", scenario.code, "QUOTE_READY" if not risk_note else "QUALITY_REVIEW"):
                session.add(FreightTagRelation(freight_id=freight.id, tag_code=tag[:64], created_at=now))
            freight_rows.append(freight)

    await _seed_price_history_samples(session, freight_rows, now)
    await _seed_quality_suggestions(session, freight_rows, now)
    await session.flush()
    return freight_rows


async def _seed_price_history_samples(session, freight_rows: list[Freight], now: datetime) -> None:
    """Add comparable historical rate samples for local-demo rate estimation."""
    comparable_roots = [
        row
        for row in freight_rows
        if row.origin_node_id and row.destination_node_id and row.commodity_standard_id and row.unit_price and row.estimated_tonnage
    ][:9]
    sequence = 0
    for root in comparable_roots:
        base_price = Decimal(str(root.unit_price))
        base_tonnage = Decimal(str(root.estimated_tonnage))
        for index, (days_back, price_delta, tonnage_ratio) in enumerate(
            [
                (7, Decimal("-2.5"), Decimal("0.92")),
                (13, Decimal("-1.2"), Decimal("0.96")),
                (21, Decimal("0.4"), Decimal("1.02")),
                (34, Decimal("1.6"), Decimal("1.08")),
                (48, Decimal("2.3"), Decimal("0.88")),
                (72, Decimal("3.1"), Decimal("1.12")),
                (96, Decimal("-3.4"), Decimal("0.84")),
                (126, Decimal("4.2"), Decimal("1.16")),
            ],
            start=1,
        ):
            sequence += 1
            sample_no = f"FR-DEMO-HIST-{sequence:04d}"
            tonnage = (base_tonnage * tonnage_ratio).quantize(Decimal("0.01"))
            unit_price = max(Decimal("8.00"), (base_price + price_delta + Decimal(str(index % 3)) * Decimal("0.35"))).quantize(Decimal("0.01"))
            loading_from = now - timedelta(days=days_back)
            session.add(
                Freight(
                    freight_no=sample_no,
                    source_type_code="LOCAL_DEMO",
                    source_channel_code="RATE_HISTORY",
                    source_ref_no=f"rate-history-{root.freight_no}-{index}",
                    raw_commodity_name=root.raw_commodity_name,
                    raw_tonnage_text=f"{int(tonnage)}吨",
                    raw_origin_text=root.raw_origin_text,
                    raw_destination_text=root.raw_destination_text,
                    cargo_title=f"历史可比样本 {root.cargo_title}",
                    cargo_description=(
                        "LOCAL_DEMO 运价预估历史样本；用于展示同装卸地、同货品、相近吨位、"
                        "不同时间新旧样本的加权估算。"
                    ),
                    commodity_standard_id=root.commodity_standard_id,
                    commodity_match_level_code=root.commodity_match_level_code,
                    packaging_form_code=root.packaging_form_code,
                    estimated_tonnage=tonnage,
                    min_tonnage=(tonnage * Decimal("0.92")).quantize(Decimal("0.01")),
                    max_tonnage=(tonnage * Decimal("1.08")).quantize(Decimal("0.01")),
                    unit_price=unit_price,
                    total_price=(tonnage * unit_price).quantize(Decimal("0.01")),
                    price_unit="元/吨",
                    settlement_method_code=root.settlement_method_code,
                    origin_node_id=root.origin_node_id,
                    destination_node_id=root.destination_node_id,
                    origin_match_level_code="NODE",
                    destination_match_level_code="NODE",
                    origin_province_code=root.origin_province_code,
                    origin_city_code=root.origin_city_code,
                    origin_district_code=root.origin_district_code,
                    destination_province_code=root.destination_province_code,
                    destination_city_code=root.destination_city_code,
                    destination_district_code=root.destination_district_code,
                    origin_region_id_cache=root.origin_region_id_cache,
                    destination_region_id_cache=root.destination_region_id_cache,
                    loading_time_from=loading_from,
                    loading_time_to=loading_from + timedelta(hours=8),
                    unloading_time_from=loading_from + timedelta(days=2),
                    unloading_time_to=loading_from + timedelta(days=3),
                    publisher_org_name=root.publisher_org_name,
                    status_code="PUBLISHED",
                    published_at=loading_from - timedelta(days=1),
                    expired_at=loading_from + timedelta(days=20),
                    confirmed_at=loading_from,
                    hall_status_code="LISTED",
                    hall_published_at=loading_from - timedelta(days=1),
                    hall_visible_until=loading_from + timedelta(days=20),
                    audit_status="APPROVED",
                    audited_at=loading_from,
                    created_at=loading_from,
                    updated_at=now,
                )
            )


async def _seed_quality_suggestions(session, freight_rows: list[Freight], now: datetime) -> None:
    risk_rows = [row for row in freight_rows if row.freight_no >= "FR-DEMO-0033"]
    task = FreightNormalizationTask(
        task_no="FNT-DEMO-0001",
        celery_task_id="round11-experience-normalization",
        status_code="SUCCESS",
        stage_code="DONE",
        stage_name="体验数据质量扫描完成",
        stage_message="已识别节点缺失、货品未标准化和约束复核样例。",
        progress_percent=100,
        scanned_count=len(freight_rows),
        suggestion_count=min(len(risk_rows), 10),
        auto_applied_count=0,
        pending_count=min(len(risk_rows), 10),
        failed_count=0,
        review_status_code="PENDING_REVIEW",
        started_at=now - timedelta(minutes=15),
        finished_at=now - timedelta(minutes=14),
        heartbeat_at=now - timedelta(minutes=14),
        result_json={"source_layer": "LOCAL_DEMO", "scenario": "SCN_RISK_NOT_COMPUTABLE"},
        created_at=now,
        updated_at=now,
    )
    session.add(task)
    await session.flush()
    wuhu = await _node(session, NODE_CODES["WUHU"])
    commodity = await _commodity(session, ("STD_MACHINE_SAND",), 0)
    region_id = await _business_region_id(session, wuhu)
    for index, freight in enumerate(risk_rows[:10], start=1):
        missing_destination = freight.destination_node_id is None
        suggestion_type = "DESTINATION" if missing_destination else "COMMODITY"
        session.add(
            FreightNormalizationSuggestion(
                clean_task_id=task.id,
                freight_id=freight.id,
                suggestion_type_code=suggestion_type,
                raw_text=freight.raw_destination_text if missing_destination else freight.raw_commodity_name,
                current_level_code="RAW",
                suggested_level_code="NODE" if missing_destination else "STANDARD",
                suggested_node_id=wuhu.id if missing_destination else None,
                suggested_commodity_standard_id=None if missing_destination else commodity.id,
                suggested_province_code=wuhu.province_code if missing_destination else None,
                suggested_city_code=wuhu.city_code if missing_destination else None,
                suggested_district_code=wuhu.district_code if missing_destination else None,
                suggested_region_id=region_id if missing_destination else freight.destination_region_id_cache,
                confidence_score=Decimal("0.74") if missing_destination else Decimal("0.71"),
                status_code="PENDING",
                auto_apply_flag=False,
                match_basis_json={"source_layer": "LOCAL_DEMO", "scenario": "SCN_RISK_NOT_COMPUTABLE"},
                before_json={"freight_no": freight.freight_no, "current_level": "RAW"},
                after_json={"suggestion_index": index, "needs_recalc": True},
                created_at=now,
                updated_at=now,
            )
        )
