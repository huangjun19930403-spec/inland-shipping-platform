"""项目一期主线种子数据初始化脚本。

目标：只生成当前主线所需的最小可运行数据集。
执行：python -m scripts.seed_data
"""

import asyncio
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.address import (
    AdminRegion,
    NodeAlias,
    NodeType,
    Region,
    RegionAddressRelation,
    RegionCityRelation,
    RegionWaterwayRelation,
    TransportNode,
    TransportNodeProfile,
    Waterway,
)
from app.models.ai import AiPromptTemplate, AiPromptVersion
from app.models.cargo import (
    CargoFreight,
    CommodityAlias,
    CommodityCategory,
    CommodityStandard,
    CommodityType,
)
from app.models.route import (
    ShippingRoute,
    ShippingRoutePath,
    ShippingRoutePathNode,
    ShippingRoutePathSegment,
)
from app.models.system import SysRole, SysUser, SysUserRole
from app.models.vessel import Vessel, VesselDynamic, VesselTypeDict
from app.tasks.stat_tasks import refresh_cargo_stats, refresh_all_vessel_stats

logger = logging.getLogger(__name__)


ROLES = [
    {"code": "SUPER_ADMIN", "name": "超级管理员", "sort_order": 1},
    {"code": "ADMIN", "name": "管理员", "sort_order": 2},
    {"code": "OPERATOR", "name": "运营人员", "sort_order": 3},
    {"code": "COLLECTOR", "name": "采集员", "sort_order": 4},
]

USERS = [
    {
        "username": "admin",
        "real_name": "系统管理员",
        "password": "Admin@2026",
        "phone": "13800138000",
        "roles": ["SUPER_ADMIN"],
    },
    {
        "username": "operator1",
        "real_name": "运营测试用户",
        "password": "Test@2026",
        "phone": "13800138001",
        "roles": ["OPERATOR"],
    },
    {
        "username": "collector1",
        "real_name": "采集测试用户",
        "password": "Test@2026",
        "phone": "13800138002",
        "roles": ["COLLECTOR"],
    },
]

WATERWAYS = [
    {
        "code": "YANGTZE",
        "name": "长江",
        "level": 1,
        "provinces": "重庆,湖北,江苏",
        "description": "内河主干水系",
        "sort_order": 1,
    },
    {
        "code": "JINGHANG",
        "name": "京杭运河",
        "level": 1,
        "provinces": "北京,天津,河北,山东,江苏,浙江",
        "description": "内河重要人工运河",
        "sort_order": 2,
    },
    {
        "code": "HAN_RIVER",
        "name": "汉江",
        "level": 2,
        "parent_code": "YANGTZE",
        "provinces": "陕西,湖北",
        "description": "长江主要支流",
        "sort_order": 3,
    },
]

ADMIN_REGIONS = [
    {"code": "320000", "name": "江苏省", "level": 1, "parent_code": None, "longitude": 118.767413, "latitude": 32.041544},
    {"code": "420000", "name": "湖北省", "level": 1, "parent_code": None, "longitude": 114.298572, "latitude": 30.584355},
    {"code": "500000", "name": "重庆市", "level": 1, "parent_code": None, "longitude": 106.551556, "latitude": 29.563009},
    {"code": "320100", "name": "南京市", "level": 2, "parent_code": "320000", "longitude": 118.796877, "latitude": 32.060255},
    {"code": "320500", "name": "苏州市", "level": 2, "parent_code": "320000", "longitude": 120.585316, "latitude": 31.298886},
    {"code": "420100", "name": "武汉市", "level": 2, "parent_code": "420000", "longitude": 114.305393, "latitude": 30.593099},
    {"code": "500100", "name": "重庆市", "level": 2, "parent_code": "500000", "longitude": 106.551556, "latitude": 29.563009},
    {"code": "320111", "name": "浦口区", "level": 3, "parent_code": "320100", "longitude": 118.628493, "latitude": 32.058406},
    {"code": "420116", "name": "黄陂区", "level": 3, "parent_code": "420100", "longitude": 114.374025, "latitude": 30.874155},
    {"code": "500115", "name": "长寿区", "level": 3, "parent_code": "500100", "longitude": 107.074854, "latitude": 29.833671},
]

