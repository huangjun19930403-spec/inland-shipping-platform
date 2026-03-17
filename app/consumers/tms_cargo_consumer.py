"""
TMS货源 RQ 消费者
Topic: tms.cargo.available
消息体格式: TMS系统推送的标准货源JSON

数据流：
  TMS RQ Topic → tms_cargo_raw（幂等暂存）
                → 节点匹配（名称/坐标/区域匹配）
                → cargo_freight（导入主表）
                → refresh_cargo_stats（事件驱动刷新统计）

启动方式（在 main.py 的 lifespan 中注册，或独立运行）:
    python -m app.consumers.tms_cargo_consumer
"""
import asyncio
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from app.core.database import AsyncSessionLocal
from app.models.cargo import CargoFreight, TmsCargoRaw
from app.repositories.cargo_repository import CargoRepository

logger = logging.getLogger(__name__)

RQ_TOPIC = "tms.cargo.available"
RQ_GROUP_ID = "inland-tms-cargo-group"


# ─────────────────────────────────────────────────
# 位置匹配逻辑（节点名称/坐标 → 系统内节点/城市）
# ─────────────────────────────────────────────────

async def _match_location(
    db,
    location_name: Optional[str],
    lng: Optional[float],
    lat: Optional[float],
) -> dict:
    """尝试将TMS位置数据匹配为系统内节点或城市

    匹配策略优先级：
    1. NAME_EXACT   — 节点名称精确匹配
    2. NAME_FUZZY   — 节点名称模糊匹配（contains）
    3. PROXIMITY    — 坐标半径匹配（±0.1度范围内最近节点）
    4. FALLBACK     — 无法匹配，仅保留坐标
    """
    from sqlalchemy import select, and_, func
    from app.models.address import TransportNode, AdminRegion

    result = {
        "node_id": None,
        "admin_code": None,
        "admin_name": None,
        "precision": "UNKNOWN",
        "strategy": "FALLBACK",
        "confidence": 0,
    }

    if not location_name and not (lng and lat):
        return result

    # 策略1: 名称精确匹配节点
    if location_name:
        node_result = await db.execute(
            select(TransportNode).where(
                and_(
                    TransportNode.name == location_name,
                    TransportNode.deleted_at.is_(None),
                )
            ).limit(1)
        )
        node = node_result.scalar_one_or_none()
        if node:
            result.update({
                "node_id": node.id,
                "precision": "NODE",
                "strategy": "NAME_EXACT",
                "confidence": 95,
            })
            return result

    # 策略2: 名称模糊匹配节点
    if location_name:
        node_result = await db.execute(
            select(TransportNode).where(
                and_(
                    TransportNode.name.ilike(f"%{location_name}%"),
                    TransportNode.deleted_at.is_(None),
                )
            ).limit(1)
        )
        node = node_result.scalar_one_or_none()
        if node:
            result.update({
                "node_id": node.id,
                "precision": "NODE",
                "strategy": "NAME_FUZZY",
                "confidence": 75,
            })
            return result

    # 策略3: 坐标临近匹配节点（±0.1度，约11km）
    if lng and lat:
        node_result = await db.execute(
            select(TransportNode).where(
                and_(
                    TransportNode.longitude.between(lng - 0.1, lng + 0.1),
                    TransportNode.latitude.between(lat - 0.1, lat + 0.1),
                    TransportNode.deleted_at.is_(None),
                )
            ).limit(1)
        )
        node = node_result.scalar_one_or_none()
        if node:
            result.update({
                "node_id": node.id,
                "precision": "NODE",
                "strategy": "PROXIMITY",
                "confidence": 60,
            })
            return result

    # 策略4: 通过城市名匹配 AdminRegion（城市级回退）
    if location_name:
        region_result = await db.execute(
            select(AdminRegion).where(
                AdminRegion.name.ilike(f"%{location_name}%")
            ).limit(1)
        )
        region = region_result.scalar_one_or_none()
        if region:
            result.update({
                "admin_code": region.code,
                "admin_name": region.name,
                "precision": "CITY",
                "strategy": "REGION",
                "confidence": 50,
            })
            return result

    # 策略5: 仅有坐标
    if lng and lat:
        result.update({
            "precision": "COORDINATE",
            "strategy": "FALLBACK",
            "confidence": 20,
        })

    return result


