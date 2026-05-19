"""业务编码序列初始化脚本。"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.common import CodeSequence


SEQUENCE_DEFINITIONS: list[dict[str, Any]] = [
    {
        "biz_code": "REGION_CODE",
        "biz_name": "区域编码",
        "target_table": "region",
        "target_column": "code",
        "prefix": "RG",
        "date_format": None,
        "separator": None,
        "current_value": 0,
        "value_length": 6,
        "step": 1,
        "reset_rule": "NONE",
        "is_enabled": True,
        "remark": "业务区域编码",
    },
    {
        "biz_code": "NODE_CODE",
        "biz_name": "运输节点编码",
        "target_table": "transport_node",
        "target_column": "code",
        "prefix": "ND",
        "date_format": None,
        "separator": None,
        "current_value": 0,
        "value_length": 6,
        "step": 1,
        "reset_rule": "NONE",
        "is_enabled": True,
        "remark": "运输节点编码",
    },
    {
        "biz_code": "NAV_CONSTRAINT_POINT_CODE",
        "biz_name": "通航约束点编码",
        "target_table": "navigation_constraint_point",
        "target_column": "code",
        "prefix": "NCP",
        "date_format": None,
        "separator": None,
        "current_value": 0,
        "value_length": 6,
        "step": 1,
        "reset_rule": "NONE",
        "is_enabled": True,
        "remark": "通航约束点编码",
    },
    {
        "biz_code": "ROUTE_CODE",
        "biz_name": "航线编码",
        "target_table": "shipping_route",
        "target_column": "code",
        "prefix": "RT",
        "date_format": None,
        "separator": None,
        "current_value": 0,
        "value_length": 6,
        "step": 1,
        "reset_rule": "NONE",
        "is_enabled": True,
        "remark": "航线编码",
    },
    {
        "biz_code": "ROUTE_PLAN_CODE",
        "biz_name": "航线方案编码",
        "target_table": "shipping_route_plan",
        "target_column": "plan_code",
        "prefix": "RP",
        "date_format": None,
        "separator": None,
        "current_value": 0,
        "value_length": 6,
        "step": 1,
        "reset_rule": "NONE",
        "is_enabled": True,
        "remark": "航线方案编码",
    },
    {
        "biz_code": "COMMODITY_STANDARD_CODE",
        "biz_name": "标准货品编码",
        "target_table": "commodity_standard",
        "target_column": "code",
        "prefix": "CS",
        "date_format": None,
        "separator": None,
        "current_value": 0,
        "value_length": 6,
        "step": 1,
        "reset_rule": "NONE",
        "is_enabled": True,
        "remark": "标准货品编码",
    },
    {
        "biz_code": "FREIGHT_NO",
        "biz_name": "正式货源单号",
        "target_table": "freight",
        "target_column": "freight_no",
        "prefix": "FR",
        "date_format": "yyyyMMdd",
        "separator": "-",
        "current_value": 0,
        "value_length": 6,
        "step": 1,
        "reset_rule": "DAY",
        "is_enabled": True,
        "remark": "正式货源单号",
    },
    {
        "biz_code": "FREIGHT_BATCH_NO",
        "biz_name": "微信语义解析批次号",
        "target_table": "freight_batch_task",
        "target_column": "batch_no",
        "prefix": "FBT",
        "date_format": "yyyyMMdd",
        "separator": "-",
        "current_value": 0,
        "value_length": 6,
        "step": 1,
        "reset_rule": "DAY",
        "is_enabled": True,
        "remark": "微信文本货源语义解析批次号",
    },
    {
        "biz_code": "FREIGHT_TMS_INBOUND_NO",
        "biz_name": "TMS 结构化入站记录号",
        "target_table": "freight_tms_inbound",
        "target_column": "inbound_no",
        "prefix": "FTI",
        "date_format": "yyyyMMdd",
        "separator": "-",
        "current_value": 0,
        "value_length": 6,
        "step": 1,
        "reset_rule": "DAY",
        "is_enabled": True,
        "remark": "TMS 运单入站幂等记录号",
    },
    {
        "biz_code": "FREIGHT_CLUE_NO",
        "biz_name": "货源线索号",
        "target_table": "freight_clue",
        "target_column": "clue_no",
        "prefix": "FCU",
        "date_format": "yyyyMMdd",
        "separator": "-",
        "current_value": 0,
        "value_length": 6,
        "step": 1,
        "reset_rule": "DAY",
        "is_enabled": True,
        "remark": "AI 原文切分线索号",
    },
    {
        "biz_code": "FREIGHT_CANDIDATE_NO",
        "biz_name": "候选货源号",
        "target_table": "freight_candidate",
        "target_column": "candidate_no",
        "prefix": "FCA",
        "date_format": "yyyyMMdd",
        "separator": "-",
        "current_value": 0,
        "value_length": 6,
        "step": 1,
        "reset_rule": "DAY",
        "is_enabled": True,
        "remark": "AI 候选货源号",
    },
    {
        "biz_code": "FREIGHT_NORMALIZATION_TASK_NO",
        "biz_name": "货源清洗任务号",
        "target_table": "freight_normalization_task",
        "target_column": "task_no",
        "prefix": "FNT",
        "date_format": "yyyyMMdd",
        "separator": "-",
        "current_value": 0,
        "value_length": 6,
        "step": 1,
        "reset_rule": "DAY",
        "is_enabled": True,
        "remark": "原文级正式货源清洗任务号",
    },
    {
        "biz_code": "AUDIT_TASK_NO",
        "biz_name": "审核任务号",
        "target_table": "audit_task",
        "target_column": "task_no",
        "prefix": "AT",
        "date_format": "yyyyMMdd",
        "separator": "-",
        "current_value": 0,
        "value_length": 6,
        "step": 1,
        "reset_rule": "DAY",
        "is_enabled": True,
        "remark": "审核任务号",
    },
    {
        "biz_code": "VESSEL_PROFILE_CODE",
        "biz_name": "船舶档案编码",
        "target_table": "vessel_profile",
        "target_column": "vessel_profile_code",
        "prefix": "VP",
        "date_format": None,
        "separator": None,
        "current_value": 0,
        "value_length": 6,
        "step": 1,
        "reset_rule": "NONE",
        "is_enabled": True,
        "remark": "船舶主数据档案编码",
    },
]


async def seed_code_sequences() -> None:
    async with AsyncSessionLocal() as session:
        for definition in SEQUENCE_DEFINITIONS:
            entity = await session.scalar(
                select(CodeSequence).where(CodeSequence.biz_code == definition["biz_code"])
            )
            if entity is None:
                session.add(CodeSequence(**definition))
                continue

            entity.biz_name = definition["biz_name"]
            entity.target_table = definition["target_table"]
            entity.target_column = definition["target_column"]
            entity.prefix = definition["prefix"]
            entity.date_format = definition["date_format"]
            entity.separator = definition["separator"]
            entity.value_length = definition["value_length"]
            entity.step = definition["step"]
            entity.reset_rule = definition["reset_rule"]
            entity.is_enabled = definition["is_enabled"]
            entity.remark = definition["remark"]
        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_code_sequences())