REGIONS = [
    {
        "code": "RG-001",
        "name": "长江中上游核心区",
        "center_longitude": 109.90,
        "center_latitude": 30.10,
        "boundary_coordinates": [
            [106.0, 28.7],
            [112.0, 28.7],
            [114.5, 31.5],
            [109.0, 31.8],
            [106.0, 28.7],
        ],
        "waterways": ["YANGTZE", "HAN_RIVER"],
        "cities": ["500100", "420100"],
    },
    {
        "code": "RG-002",
        "name": "长江下游核心区",
        "center_longitude": 119.90,
        "center_latitude": 31.70,
        "boundary_coordinates": [
            [117.2, 30.5],
            [121.5, 30.5],
            [121.5, 32.8],
            [117.2, 32.8],
            [117.2, 30.5],
        ],
        "waterways": ["YANGTZE", "JINGHANG"],
        "cities": ["320100", "320500"],
    },
]

NODE_TYPES = [
    {"code": "PORT", "name": "港口", "transport_mode": "WATERWAY", "sort_order": 1},
    {"code": "TERMINAL", "name": "货运站", "transport_mode": "MULTIMODAL", "sort_order": 2},
    {"code": "RAIL_HUB", "name": "铁路货运枢纽", "transport_mode": "RAILWAY", "sort_order": 3},
]

TRANSPORT_NODES = [
    {
        "code": "TN-WH-YL",
        "name": "武汉阳逻港",
        "node_type": "PORT",
        "node_category": 4,
        "waterway": "YANGTZE",
        "province": "湖北省",
        "city": "武汉市",
        "district": "黄陂区",
        "province_code": "420000",
        "city_code": "420100",
        "district_code": "420116",
        "longitude": 114.651900,
        "latitude": 30.743300,
        "aliases": ["阳逻港", "武汉港"],
        "profile": {"river_km": Decimal("1038.50"), "max_tonnage": 10000, "berth_count": 8, "annual_throughput": "1.2亿吨"},
        "regions": [("RG-001", 1)],
    },
    {
        "code": "TN-NJ-LT",
        "name": "南京龙潭港",
        "node_type": "PORT",
        "node_category": 4,
        "waterway": "YANGTZE",
        "province": "江苏省",
        "city": "南京市",
        "district": "浦口区",
        "province_code": "320000",
        "city_code": "320100",
        "district_code": "320111",
        "longitude": 118.865600,
        "latitude": 32.166900,
        "aliases": ["龙潭港"],
        "profile": {"river_km": Decimal("246.20"), "max_tonnage": 8000, "berth_count": 6, "annual_throughput": "8500万吨"},
        "regions": [("RG-002", 1)],
    },
    {
        "code": "TN-SZ-TC",
        "name": "苏州太仓港",
        "node_type": "PORT",
        "node_category": 4,
        "waterway": "JINGHANG",
        "province": "江苏省",
        "city": "苏州市",
        "district": None,
        "province_code": "320000",
        "city_code": "320500",
        "district_code": None,
        "longitude": 121.124100,
        "latitude": 31.463900,
        "aliases": ["太仓港"],
        "profile": {"river_km": Decimal("38.00"), "max_tonnage": 5000, "berth_count": 4, "annual_throughput": "4200万吨"},
        "regions": [("RG-002", 1)],
    },
    {
        "code": "TN-CQ-GY",
        "name": "重庆果园港",
        "node_type": "TERMINAL",
        "node_category": 4,
        "waterway": "YANGTZE",
        "province": "重庆市",
        "city": "重庆市",
        "district": "长寿区",
        "province_code": "500000",
        "city_code": "500100",
        "district_code": "500115",
        "longitude": 107.001200,
        "latitude": 29.855900,
        "aliases": ["果园港"],
        "profile": {"river_km": Decimal("660.00"), "max_tonnage": 10000, "berth_count": 10, "annual_throughput": "9000万吨"},
        "regions": [("RG-001", 1)],
    },
]

COMMODITY_CATEGORIES = [
    {"code": "COAL", "name": "煤炭类", "sort_order": 1},
    {"code": "ORE", "name": "矿石类", "sort_order": 2},
]

COMMODITY_TYPES = [
    {"code": "COAL_THERMAL", "name": "动力煤", "category": "COAL", "sort_order": 1},
    {"code": "ORE_IRON", "name": "铁矿石", "category": "ORE", "sort_order": 1},
]