# ─────────────────────────────────────────────────
# 单条消息处理
# ─────────────────────────────────────────────────

async def _process_tms_message(payload: dict) -> None:
    """处理单条TMS货源消息

    期望 payload 格式（TMS系统约定）：
    {
        "message_id": "TMS-2024-XXXXX",  # 唯一消息ID（幂等键）
        "order_no": "TMS-ORDER-XXX",      # TMS订单号
        "origin_name": "上海港",
        "origin_lng": 121.4737,
        "origin_lat": 31.2304,
        "origin_region": "华东",
        "dest_name": "武汉港",
        "dest_lng": 114.3162,
        "dest_lat": 30.5810,
        "dest_region": "华中",
        "commodity_name": "煤炭",
        "tonnage": 5000.0,
        "loading_date": "2024-06-01",
        "freight_price": 45.5,
        "contact_person": "张三",
        "contact_phone": "13800138000"
    }
    """
    message_id = payload.get("message_id")
    if not message_id:
        logger.warning("[tms_consumer] 消息缺少 message_id，跳过")
        return

    async with AsyncSessionLocal() as db:
        try:
            cargo_repo = CargoRepository(db)

            # 幂等检查：已处理过则跳过
            existing = await cargo_repo.get_tms_raw_by_msg_id(message_id)
            if existing and existing.process_status in ("IMPORTED", "MATCHED"):
                logger.info(f"[tms_consumer] 消息已处理 message_id={message_id}，跳过")
                return

            # 写入暂存表（INSERT OR 已存在则UPDATE）
            tms_raw = existing or TmsCargoRaw(
                tms_message_id=message_id,
                raw_payload=payload,
                consumed_at=datetime.now(),
            )
            if not existing:
                tms_raw.tms_origin_name = payload.get("origin_name")
                tms_raw.tms_origin_lng = payload.get("origin_lng")
                tms_raw.tms_origin_lat = payload.get("origin_lat")
                tms_raw.tms_origin_region = payload.get("origin_region")
                tms_raw.tms_dest_name = payload.get("dest_name")
                tms_raw.tms_dest_lng = payload.get("dest_lng")
                tms_raw.tms_dest_lat = payload.get("dest_lat")
                tms_raw.tms_dest_region = payload.get("dest_region")
                tms_raw = await cargo_repo.create_tms_raw(tms_raw)
            else:
                tms_raw = await cargo_repo.update_tms_raw(
                    tms_raw.id, process_status="PENDING", consumed_at=datetime.now()
                )

            # 节点/城市匹配
            origin_match = await _match_location(
                db,
                payload.get("origin_name"),
                payload.get("origin_lng"),
                payload.get("origin_lat"),
            )
            dest_match = await _match_location(
                db,
                payload.get("dest_name"),
                payload.get("dest_lng"),
                payload.get("dest_lat"),
            )

            avg_confidence = (origin_match["confidence"] + dest_match["confidence"]) // 2
            strategy = origin_match["strategy"]

            # 更新暂存表的匹配结果
            await cargo_repo.update_tms_raw(
                tms_raw.id,
                matched_origin_node_id=origin_match["node_id"],
                matched_origin_admin_code=origin_match["admin_code"],
                matched_dest_node_id=dest_match["node_id"],
                matched_dest_admin_code=dest_match["admin_code"],
                match_strategy=strategy,
                match_confidence=avg_confidence,
                process_status="MATCHED",
            )

            # 构建 CargoFreight 导入主表
            loading_date_str = payload.get("loading_date")
            loading_date = (
                date.fromisoformat(loading_date_str) if loading_date_str else None
            )

            freight_no = f"TMS-{datetime.now().strftime('%Y%m%d')}-{message_id[-8:].upper()}"
            freight = CargoFreight(
                freight_no=freight_no,
                source_type="TMS",
                status="CONFIRMED",
                # 装货地
                origin_node_id=origin_match["node_id"],
                origin_admin_code=origin_match["admin_code"],
                origin_admin_name=origin_match["admin_name"],
                origin_longitude=payload.get("origin_lng"),
                origin_latitude=payload.get("origin_lat"),
                origin_raw_text=payload.get("origin_name"),
                origin_precision=origin_match["precision"],
                # 卸货地
                dest_node_id=dest_match["node_id"],
                dest_admin_code=dest_match["admin_code"],
                dest_admin_name=dest_match["admin_name"],
                dest_longitude=payload.get("dest_lng"),
                dest_latitude=payload.get("dest_lat"),
                dest_raw_text=payload.get("dest_name"),
                dest_precision=dest_match["precision"],
                # 货物
                commodity_text=payload.get("commodity_name"),
                tonnage=payload.get("tonnage"),
                loading_date=loading_date,
                freight_price=payload.get("freight_price"),
                contact_person=payload.get("contact_person"),
                contact_phone=payload.get("contact_phone"),
                # 来源追踪
                tms_external_id=payload.get("order_no"),
                tms_raw_data=payload,
                # 审核（TMS数据质量高，自动通过审核）
                audit_status=1,
            )
            saved_freight = await cargo_repo.create_freight(freight)

            # 关联暂存表
            await cargo_repo.update_tms_raw(
                tms_raw.id,
                process_status="IMPORTED",
                freight_id=saved_freight.id,
            )

            await db.commit()

            # 事件驱动刷新统计
            from app.tasks.stat_tasks import refresh_cargo_stats
            asyncio.create_task(refresh_cargo_stats(date.today()))

            logger.info(
                f"[tms_consumer] 导入成功 message_id={message_id} "
                f"freight_id={saved_freight.id} "
                f"origin_strategy={origin_match['strategy']}({origin_match['confidence']}) "
                f"dest_strategy={dest_match['strategy']}({dest_match['confidence']})"
            )

        except Exception as exc:
            await db.rollback()
            # 记录失败状态
            try:
                async with AsyncSessionLocal() as err_db:
                    err_repo = CargoRepository(err_db)
                    raw = await err_repo.get_tms_raw_by_msg_id(message_id)
                    if raw:
                        await err_repo.update_tms_raw(
                            raw.id,
                            process_status="FAILED",
                            error_msg=str(exc)[:500],
                        )
                    await err_db.commit()
            except Exception:
                pass
            logger.error(
                f"[tms_consumer] 处理失败 message_id={message_id}: {exc}",
                exc_info=True,
            )


