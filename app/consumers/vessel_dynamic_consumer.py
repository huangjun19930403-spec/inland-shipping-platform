"""
船舶动态 Kafka 消费者
Topic: vessel.dynamic
消息体格式: VesselDynamicKafkaMessage (JSON)

启动方式（在 main.py 的 lifespan 中注册，或独立运行）:
    python -m app.consumers.vessel_dynamic_consumer
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.repositories.vessel_repository import VesselRepository
from app.repositories.audit_repository import AuditRepository
from app.schemas.vessel import VesselDynamicKafkaMessage
from app.services.audit_service import AuditService
from app.services.vessel_service import VesselService

logger = logging.getLogger(__name__)

KAFKA_TOPIC = "vessel.dynamic"
KAFKA_GROUP_ID = "inland-vessel-dynamic-group"


async def _process_message(msg_value: bytes) -> None:
    """解析并处理单条 Kafka 消息"""
    try:
        payload = json.loads(msg_value)
        msg = VesselDynamicKafkaMessage(**payload)
    except Exception as e:
        logger.warning("vessel.dynamic: 消息解析失败 — %s | raw=%s", e, msg_value[:200])
        return

    async with AsyncSessionLocal() as session:
        try:
            vessel_repo = VesselRepository(session)
            audit_svc = AuditService(audit_repo=AuditRepository(session))
            svc = VesselService(vessel_repo=vessel_repo, audit_svc=audit_svc)

            fields = msg.model_dump(exclude={"mmsi"}, exclude_none=True)
            await svc.update_dynamic_by_mmsi(mmsi=msg.mmsi, operator_id=None, **fields)
            await session.commit()
            logger.info("vessel.dynamic: 已更新 mmsi=%s", msg.mmsi)
        except Exception as e:
            await session.rollback()
            logger.error("vessel.dynamic: 处理消息失败 mmsi=%s — %s", msg.mmsi, e)


async def start_consumer(bootstrap_servers: str = None) -> None:
    """
    启动 Kafka 消费者，持续消费 vessel.dynamic Topic。
    需要安装 aiokafka: pip install aiokafka
    """
    try:
        from aiokafka import AIOKafkaConsumer
    except ImportError:
        logger.error("aiokafka 未安装，无法启动 Kafka 消费者。请运行: pip install aiokafka")
        return

    servers = bootstrap_servers or getattr(settings, "KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    consumer = AIOKafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=servers,
        group_id=KAFKA_GROUP_ID,
        auto_offset_reset="latest",
        enable_auto_commit=True,
        value_deserializer=lambda v: v,  # 原始 bytes，_process_message 内部 json.loads
    )

    logger.info("vessel.dynamic consumer 启动，broker=%s topic=%s", servers, KAFKA_TOPIC)
    await consumer.start()
    try:
        async for msg in consumer:
            await _process_message(msg.value)
    finally:
        await consumer.stop()
        logger.info("vessel.dynamic consumer 已停止")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(start_consumer())
