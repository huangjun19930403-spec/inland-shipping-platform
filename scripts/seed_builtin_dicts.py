"""内置标准字典初始化脚本（非 AI 正式库）。"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.dictionary import StdDict, StdDictItem


def _items(*codes: str) -> list[dict[str, Any]]:
    return [
        {
            "item_code": code,
            "item_name": code,
            "item_name_en": code,
            "is_default": False,
        }
        for code in codes
    ]


BUILTIN_DICTS: list[dict[str, Any]] = [
    {"dict_code": "NODE_TYPE", "dict_name": "节点类型", "items": _items("PORT", "TERMINAL", "ANCHORAGE", "LOCK", "LOGISTICS_PARK", "RAIL_STATION", "HIGHWAY_PORT", "INTERMODAL_HUB", "OTHER")},
    {"dict_code": "BUSINESS_CATEGORY", "dict_name": "业务类别", "items": _items("LOADING", "UNLOADING", "TRANSFER", "TRANSSHIPMENT", "STORAGE", "PASSAGE", "COMPREHENSIVE")},
    {"dict_code": "PACKAGING_FORM", "dict_name": "包装形式", "items": _items("BULK", "TON_BAG", "BAGGED", "BOXED", "CONTAINER", "GENERAL_CARGO")},
    {"dict_code": "HANDLING_MODE", "dict_name": "装卸方式", "items": _items("GRAB", "PIPELINE", "CONVEYOR", "CRANE", "MANUAL", "SELF_UNLOADING", "OTHER")},
    {"dict_code": "SHIP_TYPE", "dict_name": "船型", "items": _items("BULK_CARRIER", "SELF_UNLOADING_BULK", "GENERAL_CARGO_SHIP", "CONTAINER_SHIP", "CHEMICAL_TANKER", "OIL_TANKER", "MULTIPURPOSE", "BARGE", "TUG")},
    {"dict_code": "NAVIGATION_POWER_TYPE", "dict_name": "动力类型", "items": _items("SELF_PROPELLED", "NON_SELF_PROPELLED")},
    {"dict_code": "PARTY_RELATION_TYPE", "dict_name": "主体关系类型", "items": _items("OWNER", "OPERATOR", "MANAGER", "AGENT", "CARRIER")},
    {"dict_code": "CONTACT_ROLE", "dict_name": "联系人角色", "items": _items("CAPTAIN", "OWNER_CONTACT", "DISPATCH_CONTACT", "SETTLEMENT_CONTACT", "EMERGENCY_CONTACT", "FREIGHT_CONTACT")},
    {"dict_code": "CERTIFICATE_TYPE", "dict_name": "证件类型", "items": _items("TRANSPORT_LICENSE", "OWNERSHIP_CERT", "INSPECTION_CERT", "SEAWORTHINESS_CERT", "AIS_CERT", "CREW_CERT", "OTHER")},
    {"dict_code": "BOUNDARY_SOURCE_TYPE", "dict_name": "边界来源类型", "items": _items("OFFICIAL_GIS_SERVICE", "STANDARD_MAP_EXTRACTION", "PLATFORM_DEFINED", "THIRD_PARTY_AUTHORIZED")},
    {"dict_code": "REGION_TYPE", "dict_name": "区域类型", "items": _items("SHIPPING_ANALYSIS_REGION", "OPERATION_REGION", "MARKET_REGION")},
    {"dict_code": "REGION_RELATION_TYPE", "dict_name": "区域关系类型", "items": _items("INCLUDED", "PRIMARY", "ASSIST")},
    {"dict_code": "TRANSPORT_MODE_ELEMENT", "dict_name": "运输方式要素", "items": _items("WATER", "ROAD", "RAIL", "MANUAL", "UNKNOWN")},
    {"dict_code": "TRANSPORT_ORG_TYPE", "dict_name": "运输组织类型", "items": _items("SINGLE_MODE", "MULTIMODAL")},
    {"dict_code": "MULTIMODAL_COMBINATION", "dict_name": "联运组合", "items": _items("WATER_ROAD", "WATER_RAIL", "ROAD_RAIL", "WATER_ROAD_RAIL")},
    {"dict_code": "ROUTE_PLAN_TYPE", "dict_name": "路线方案类型", "items": _items("STANDARD", "SEASONAL", "EMERGENCY")},
    {"dict_code": "ROUTE_PLAN_NODE_KIND", "dict_name": "路径节点类型", "items": _items("REGION_ANCHOR", "TRANSPORT_NODE", "CONSTRAINT_POINT", "MANUAL_POINT")},
    {"dict_code": "ROUTE_PLAN_NODE_ROLE", "dict_name": "路径节点角色", "items": _items("START", "PASS", "TRANSFER", "END")},
    {"dict_code": "ROUTE_STATUS", "dict_name": "航线状态", "items": _items("DRAFT", "ACTIVE", "INACTIVE")},
    {"dict_code": "ROUTE_PLAN_SEGMENT_TYPE", "dict_name": "路线分段类型", "items": _items("NAVIGATION_SEGMENT", "TRANSFER_SEGMENT", "PASSAGE_SEGMENT")},
    {"dict_code": "ROUTE_SEGMENT_POINT_TYPE", "dict_name": "分段点位类型", "items": _items("NODE", "CONSTRAINT_POINT", "LOCK", "SERVICE_POINT")},
    {"dict_code": "NAVIGATION_CONSTRAINT_TYPE", "dict_name": "通航约束类型", "items": _items("LOCK", "BRIDGE", "SHALLOW", "RESTRICTED_AREA", "FORBIDDEN_AREA", "DRAFT_LIMIT", "WIDTH_LIMIT", "HEIGHT_LIMIT", "LOW_BRIDGE", "PASSAGE_RESTRICTION")},
    {"dict_code": "SOURCE_TYPE", "dict_name": "来源类型", "items": _items("MANUAL", "IMPORT", "TMS", "WECHAT", "SYSTEM")},
    {"dict_code": "SOURCE_CHANNEL", "dict_name": "来源渠道", "items": _items("MANUAL_FORM", "IMPORT_FILE", "TMS_API", "WECHAT_TEXT", "SYSTEM_SYNC")},
    {"dict_code": "PROVIDER_CODE", "dict_name": "提供方编码", "items": _items("AMAP", "HIFLEET")},
    {"dict_code": "FREIGHT_STATUS", "dict_name": "货源状态", "items": _items("DRAFT", "PUBLISHED", "MATCHING", "EXPIRED", "CLOSED")},
    {"dict_code": "FREIGHT_TAG", "dict_name": "货源标签", "items": _items("URGENT", "HIGH_VALUE", "FIXED_ROUTE", "LONG_TERM")},
    {"dict_code": "DATA_SCOPE_TYPE", "dict_name": "数据权限类型", "items": _items("ALL_DATA", "REGION_DATA", "CITY_DATA", "NODE_DATA", "SELF_DATA")},
    {"dict_code": "USER_STATUS", "dict_name": "用户状态", "items": _items("ACTIVE", "DISABLED", "LOCKED")},
    {"dict_code": "AUDIT_STATUS", "dict_name": "审核状态", "items": _items("PENDING", "APPROVED", "REJECTED")},
    {"dict_code": "CERTIFICATE_STATUS", "dict_name": "证件状态", "items": _items("VALID", "EXPIRING", "EXPIRED", "INVALID")},
    {"dict_code": "VERIFY_STATUS", "dict_name": "校验状态", "items": _items("UNVERIFIED", "VERIFIED", "FAILED")},
    {"dict_code": "FILE_STORAGE_PROVIDER", "dict_name": "文件存储提供方", "items": _items("TENCENT_COS", "MINIO", "LOCAL")},
    {"dict_code": "LOGIN_RESULT", "dict_name": "登录结果", "items": _items("SUCCESS", "FAILED", "LOGOUT")},
    {"dict_code": "PROFILE_STATUS", "dict_name": "档案状态", "items": _items("ACTIVE", "INACTIVE", "ARCHIVED")},
    {"dict_code": "STAT_JOB_STATUS", "dict_name": "统计任务状态", "items": _items("RUNNING", "SUCCESS", "FAILED")},
    {"dict_code": "VALUE_TYPE", "dict_name": "值类型", "items": _items("STRING", "NUMBER", "BOOLEAN", "JSON", "DATE", "DATETIME")},
    {"dict_code": "CONFIG_GROUP", "dict_name": "配置分组", "items": _items("SYSTEM", "MAP", "FREIGHT", "SHIP", "ANALYSIS")},
]


async def seed_builtin_dicts() -> None:
    async with AsyncSessionLocal() as session:
        for dict_payload in BUILTIN_DICTS:
            dict_code = dict_payload["dict_code"]
            dictionary = await session.scalar(select(StdDict).where(StdDict.dict_code == dict_code))
            if dictionary is None:
                dictionary = StdDict(
                    dict_code=dict_code,
                    dict_name=dict_payload["dict_name"],
                    dict_name_en=dict_payload.get("dict_name_en"),
                    description=dict_payload.get("description"),
                    is_system=True,
                    status=1,
                    sort_order=dict_payload.get("sort_order", 0),
                )
                session.add(dictionary)
                await session.flush()

            for item in dict_payload.get("items", []):
                existed_item = await session.scalar(
                    select(StdDictItem).where(
                        StdDictItem.dict_id == dictionary.id,
                        StdDictItem.item_code == item["item_code"],
                    )
                )
                if existed_item is not None:
                    continue
                session.add(
                    StdDictItem(
                        dict_id=dictionary.id,
                        item_code=item["item_code"],
                        item_name=item["item_name"],
                        item_name_en=item.get("item_name_en"),
                        item_value=item.get("item_value"),
                        description=item.get("description"),
                        is_default=bool(item.get("is_default", False)),
                        is_system=True,
                        status=1,
                        sort_order=item.get("sort_order", 0),
                    )
                )

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_builtin_dicts())