COMMODITY_STANDARDS = [
    {
        "code": "COAL-STEAM",
        "name": "动力煤",
        "type": "COAL_THERMAL",
        "aliases": ["煤炭", "电煤"],
    },
    {
        "code": "ORE-IRON-62",
        "name": "铁矿石(62%)",
        "type": "ORE_IRON",
        "aliases": ["铁矿", "矿石"],
    },
]

VESSEL_TYPES = [
    {
        "code": "DBC",
        "name": "干散货船",
        "transport_type": "WATERWAY",
        "min_tonnage": 500,
        "max_tonnage": 12000,
    }
]

VESSELS = [
    {
        "vessel_no": "CN-TEST-0001",
        "vessel_name": "江运001",
        "mmsi": "413000001",
        "vessel_type": "DBC",
        "deadweight": 5200,
        "build_year": 2018,
        "home_port": "武汉",
    },
    {
        "vessel_no": "CN-TEST-0002",
        "vessel_name": "江运002",
        "mmsi": "413000002",
        "vessel_type": "DBC",
        "deadweight": 7600,
        "build_year": 2016,
        "home_port": "南京",
    },
]

DYNAMICS = [
    {
        "mmsi": "413000001",
        "node": "TN-WH-YL",
        "city_code": "420100",
        "region": "RG-001",
        "longitude": 114.651900,
        "latitude": 30.743300,
        "vessel_status": "IN_PORT",
    },
    {
        "mmsi": "413000002",
        "node": "TN-NJ-LT",
        "city_code": "320100",
        "region": "RG-002",
        "longitude": 118.865600,
        "latitude": 32.166900,
        "vessel_status": "UNDERWAY",
    },
]

ROUTES = [
    {
        "code": "RT-SEED-001",
        "name": "武汉-南京煤炭线",
        "origin_region": "RG-001",
        "dest_region": "RG-002",
        "distance_km": Decimal("680.00"),
        "duration_hours": Decimal("48.00"),
        "path": {
            "code": "RP-SEED-001",
            "name": "长江主线方案",
            "nodes": [
                {"node": "TN-WH-YL", "sequence": 1, "node_role": "START"},
                {"node": "TN-NJ-LT", "sequence": 2, "node_role": "END"},
            ],
            "segments": [
                {
                    "sequence": 1,
                    "segment_type": "WATERWAY",
                    "transport_mode": "WATERWAY",
                    "from_node": "TN-WH-YL",
                    "to_node": "TN-NJ-LT",
                    "waterway": "YANGTZE",
                    "distance_km": Decimal("650.00"),
                    "duration_hours": Decimal("46.00"),
                    "cost_factor": Decimal("1.000"),
                    "remark": "主航道直达",
                },
                {
                    "sequence": 2,
                    "segment_type": "MULTIMODAL_TRANSFER",
                    "transport_mode": "HIGHWAY",
                    "from_node": "TN-NJ-LT",
                    "to_node": "TN-SZ-TC",
                    "waterway": "JINGHANG",
                    "distance_km": Decimal("30.00"),
                    "duration_hours": Decimal("2.00"),
                    "cost_factor": Decimal("1.150"),
                    "remark": "支线接驳",
                },
            ],
        },
    }
]

AI_SYSTEM_PROMPT = """你是中国内河航运货源解析助手。
请从输入文本抽取起运地、目的地、货物、吨位、装货时间、运价、联系方式。
无法确定的字段返回 null。"""

AI_USER_TEMPLATE = """请解析以下货运文本并输出 JSON：
{raw_text}

JSON结构：
{
  "origin": {"value": null, "confidence": 0},
  "destination": {"value": null, "confidence": 0},
  "commodity": {"value": null, "confidence": 0},
  "tonnage": {"value": null, "unit": "吨", "confidence": 0},
  "loading_date": {"value": null, "confidence": 0},
  "freight_price": {"value": null, "unit": "元/吨", "confidence": 0},
  "contact": {"value": null, "confidence": 0},
  "remarks": ""
}"""


async def seed_roles(db):
    role_map = {}
    for row in ROLES:
        role = (
            await db.execute(select(SysRole).where(SysRole.code == row["code"]))
        ).scalar_one_or_none()
        if not role:
            role = SysRole(
                code=row["code"],
                name=row["name"],
                status=1,
                sort_order=row["sort_order"],
            )
            db.add(role)
            await db.flush()
        else:
            role.name = row["name"]
            role.sort_order = row["sort_order"]
            role.status = 1
        role_map[row["code"]] = role
    logger.info("[seed] roles=%s", len(role_map))
    return role_map


