"""基础数据本地验证样例 seed。

本脚本只补齐第一轮重构需要的真实感基础数据：业务区域、运输节点、
节点别名/能力；标准货品由 seed_commodity_standards.py 统一维护。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.address import (
    AdminRegion,
    NodeAlias,
    Region,
    RegionBoundaryVersion,
    RegionCityRelation,
    TransportNode,
    TransportNodeBusinessCategory,
    TransportNodeContact,
    TransportNodeHandlingMode,
    TransportNodePackagingForm,
    TransportNodeProfile,
)
from app.models.commodity import CommodityCategory, CommodityType


REGION_SEEDS: list[dict[str, Any]] = [
    {
        "code": "REGION_YANGTZE_DELTA",
        "name": "长三角内河集疏运区",
        "short_name": "长三角",
        "description": "覆盖苏南、浙北、上海周边和长江下游港口群。",
        "cities": ["南京市", "镇江市", "扬州市", "泰州市", "苏州市", "无锡市", "常州市", "南通市", "杭州市", "湖州市", "嘉兴市"],
        "bbox": [118.25, 29.70, 122.10, 33.20],
    },
    {
        "code": "REGION_WANJIANG",
        "name": "皖江矿建材料走廊",
        "short_name": "皖江",
        "description": "覆盖芜湖、马鞍山、铜陵、安庆等长江安徽段港口与矿建材料节点。",
        "cities": ["芜湖市", "马鞍山市", "铜陵市", "安庆市"],
        "bbox": [116.30, 29.35, 119.05, 32.20],
    },
    {
        "code": "REGION_MIDDLE_YANGTZE",
        "name": "长江中游煤砂粮流通区",
        "short_name": "长江中游",
        "description": "覆盖武汉、黄石、荆州、岳阳、九江等中游港口。",
        "cities": ["武汉市", "黄石市", "荆州市", "岳阳市", "九江市"],
        "bbox": [112.00, 28.20, 116.35, 31.60],
    },
    {
        "code": "REGION_UPPER_YANGTZE",
        "name": "川渝长江上游通道",
        "short_name": "川渝上游",
        "description": "覆盖宜宾、泸州等上游港口，本地样例用于上游货源和节点验证。",
        "cities": ["宜宾市", "泸州市"],
        "bbox": [104.00, 27.70, 106.35, 29.55],
    },
    {
        "code": "REGION_PEARL_RIVER",
        "name": "珠江三角洲水网区",
        "short_name": "珠三角",
        "description": "覆盖广州、佛山、肇庆等珠江水网港口与制造业节点。",
        "cities": ["广州市", "佛山市", "肇庆市"],
        "bbox": [112.10, 22.55, 114.15, 23.75],
    },
    {
        "code": "REGION_CANAL_JIANGNAN",
        "name": "江南运河节点带",
        "short_name": "江南运河",
        "description": "覆盖苏锡常杭湖嘉等运河沿线装卸点和内河码头。",
        "cities": ["苏州市", "无锡市", "常州市", "杭州市", "湖州市", "嘉兴市"],
        "bbox": [119.20, 29.95, 121.45, 31.85],
    },
    {
        "code": "REGION_LOWER_YANGTZE_PORTS",
        "name": "长江下游港口群",
        "short_name": "长江下游",
        "description": "覆盖南京、镇江、扬州、泰州、南通等长江下游港口节点。",
        "cities": ["南京市", "镇江市", "扬州市", "泰州市", "南通市"],
        "bbox": [118.20, 31.45, 121.10, 33.00],
    },
    {
        "code": "REGION_EAST_CHINA_BULK",
        "name": "华东散货集散区",
        "short_name": "华东散货",
        "description": "覆盖华东砂石、煤炭、钢材、水泥熟料等散货主要集散节点。",
        "cities": ["南京市", "苏州市", "无锡市", "芜湖市", "马鞍山市", "铜陵市", "湖州市", "嘉兴市"],
        "bbox": [117.80, 29.80, 121.90, 32.60],
    },
]


NODE_SEEDS: list[dict[str, Any]] = [
    {"code": "NODE_NJ_LONGTAN_PORT", "name": "南京龙潭港", "short": "龙潭港", "type": "PORT", "city": "南京市", "lng": "118.9212", "lat": "32.1668", "address": "南京市栖霞区龙潭港区", "aliases": ["龙潭港", "南京龙潭", "龙潭码头"], "categories": ["LOADING", "UNLOADING", "TRANSFER"], "packaging": ["BULK", "CONTAINER", "GENERAL_CARGO"], "handling": ["GRAB", "CRANE", "CONVEYOR"], "berths": 18, "draft": "9.50"},
    {"code": "NODE_NJ_XINSHENGWEI_PORT", "name": "南京新生圩港", "short": "新生圩", "type": "TERMINAL", "city": "南京市", "lng": "118.8367", "lat": "32.1352", "address": "南京市栖霞区新生圩港区", "aliases": ["新生圩", "南京新生圩"], "categories": ["LOADING", "UNLOADING"], "packaging": ["BULK", "GENERAL_CARGO"], "handling": ["GRAB", "CRANE"], "berths": 12, "draft": "8.80"},
    {"code": "NODE_ZJ_DAGANG_PORT", "name": "镇江大港港区", "short": "镇江大港", "type": "PORT", "city": "镇江市", "lng": "119.6626", "lat": "32.1965", "address": "镇江市新区大港港区", "aliases": ["大港港区", "镇江大港"], "categories": ["LOADING", "UNLOADING", "TRANSFER"], "packaging": ["BULK", "GENERAL_CARGO"], "handling": ["GRAB", "CRANE", "CONVEYOR"], "berths": 16, "draft": "10.20"},
    {"code": "NODE_ZJ_JIANBI_TERMINAL", "name": "镇江谏壁作业区", "short": "谏壁", "type": "TERMINAL", "city": "镇江市", "lng": "119.5818", "lat": "32.1914", "address": "镇江市京口区谏壁作业区", "aliases": ["谏壁码头", "谏壁作业区"], "categories": ["LOADING", "UNLOADING"], "packaging": ["BULK"], "handling": ["GRAB", "CONVEYOR"], "berths": 8, "draft": "7.60"},
    {"code": "NODE_YZ_LIUWEI_PORT", "name": "扬州六圩港区", "short": "六圩港", "type": "PORT", "city": "扬州市", "lng": "119.5182", "lat": "32.3036", "address": "扬州市广陵区六圩港区", "aliases": ["六圩", "扬州六圩"], "categories": ["LOADING", "UNLOADING", "STORAGE"], "packaging": ["BULK", "GENERAL_CARGO"], "handling": ["GRAB", "CRANE"], "berths": 10, "draft": "6.80"},
    {"code": "NODE_TZ_GAOGANG_TERMINAL", "name": "泰州高港码头", "short": "高港", "type": "TERMINAL", "city": "泰州市", "lng": "119.8815", "lat": "32.3183", "address": "泰州市高港区沿江作业区", "aliases": ["高港码头", "泰州高港"], "categories": ["LOADING", "UNLOADING"], "packaging": ["BULK", "TON_BAG"], "handling": ["GRAB", "CRANE"], "berths": 9, "draft": "7.20"},
    {"code": "NODE_SUZHOU_TAICANG_PORT", "name": "苏州太仓港", "short": "太仓港", "type": "PORT", "city": "苏州市", "lng": "121.2013", "lat": "31.6765", "address": "苏州市太仓市港区", "aliases": ["太仓港", "苏州太仓"], "categories": ["LOADING", "UNLOADING", "TRANSFER"], "packaging": ["BULK", "CONTAINER", "GENERAL_CARGO"], "handling": ["GRAB", "CRANE", "CONVEYOR"], "berths": 22, "draft": "10.50"},
    {"code": "NODE_SUZHOU_ZJG_PORT", "name": "张家港港", "short": "张家港", "type": "PORT", "city": "苏州市", "lng": "120.5565", "lat": "31.9482", "address": "苏州市张家港市港区", "aliases": ["张家港", "张港"], "categories": ["LOADING", "UNLOADING", "TRANSFER"], "packaging": ["BULK", "GENERAL_CARGO"], "handling": ["GRAB", "CRANE"], "berths": 20, "draft": "10.00"},
    {"code": "NODE_SUZHOU_CHANGSHU_PORT", "name": "常熟港", "short": "常熟港", "type": "PORT", "city": "苏州市", "lng": "120.9818", "lat": "31.7496", "address": "苏州市常熟港区", "aliases": ["常熟港", "常熟码头"], "categories": ["LOADING", "UNLOADING"], "packaging": ["BULK", "GENERAL_CARGO"], "handling": ["GRAB", "CRANE"], "berths": 14, "draft": "8.80"},
    {"code": "NODE_WX_JIANGYIN_PORT", "name": "江阴港", "short": "江阴港", "type": "PORT", "city": "无锡市", "lng": "120.2904", "lat": "31.9327", "address": "无锡市江阴港区", "aliases": ["江阴港", "无锡江阴"], "categories": ["LOADING", "UNLOADING", "TRANSFER"], "packaging": ["BULK", "GENERAL_CARGO"], "handling": ["GRAB", "CRANE", "CONVEYOR"], "berths": 18, "draft": "9.60"},
    {"code": "NODE_CZ_BENNIU_PORT", "name": "常州奔牛港", "short": "奔牛港", "type": "TERMINAL", "city": "常州市", "lng": "119.8254", "lat": "31.9066", "address": "常州市新北区奔牛作业区", "aliases": ["奔牛港", "奔牛码头"], "categories": ["LOADING", "UNLOADING"], "packaging": ["BULK", "TON_BAG"], "handling": ["GRAB", "CRANE"], "berths": 6, "draft": "5.80"},
    {"code": "NODE_NT_RUGAO_PORT", "name": "南通如皋港", "short": "如皋港", "type": "PORT", "city": "南通市", "lng": "120.5906", "lat": "32.0322", "address": "南通市如皋港区", "aliases": ["如皋港", "南通如皋"], "categories": ["LOADING", "UNLOADING"], "packaging": ["BULK", "GENERAL_CARGO"], "handling": ["GRAB", "CRANE"], "berths": 12, "draft": "8.50"},
    {"code": "NODE_HZ_QIANTANG_PORT", "name": "杭州钱塘港", "short": "钱塘港", "type": "PORT", "city": "杭州市", "lng": "120.3450", "lat": "30.2954", "address": "杭州市钱塘港区", "aliases": ["钱塘港", "杭州钱塘"], "categories": ["LOADING", "UNLOADING"], "packaging": ["BULK", "CONTAINER"], "handling": ["CRANE", "GRAB"], "berths": 10, "draft": "5.50"},
    {"code": "NODE_HUZHOU_CHANGXING_PORT", "name": "湖州长兴港", "short": "长兴港", "type": "TERMINAL", "city": "湖州市", "lng": "119.9338", "lat": "31.0265", "address": "湖州市长兴县综合港区", "aliases": ["长兴港", "湖州长兴"], "categories": ["LOADING", "UNLOADING"], "packaging": ["BULK", "TON_BAG"], "handling": ["GRAB", "CONVEYOR"], "berths": 7, "draft": "5.20"},
    {"code": "NODE_JX_JIAXING_INLAND_PORT", "name": "嘉兴内河港", "short": "嘉兴港", "type": "PORT", "city": "嘉兴市", "lng": "120.7555", "lat": "30.7472", "address": "嘉兴市内河港区", "aliases": ["嘉兴内河港", "嘉兴港"], "categories": ["LOADING", "UNLOADING", "TRANSFER"], "packaging": ["BULK", "CONTAINER"], "handling": ["CRANE", "GRAB"], "berths": 11, "draft": "5.40"},
    {"code": "NODE_NB_ZHENHAI_PORT", "name": "宁波镇海港区", "short": "镇海港", "type": "PORT", "city": "宁波市", "lng": "121.7041", "lat": "29.9642", "address": "宁波市镇海港区", "aliases": ["镇海港", "宁波镇海"], "categories": ["LOADING", "UNLOADING", "TRANSFER"], "packaging": ["BULK", "CONTAINER", "GENERAL_CARGO"], "handling": ["CRANE", "GRAB"], "berths": 18, "draft": "10.80"},
    {"code": "NODE_WUHU_ZHUJIAQIAO_PORT", "name": "芜湖朱家桥港区", "short": "朱家桥", "type": "PORT", "city": "芜湖市", "lng": "118.3893", "lat": "31.3787", "address": "芜湖市朱家桥港区", "aliases": ["朱家桥港", "芜湖朱家桥"], "categories": ["LOADING", "UNLOADING"], "packaging": ["BULK", "GENERAL_CARGO"], "handling": ["GRAB", "CRANE"], "berths": 13, "draft": "8.60"},
    {"code": "NODE_MAS_CIHU_PORT", "name": "马鞍山慈湖港", "short": "慈湖港", "type": "TERMINAL", "city": "马鞍山市", "lng": "118.5237", "lat": "31.7260", "address": "马鞍山市慈湖港区", "aliases": ["慈湖港", "马鞍山慈湖"], "categories": ["LOADING", "UNLOADING"], "packaging": ["BULK"], "handling": ["GRAB", "CONVEYOR"], "berths": 8, "draft": "8.20"},
    {"code": "NODE_TONGLING_HENGGANG_PORT", "name": "铜陵横港港区", "short": "横港", "type": "PORT", "city": "铜陵市", "lng": "117.8083", "lat": "30.9452", "address": "铜陵市横港港区", "aliases": ["横港", "铜陵横港"], "categories": ["LOADING", "UNLOADING"], "packaging": ["BULK", "TON_BAG"], "handling": ["GRAB", "CRANE"], "berths": 9, "draft": "7.80"},
    {"code": "NODE_AQ_SHIMENHU_PORT", "name": "安庆石门湖港区", "short": "石门湖", "type": "PORT", "city": "安庆市", "lng": "117.1151", "lat": "30.5386", "address": "安庆市石门湖港区", "aliases": ["石门湖港", "安庆石门湖"], "categories": ["LOADING", "UNLOADING"], "packaging": ["BULK", "GENERAL_CARGO"], "handling": ["GRAB", "CRANE"], "berths": 8, "draft": "7.50"},
    {"code": "NODE_WH_YANGLUO_PORT", "name": "武汉阳逻港", "short": "阳逻港", "type": "PORT", "city": "武汉市", "lng": "114.5681", "lat": "30.6825", "address": "武汉市新洲区阳逻港区", "aliases": ["阳逻港", "武汉阳逻"], "categories": ["LOADING", "UNLOADING", "TRANSFER"], "packaging": ["BULK", "CONTAINER"], "handling": ["CRANE", "GRAB"], "berths": 20, "draft": "9.20"},
    {"code": "NODE_WH_BAIXUSHAN_PORT", "name": "武汉白浒山港", "short": "白浒山", "type": "TERMINAL", "city": "武汉市", "lng": "114.5068", "lat": "30.6009", "address": "武汉市青山区白浒山作业区", "aliases": ["白浒山", "武汉白浒山"], "categories": ["LOADING", "UNLOADING"], "packaging": ["BULK"], "handling": ["GRAB", "CONVEYOR"], "berths": 10, "draft": "7.80"},
    {"code": "NODE_HS_XINGANG_PORT", "name": "黄石新港", "short": "黄石新港", "type": "PORT", "city": "黄石市", "lng": "115.0379", "lat": "30.2054", "address": "黄石市新港园区", "aliases": ["黄石新港", "新港园区"], "categories": ["LOADING", "UNLOADING"], "packaging": ["BULK", "GENERAL_CARGO"], "handling": ["GRAB", "CRANE"], "berths": 14, "draft": "8.30"},
    {"code": "NODE_YC_YUNCHI_PORT", "name": "宜昌云池港", "short": "云池港", "type": "PORT", "city": "宜昌市", "lng": "111.4742", "lat": "30.5085", "address": "宜昌市猇亭区云池港区", "aliases": ["云池港", "宜昌云池"], "categories": ["LOADING", "UNLOADING", "TRANSFER"], "packaging": ["BULK", "CONTAINER"], "handling": ["CRANE", "GRAB"], "berths": 12, "draft": "8.60"},
    {"code": "NODE_JZ_YANKA_PORT", "name": "荆州盐卡港", "short": "盐卡港", "type": "PORT", "city": "荆州市", "lng": "112.2475", "lat": "30.3353", "address": "荆州市沙市区盐卡港区", "aliases": ["盐卡港", "荆州盐卡"], "categories": ["LOADING", "UNLOADING"], "packaging": ["BULK", "CONTAINER"], "handling": ["CRANE", "GRAB"], "berths": 10, "draft": "7.20"},
    {"code": "NODE_YY_CHENGLINGJI_PORT", "name": "岳阳城陵矶港", "short": "城陵矶", "type": "PORT", "city": "岳阳市", "lng": "113.1645", "lat": "29.4442", "address": "岳阳市城陵矶港区", "aliases": ["城陵矶", "岳阳城陵矶"], "categories": ["LOADING", "UNLOADING", "TRANSFER"], "packaging": ["BULK", "CONTAINER"], "handling": ["CRANE", "GRAB"], "berths": 18, "draft": "8.80"},
    {"code": "NODE_JJ_CHENGXI_PORT", "name": "九江城西港", "short": "城西港", "type": "PORT", "city": "九江市", "lng": "115.8529", "lat": "29.7269", "address": "九江市城西港区", "aliases": ["城西港", "九江城西"], "categories": ["LOADING", "UNLOADING"], "packaging": ["BULK", "CONTAINER"], "handling": ["CRANE", "GRAB"], "berths": 12, "draft": "8.00"},
    {"code": "NODE_YB_ZHIJIANG_PORT", "name": "宜宾志城作业区", "short": "志城", "type": "TERMINAL", "city": "宜宾市", "lng": "104.6108", "lat": "28.7801", "address": "宜宾市三江新区志城作业区", "aliases": ["志城港", "宜宾志城"], "categories": ["LOADING", "UNLOADING"], "packaging": ["BULK", "GENERAL_CARGO"], "handling": ["GRAB", "CRANE"], "berths": 6, "draft": "5.80"},
    {"code": "NODE_LZ_LANTIAN_PORT", "name": "泸州蓝田港", "short": "蓝田港", "type": "PORT", "city": "泸州市", "lng": "105.4498", "lat": "28.8813", "address": "泸州市蓝田港区", "aliases": ["蓝田港", "泸州蓝田"], "categories": ["LOADING", "UNLOADING"], "packaging": ["BULK", "CONTAINER"], "handling": ["CRANE", "GRAB"], "berths": 10, "draft": "6.40"},
    {"code": "NODE_GZ_XINSHA_PORT", "name": "广州新沙港", "short": "新沙港", "type": "PORT", "city": "广州市", "lng": "113.6104", "lat": "23.0778", "address": "广州市增城区新沙港区", "aliases": ["新沙港", "广州新沙"], "categories": ["LOADING", "UNLOADING", "TRANSFER"], "packaging": ["BULK", "CONTAINER"], "handling": ["CRANE", "GRAB"], "berths": 16, "draft": "9.80"},
    {"code": "NODE_FS_SANSHUI_PORT", "name": "佛山三水港", "short": "三水港", "type": "PORT", "city": "佛山市", "lng": "112.8793", "lat": "23.1736", "address": "佛山市三水港区", "aliases": ["三水港", "佛山三水"], "categories": ["LOADING", "UNLOADING"], "packaging": ["BULK", "GENERAL_CARGO"], "handling": ["GRAB", "CRANE"], "berths": 9, "draft": "5.60"},
    {"code": "NODE_ZQ_XINGANG_PORT", "name": "肇庆新港", "short": "肇庆新港", "type": "PORT", "city": "肇庆市", "lng": "112.5130", "lat": "23.0603", "address": "肇庆市新港作业区", "aliases": ["肇庆新港", "肇庆港"], "categories": ["LOADING", "UNLOADING"], "packaging": ["BULK", "GENERAL_CARGO"], "handling": ["GRAB", "CRANE"], "berths": 8, "draft": "5.40"},
]


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _rect_geometry(bbox: list[float]) -> dict[str, Any]:
    min_lng, min_lat, max_lng, max_lat = bbox
    return {
        "type": "Polygon",
        "coordinates": [[
            [min_lng, min_lat],
            [max_lng, min_lat],
            [max_lng, max_lat],
            [min_lng, max_lat],
            [min_lng, min_lat],
        ]],
    }


async def _city_map(session) -> dict[str, AdminRegion]:
    names = sorted({name for row in REGION_SEEDS for name in row["cities"]} | {row["city"] for row in NODE_SEEDS})
    result = await session.execute(select(AdminRegion).where(AdminRegion.name.in_(names), AdminRegion.level == 2))
    return {row.name: row for row in result.scalars().all()}


async def _upsert_region(session, seed: dict[str, Any], cities: dict[str, AdminRegion]) -> Region:
    row = await session.scalar(select(Region).where(Region.code == seed["code"]))
    payload = {
        "code": seed["code"],
        "name": seed["name"],
        "short_name": seed["short_name"],
        "region_type_code": "SHIPPING_ANALYSIS_REGION",
        "description": seed["description"],
        "sort_order": REGION_SEEDS.index(seed) + 1,
        "status": 1,
    }
    if row is None:
        row = Region(**payload)
        session.add(row)
    else:
        for key, value in payload.items():
            setattr(row, key, value)
        row.deleted_at = None
    row.audit_status = "APPROVED"
    await session.flush()

    boundary = await session.scalar(
        select(RegionBoundaryVersion).where(RegionBoundaryVersion.region_id == row.id, RegionBoundaryVersion.version_no == 1)
    )
    geometry = _rect_geometry(seed["bbox"])
    min_lng, min_lat, max_lng, max_lat = seed["bbox"]
    boundary_payload = {
        "boundary_source_type_code": "PLATFORM_DEFINED",
        "geometry_json": geometry,
        "center_longitude": _decimal((min_lng + max_lng) / 2),
        "center_latitude": _decimal((min_lat + max_lat) / 2),
        "area_km2": _decimal(0),
        "is_current": True,
        "remark": "本地验证预制业务区域边界，非生产测绘边界。",
    }
    if boundary is None:
        boundary = RegionBoundaryVersion(region_id=row.id, version_no=1, **boundary_payload)
        session.add(boundary)
    else:
        for key, value in boundary_payload.items():
            setattr(boundary, key, value)
    await session.flush()
    row.current_boundary_version_id = boundary.id

    await session.execute(delete(RegionCityRelation).where(RegionCityRelation.region_id == row.id))
    for index, city_name in enumerate(seed["cities"], start=1):
        city = cities.get(city_name)
        if city is None:
            continue
        session.add(
            RegionCityRelation(
                region_id=row.id,
                city_region_id=city.id,
                relation_type_code="INCLUDED",
                is_primary=index == 1,
                sort_order=index,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )
    await session.flush()
    return row


async def _replace_node_codes(session, node: TransportNode, seed: dict[str, Any]) -> None:
    now = datetime.utcnow()
    relation_sets = [
        (TransportNodeBusinessCategory, "business_category_code", seed["categories"]),
        (TransportNodePackagingForm, "packaging_form_code", seed["packaging"]),
        (TransportNodeHandlingMode, "handling_mode_code", seed["handling"]),
    ]
    for model, code_field, codes in relation_sets:
        await session.execute(delete(model).where(model.node_id == node.id))
        for code in codes:
            session.add(model(node_id=node.id, **{code_field: code}, created_at=now))


async def _upsert_node(session, seed: dict[str, Any], cities: dict[str, AdminRegion], sort_order: int) -> None:
    city = cities.get(seed["city"])
    if city is None:
        return
    row = await session.scalar(select(TransportNode).where(TransportNode.code == seed["code"]))
    payload = {
        "code": seed["code"],
        "name": seed["name"],
        "short_name": seed["short"],
        "node_type_code": seed["type"],
        "province_code": city.province_code or city.code[:2] + "0000",
        "city_code": city.code,
        "district_code": None,
        "city_region_id": city.id,
        "address": seed["address"],
        "longitude": _decimal(seed["lng"]),
        "latitude": _decimal(seed["lat"]),
        "status": 1,
        "lifecycle_status_code": "ACTIVE",
        "sort_order": sort_order,
        "is_hot_node": sort_order <= 16,
    }
    if row is None:
        row = TransportNode(**payload)
        session.add(row)
    else:
        for key, value in payload.items():
            setattr(row, key, value)
        row.deleted_at = None
    row.audit_status = "APPROVED"
    await session.flush()

    profile = await session.scalar(select(TransportNodeProfile).where(TransportNodeProfile.node_id == row.id))
    profile_payload = {
        "business_nature_code": "PUBLIC_TERMINAL",
        "channel_depth_m": _decimal(seed.get("draft", "6.00")) + _decimal("1.20"),
        "max_draft_m": _decimal(seed.get("draft", "6.00")),
        "berth_count": int(seed.get("berths", 6)),
        "annual_throughput_ton": _decimal(seed.get("berths", 6)) * _decimal("450000"),
        "open_hours_desc": "全天候作业，夜间靠泊需提前预约",
        "ext_json": {"seed_note": "本地验证样例", "supported_commodities": ["砂石", "煤炭", "钢材", "粮食"]},
        "updated_at": datetime.utcnow(),
    }
    if profile is None:
        session.add(TransportNodeProfile(node_id=row.id, **profile_payload))
    else:
        for key, value in profile_payload.items():
            setattr(profile, key, value)

    await session.execute(delete(NodeAlias).where(NodeAlias.node_id == row.id))
    for index, alias in enumerate(seed["aliases"]):
        session.add(
            NodeAlias(
                node_id=row.id,
                alias_name=alias,
                alias_type_code="COMMON_ALIAS",
                source_type_code="SYSTEM",
                is_primary=index == 0,
            )
        )

    await session.execute(delete(TransportNodeContact).where(TransportNodeContact.node_id == row.id))
    contact_suffix = f"{sort_order:08d}"[-8:]
    session.add_all(
        [
            TransportNodeContact(
                node_id=row.id,
                contact_name="港航调度",
                contact_type_code="OPERATIONS",
                mobile_phone="025-88000000",
                wechat=None,
                email=None,
                is_primary=True,
                remark="本地验证样例主联系人",
            ),
            TransportNodeContact(
                node_id=row.id,
                contact_name="商务值班",
                contact_type_code="BUSINESS",
                mobile_phone=f"13{sort_order % 10}{contact_suffix}"[:11],
                wechat=None,
                email=None,
                is_primary=False,
                remark="本地验证样例商务联系人",
            ),
        ]
    )
    await _replace_node_codes(session, row, seed)


def _supplemental_node_seeds(cities: dict[str, AdminRegion]) -> list[dict[str, Any]]:
    seeds: list[dict[str, Any]] = []
    for city_name, city in sorted(cities.items(), key=lambda item: item[1].code):
        base_name = city_name.removesuffix("市")
        lng = _decimal(city.longitude or 118) if city.longitude is not None else _decimal(118)
        lat = _decimal(city.latitude or 31) if city.latitude is not None else _decimal(31)
        city_code = city.code
        seeds.extend(
            [
                {
                    "code": f"NODE_{city_code}_GRAIN_TRANSFER",
                    "name": f"{base_name}粮食中转码头",
                    "short": "粮食中转",
                    "type": "TERMINAL",
                    "city": city_name,
                    "lng": str(lng + _decimal("0.035")),
                    "lat": str(lat + _decimal("0.018")),
                    "address": f"{city_name}内河粮食物流作业区",
                    "aliases": [f"{base_name}粮食码头", f"{base_name}粮食中转点"],
                    "categories": ["LOADING", "UNLOADING", "STORAGE"],
                    "packaging": ["BULK", "BAGGED"],
                    "handling": ["GRAB", "CONVEYOR", "CRANE"],
                    "berths": 4,
                    "draft": "4.80",
                },
                {
                    "code": f"NODE_{city_code}_AGGREGATE_YARD",
                    "name": f"{base_name}砂石装卸点",
                    "short": "砂石装卸",
                    "type": "TERMINAL",
                    "city": city_name,
                    "lng": str(lng - _decimal("0.028")),
                    "lat": str(lat - _decimal("0.015")),
                    "address": f"{city_name}内河砂石集散作业区",
                    "aliases": [f"{base_name}砂石码头", f"{base_name}骨料装卸点"],
                    "categories": ["LOADING", "UNLOADING"],
                    "packaging": ["BULK"],
                    "handling": ["GRAB", "CONVEYOR"],
                    "berths": 5,
                    "draft": "5.20",
                },
            ]
        )
    return seeds


async def seed_foundation_samples() -> None:
    async with AsyncSessionLocal() as session:
        cities = await _city_map(session)
        for seed in REGION_SEEDS:
            await _upsert_region(session, seed, cities)
        all_node_seeds = [*NODE_SEEDS, *_supplemental_node_seeds(cities)]
        for index, seed in enumerate(all_node_seeds, start=1):
            await _upsert_node(session, seed, cities, index)

        for category in (await session.execute(select(CommodityCategory))).scalars().all():
            category.audit_status = "APPROVED"
        for commodity_type in (await session.execute(select(CommodityType))).scalars().all():
            commodity_type.audit_status = "APPROVED"

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_foundation_samples())