# ─────────────────────────────────────────────────
# RQ 消费者主循环（需配合 redis-py 或 rq 库使用）
# ─────────────────────────────────────────────────

async def consume_tms_cargo() -> None:
    """TMS货源消费者主循环

    说明：
    实际接入时需根据项目的 RQ/消息队列实现替换此函数。
    本实现为占位框架，展示消费者的完整数据处理流程。

    接入示例（使用 redis-py streams）：
        redis_client = await aioredis.from_url(settings.REDIS_URL)
        while True:
            messages = await redis_client.xread({RQ_TOPIC: "$"}, block=5000)
            for stream, msgs in messages:
                for msg_id, data in msgs:
                    await _process_tms_message(json.loads(data[b"payload"]))
    """
    logger.info(f"[tms_consumer] 启动，监听 topic={RQ_TOPIC}")
    try:
        from app.core.config import settings
        import aioredis

        redis = await aioredis.from_url(settings.REDIS_URL)
        last_id = "$"

        while True:
            try:
                messages = await redis.xread({RQ_TOPIC: last_id}, block=5000, count=10)
                for _stream, msgs in (messages or []):
                    for msg_id, data in msgs:
                        last_id = msg_id
                        try:
                            payload_bytes = data.get(b"payload") or data.get("payload", b"{}")
                            payload = json.loads(payload_bytes)
                            await _process_tms_message(payload)
                        except Exception as exc:
                            logger.error(
                                f"[tms_consumer] 消息处理异常 msg_id={msg_id}: {exc}",
                                exc_info=True,
                            )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"[tms_consumer] 消费循环异常: {exc}", exc_info=True)
                await asyncio.sleep(5)

    except ImportError:
        logger.warning(
            "[tms_consumer] aioredis 未安装，消费者未启动。"
            "请安装: pip install aioredis"
        )


if __name__ == "__main__":
    asyncio.run(consume_tms_cargo())