async def seed_users(db, role_map):
    for row in USERS:
        user = (
            await db.execute(select(SysUser).where(SysUser.username == row["username"]))
        ).scalar_one_or_none()
        password_hash = get_password_hash(row["password"])
        if not user:
            user = SysUser(
                username=row["username"],
                real_name=row["real_name"],
                password_hash=password_hash,
                phone=row["phone"],
                status=1,
                created_by=1,
            )
            db.add(user)
            await db.flush()
        else:
            user.real_name = row["real_name"]
            user.password_hash = password_hash
            user.phone = row["phone"]
            user.status = 1

        await db.execute(delete(SysUserRole).where(SysUserRole.user_id == user.id))
        for role_code in row["roles"]:
            db.add(SysUserRole(user_id=user.id, role_id=role_map[role_code].id))

    logger.info("[seed] users=%s", len(USERS))


async def seed_waterways(db):
    w_map = {}
    for row in WATERWAYS:
        waterway = (
            await db.execute(select(Waterway).where(Waterway.code == row["code"]))
        ).scalar_one_or_none()
        parent_id = None
        if row.get("parent_code"):
            parent = (
                await db.execute(select(Waterway).where(Waterway.code == row["parent_code"]))
            ).scalar_one_or_none()
            parent_id = parent.id if parent else None

        if not waterway:
            waterway = Waterway(
                code=row["code"],
                name=row["name"],
                level=row["level"],
                parent_id=parent_id,
                provinces=row.get("provinces"),
                description=row.get("description"),
                sort_order=row.get("sort_order", 0),
                status=1,
                audit_status=1,
            )
            db.add(waterway)
            await db.flush()
        else:
            waterway.name = row["name"]
            waterway.level = row["level"]
            waterway.parent_id = parent_id
            waterway.provinces = row.get("provinces")
            waterway.description = row.get("description")
            waterway.sort_order = row.get("sort_order", 0)
            waterway.status = 1
            waterway.audit_status = 1

        w_map[row["code"]] = waterway

    logger.info("[seed] waterways=%s", len(w_map))
    return w_map


async def seed_admin_regions(db):
    a_map = {}
    for idx, row in enumerate(ADMIN_REGIONS, start=1):
        item = (
            await db.execute(select(AdminRegion).where(AdminRegion.code == row["code"]))
        ).scalar_one_or_none()

        payload = {
            "name": row["name"],
            "level": row["level"],
            "parent_code": row["parent_code"],
            "full_path": f"{row['name']}" if row["level"] == 1 else None,
            "longitude": Decimal(str(row["longitude"])) if row.get("longitude") is not None else None,
            "latitude": Decimal(str(row["latitude"])) if row.get("latitude") is not None else None,
            "sort_order": idx,
            "status": 1,
        }

        if not item:
            item = AdminRegion(code=row["code"], **payload)
            db.add(item)
            await db.flush()
        else:
            for k, v in payload.items():
                setattr(item, k, v)

        a_map[row["code"]] = item

    logger.info("[seed] admin_regions=%s", len(a_map))
    return a_map


async def seed_regions(db, waterway_map, admin_map):
    r_map = {}
    for idx, row in enumerate(REGIONS, start=1):
        region = (
            await db.execute(select(Region).where(Region.code == row["code"]))
        ).scalar_one_or_none()

        payload = {
            "name": row["name"],
            "center_longitude": Decimal(str(row["center_longitude"])),
            "center_latitude": Decimal(str(row["center_latitude"])),
            "boundary_coordinates": row["boundary_coordinates"],
            "boundary_color": "#1A73E8",
            "area_color": "#D2E3FC",
            "description": "一期核心运营区域",
            "sort_order": idx,
            "status": 1,
            "audit_status": 1,
        }

        if not region:
            region = Region(code=row["code"], **payload)
            db.add(region)
            await db.flush()
        else:
            for k, v in payload.items():
                setattr(region, k, v)

        await db.execute(
            delete(RegionWaterwayRelation).where(RegionWaterwayRelation.region_id == region.id)
        )
        for ww_code in row["waterways"]:
            db.add(
                RegionWaterwayRelation(
                    region_id=region.id,
                    waterway_id=waterway_map[ww_code].id,
                    relation_type="MAIN",
                    source="SEED",
                )
            )

        await db.execute(
            delete(RegionCityRelation).where(RegionCityRelation.region_id == region.id)
        )
        for city_code in row["cities"]:
            db.add(
                RegionCityRelation(
                    region_id=region.id,
                    admin_region_id=admin_map[city_code].id,
                    relation_type="MAIN",
                    source="SEED",
                )
            )

        r_map[row["code"]] = region

    logger.info("[seed] regions=%s", len(r_map))
    return r_map


async def seed_node_types(db):
    t_map = {}
    for row in NODE_TYPES:
        item = (
            await db.execute(select(NodeType).where(NodeType.code == row["code"]))
        ).scalar_one_or_none()
        if not item:
            item = NodeType(
                code=row["code"],
                name=row["name"],
                transport_mode=row["transport_mode"],
                sort_order=row["sort_order"],
                status=1,
                audit_status=1,
            )
            db.add(item)
            await db.flush()
        else:
            item.name = row["name"]
            item.transport_mode = row["transport_mode"]
            item.sort_order = row["sort_order"]
            item.status = 1
            item.audit_status = 1

        t_map[row["code"]] = item

    logger.info("[seed] node_types=%s", len(t_map))
    return t_map


async def seed_transport_nodes(db, node_type_map, waterway_map, region_map):
    n_map = {}

    for row in TRANSPORT_NODES:
        item = (
            await db.execute(select(TransportNode).where(TransportNode.code == row["code"]))
        ).scalar_one_or_none()

        payload = {
            "name": row["name"],
            "node_type_id": node_type_map[row["node_type"]].id,
            "node_category": row["node_category"],
            "waterway_id": waterway_map[row["waterway"]].id if row.get("waterway") else None,
            "province": row.get("province"),
            "city": row.get("city"),
            "district": row.get("district"),
            "province_code": row.get("province_code"),
            "city_code": row.get("city_code"),
            "district_code": row.get("district_code"),
            "longitude": Decimal(str(row["longitude"])) if row.get("longitude") is not None else None,
            "latitude": Decimal(str(row["latitude"])) if row.get("latitude") is not None else None,
            "status": 1,
            "audit_status": 1,
            "description": "一期示例运输节点",
        }

        if not item:
            item = TransportNode(code=row["code"], **payload)
            db.add(item)
            await db.flush()
        else:
            for k, v in payload.items():
                setattr(item, k, v)

        profile_data = row.get("profile") or {}
        profile = (
            await db.execute(
                select(TransportNodeProfile).where(TransportNodeProfile.transport_node_id == item.id)
            )
        ).scalar_one_or_none()
        if not profile:
            profile = TransportNodeProfile(transport_node_id=item.id, **profile_data)
            db.add(profile)
        else:
            for k, v in profile_data.items():
                setattr(profile, k, v)

        existing_aliases = {
            a.alias_name
            for a in (
                await db.execute(select(NodeAlias).where(NodeAlias.node_id == item.id))
            ).scalars().all()
        }
        for alias_name in row.get("aliases", []):
            if alias_name not in existing_aliases:
                db.add(
                    NodeAlias(
                        node_id=item.id,
                        alias_name=alias_name,
                        alias_type="COMMON",
                        source="SEED",
                        priority=0,
                        status=1,
                    )
                )

        await db.execute(
            delete(RegionAddressRelation).where(RegionAddressRelation.transport_node_id == item.id)
        )
        for region_code, is_primary in row.get("regions", []):
            db.add(
                RegionAddressRelation(
                    region_id=region_map[region_code].id,
                    transport_node_id=item.id,
                    is_primary=is_primary,
                    relation_type="BELONGS",
                    source="SEED",
                )
            )

        n_map[row["code"]] = item

    logger.info("[seed] transport_nodes=%s", len(n_map))
    return n_map


async def seed_commodities(db):
    c_map = {}
    t_map = {}
    s_map = {}

    for row in COMMODITY_CATEGORIES:
        item = (
            await db.execute(select(CommodityCategory).where(CommodityCategory.code == row["code"]))
        ).scalar_one_or_none()
        if not item:
            item = CommodityCategory(
                code=row["code"],
                name=row["name"],
                sort_order=row["sort_order"],
                status=1,
                audit_status=1,
                submitter_id=1,
            )
            db.add(item)
            await db.flush()
        else:
            item.name = row["name"]
            item.sort_order = row["sort_order"]
            item.status = 1
            item.audit_status = 1
        c_map[row["code"]] = item

    for row in COMMODITY_TYPES:
        item = (
            await db.execute(select(CommodityType).where(CommodityType.code == row["code"]))
        ).scalar_one_or_none()
        if not item:
            item = CommodityType(
                code=row["code"],
                name=row["name"],
                category_id=c_map[row["category"]].id,
                sort_order=row["sort_order"],
                status=1,
                audit_status=1,
                submitter_id=1,
            )
            db.add(item)
            await db.flush()
        else:
            item.name = row["name"]
            item.category_id = c_map[row["category"]].id
            item.sort_order = row["sort_order"]
            item.status = 1
            item.audit_status = 1
        t_map[row["code"]] = item

    for row in COMMODITY_STANDARDS:
        item = (
            await db.execute(select(CommodityStandard).where(CommodityStandard.code == row["code"]))
        ).scalar_one_or_none()
        if not item:
            item = CommodityStandard(
                code=row["code"],
                name=row["name"],
                type_id=t_map[row["type"]].id,
                status=1,
                audit_status=1,
                submitter_id=1,
            )
            db.add(item)
            await db.flush()
        else:
            item.name = row["name"]
            item.type_id = t_map[row["type"]].id
            item.status = 1
            item.audit_status = 1

        await db.execute(delete(CommodityAlias).where(CommodityAlias.commodity_id == item.id))
        for idx, alias_name in enumerate(row.get("aliases", []), start=1):
            db.add(
                CommodityAlias(
                    commodity_id=item.id,
                    alias_name=alias_name,
                    alias_type="COMMON",
                    priority=idx,
                    status=1,
                )
            )

        s_map[row["code"]] = item

    logger.info("[seed] commodity_categories=%s commodity_types=%s commodity_standards=%s", len(c_map), len(t_map), len(s_map))
    return s_map


async def seed_vessels(db, vessel_type_map, node_map, region_map):
    vessel_map = {}

    for row in VESSEL_TYPES:
        item = (
            await db.execute(select(VesselTypeDict).where(VesselTypeDict.code == row["code"]))
        ).scalar_one_or_none()
        if not item:
            item = VesselTypeDict(
                code=row["code"],
                name=row["name"],
                transport_type=row["transport_type"],
                min_tonnage=row["min_tonnage"],
                max_tonnage=row["max_tonnage"],
                status=1,
                audit_status=1,
                submitter_id=1,
            )
            db.add(item)
            await db.flush()
        else:
            item.name = row["name"]
            item.transport_type = row["transport_type"]
            item.min_tonnage = row["min_tonnage"]
            item.max_tonnage = row["max_tonnage"]
            item.status = 1
            item.audit_status = 1

        vessel_type_map[row["code"]] = item

    for row in VESSELS:
        vessel = (
            await db.execute(select(Vessel).where(Vessel.vessel_no == row["vessel_no"]))
        ).scalar_one_or_none()

        payload = {
            "vessel_name": row["vessel_name"],
            "mmsi": row["mmsi"],
            "vessel_type_id": vessel_type_map[row["vessel_type"]].id,
            "deadweight": row["deadweight"],
            "build_year": row["build_year"],
            "home_port": row["home_port"],
            "data_status": 1,
            "is_deleted": 0,
            "audit_status": 1,
            "submitter_id": 1,
        }

        if not vessel:
            vessel = Vessel(vessel_no=row["vessel_no"], **payload)
            db.add(vessel)
            await db.flush()
        else:
            for k, v in payload.items():
                setattr(vessel, k, v)

        vessel_map[row["mmsi"]] = vessel

    for row in DYNAMICS:
        vessel = vessel_map[row["mmsi"]]
        dynamic = (
            await db.execute(select(VesselDynamic).where(VesselDynamic.mmsi == row["mmsi"]))
        ).scalar_one_or_none()

        payload = {
            "vessel_id": vessel.id,
            "current_node_id": node_map[row["node"]].id,
            "current_region_id": region_map[row["region"]].id,
            "current_city_code": row["city_code"],
            "current_longitude": Decimal(str(row["longitude"])),
            "current_latitude": Decimal(str(row["latitude"])),
            "position_match_type": "NODE",
            "position_match_distance_m": Decimal("0.00"),
            "vessel_status": row["vessel_status"],
            "data_source": "SEED",
            "reported_at": datetime.now(),
            "updated_by": 1,
        }

        if not dynamic:
            dynamic = VesselDynamic(mmsi=row["mmsi"], **payload)
            db.add(dynamic)
        else:
            for k, v in payload.items():
                setattr(dynamic, k, v)

    logger.info("[seed] vessel_types=%s vessels=%s dynamics=%s", len(vessel_type_map), len(VESSELS), len(DYNAMICS))


async def seed_routes(db, region_map, node_map, waterway_map):
    for route_row in ROUTES:
        route = (
            await db.execute(select(ShippingRoute).where(ShippingRoute.code == route_row["code"]))
        ).scalar_one_or_none()

        payload = {
            "name": route_row["name"],
            "origin_region_id": region_map[route_row["origin_region"]].id,
            "dest_region_id": region_map[route_row["dest_region"]].id,
            "distance_km": route_row["distance_km"],
            "duration_hours": route_row["duration_hours"],
            "status": 1,
            "sort_order": 1,
            "created_by": 1,
        }

        if not route:
            route = ShippingRoute(code=route_row["code"], **payload)
            db.add(route)
            await db.flush()
        else:
            for k, v in payload.items():
                setattr(route, k, v)

        path_cfg = route_row["path"]
        path = (
            await db.execute(select(ShippingRoutePath).where(ShippingRoutePath.code == path_cfg["code"]))
        ).scalar_one_or_none()

        if not path:
            path = ShippingRoutePath(
                route_id=route.id,
                code=path_cfg["code"],
                name=path_cfg["name"],
                sort_order=1,
                status=1,
            )
            db.add(path)
            await db.flush()
        else:
            path.route_id = route.id
            path.name = path_cfg["name"]
            path.sort_order = 1
            path.status = 1

        await db.execute(delete(ShippingRoutePathNode).where(ShippingRoutePathNode.path_id == path.id))
        for node_cfg in path_cfg["nodes"]:
            db.add(
                ShippingRoutePathNode(
                    path_id=path.id,
                    node_id=node_map[node_cfg["node"]].id,
                    sequence=node_cfg["sequence"],
                    node_role=node_cfg["node_role"],
                )
            )

        await db.execute(delete(ShippingRoutePathSegment).where(ShippingRoutePathSegment.path_id == path.id))
        for seg in path_cfg["segments"]:
            db.add(
                ShippingRoutePathSegment(
                    path_id=path.id,
                    sequence=seg["sequence"],
                    segment_type=seg["segment_type"],
                    transport_mode=seg["transport_mode"],
                    from_node_id=node_map[seg["from_node"]].id,
                    to_node_id=node_map[seg["to_node"]].id,
                    waterway_id=waterway_map[seg["waterway"]].id if seg.get("waterway") else None,
                    distance_km=seg.get("distance_km"),
                    duration_hours=seg.get("duration_hours"),
                    cost_factor=seg.get("cost_factor"),
                    remark=seg.get("remark"),
                )
            )

    logger.info("[seed] routes=%s", len(ROUTES))


async def seed_ai_prompt(db):
    template = (
        await db.execute(select(AiPromptTemplate).where(AiPromptTemplate.name == "cargo_parse"))
    ).scalar_one_or_none()
    if not template:
        template = AiPromptTemplate(
            name="cargo_parse",
            use_case="货运文本解析",
            description="一期货源文本解析提示词模板",
            active_version=1,
            is_active=True,
            created_by=1,
        )
        db.add(template)
        await db.flush()
    else:
        template.use_case = "货运文本解析"
        template.description = "一期货源文本解析提示词模板"
        template.active_version = 1
        template.is_active = True

    version = (
        await db.execute(
            select(AiPromptVersion).where(
                AiPromptVersion.template_id == template.id,
                AiPromptVersion.version == 1,
            )
        )
    ).scalar_one_or_none()

    if not version:
        version = AiPromptVersion(
            template_id=template.id,
            version=1,
            system_prompt=AI_SYSTEM_PROMPT,
            user_template=AI_USER_TEMPLATE,
            change_note="一期基线模板",
            created_by=1,
        )
        db.add(version)
    else:
        version.system_prompt = AI_SYSTEM_PROMPT
        version.user_template = AI_USER_TEMPLATE
        version.change_note = "一期基线模板"

    logger.info("[seed] ai_prompt_template=cargo_parse:v1")


async def seed_freights(db, node_map, region_map, commodity_map):
    base_day = date.today()
    samples = [
        {
            "freight_no": f"CS-{base_day.strftime('%Y%m%d')}-SEED001",
            "origin_node": "TN-WH-YL",
            "dest_node": "TN-NJ-LT",
            "origin_city": "420100",
            "dest_city": "320100",
            "origin_region": "RG-001",
            "dest_region": "RG-002",
            "commodity": "COAL-STEAM",
            "tonnage": Decimal("5000.00"),
            "price": Decimal("38.50"),
            "match_level": "NODE",
            "quality": Decimal("95.00"),
        },
        {
            "freight_no": f"CS-{base_day.strftime('%Y%m%d')}-SEED002",
            "origin_node": None,
            "dest_node": None,
            "origin_city": "500100",
            "dest_city": "420100",
            "origin_region": "RG-001",
            "dest_region": "RG-001",
            "commodity": "ORE-IRON-62",
            "tonnage": Decimal("4200.00"),
            "price": Decimal("56.00"),
            "match_level": "CITY",
            "quality": Decimal("82.00"),
        },
    ]

    for idx, row in enumerate(samples):
        item = (
            await db.execute(select(CargoFreight).where(CargoFreight.freight_no == row["freight_no"]))
        ).scalar_one_or_none()

        payload = {
            "source_type": "MANUAL",
            "status": "CONFIRMED",
            "origin_node_id": node_map[row["origin_node"]].id if row["origin_node"] else None,
            "origin_admin_code": row["origin_city"],
            "origin_admin_name": "武汉市" if row["origin_city"] == "420100" else "重庆市",
            "origin_region_id": region_map[row["origin_region"]].id,
            "origin_precision": "NODE" if row["origin_node"] else "CITY",
            "origin_raw_text": "seed_origin",
            "dest_node_id": node_map[row["dest_node"]].id if row["dest_node"] else None,
            "dest_admin_code": row["dest_city"],
            "dest_admin_name": "南京市" if row["dest_city"] == "320100" else "武汉市",
            "dest_region_id": region_map[row["dest_region"]].id,
            "dest_precision": "NODE" if row["dest_node"] else "CITY",
            "dest_raw_text": "seed_dest",
            "commodity_id": commodity_map[row["commodity"]].id,
            "commodity_text": commodity_map[row["commodity"]].name,
            "tonnage": row["tonnage"],
            "loading_date": base_day,
            "expire_date": base_day + timedelta(days=7),
            "freight_price": row["price"],
            "price_type": 1,
            "price_unit": "元/吨",
            "contact_person": "测试用户",
            "contact_phone": "13800000000",
            "collector_id": 2,
            "source_message_time": datetime.now() - timedelta(hours=idx + 1),
            "location_match_level": row["match_level"],
            "data_quality_score": row["quality"],
            "analysis_status": "READY",
            "audit_status": 1,
            "submitter_id": 2,
            "auditor_id": 1,
        }

        if not item:
            item = CargoFreight(freight_no=row["freight_no"], **payload)
            db.add(item)
        else:
            for k, v in payload.items():
                setattr(item, k, v)

    logger.info("[seed] freights=%s", len(samples))


async def seed_all() -> None:
    """执行一期主线全量种子初始化。"""
    print("=== 一期主线种子初始化开始 ===")

    async with AsyncSessionLocal() as db:
        try:
            role_map = await seed_roles(db)
            await seed_users(db, role_map)
            waterway_map = await seed_waterways(db)
            admin_map = await seed_admin_regions(db)
            region_map = await seed_regions(db, waterway_map, admin_map)
            node_type_map = await seed_node_types(db)
            node_map = await seed_transport_nodes(db, node_type_map, waterway_map, region_map)
            commodity_map = await seed_commodities(db)
            vessel_type_map = {}
            await seed_vessels(db, vessel_type_map, node_map, region_map)
            await seed_routes(db, region_map, node_map, waterway_map)
            await seed_ai_prompt(db)
            await seed_freights(db, node_map, region_map, commodity_map)
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    print("[+] 刷新统计快照...")
    await refresh_cargo_stats(date.today())
    await refresh_all_vessel_stats()

    print("=== 种子初始化完成 ===")
    print("默认账号:")
    print("  admin      / Admin@2026   (SUPER_ADMIN)")
    print("  operator1  / Test@2026    (OPERATOR)")
    print("  collector1 / Test@2026    (COLLECTOR)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(seed_all())
