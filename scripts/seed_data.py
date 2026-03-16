"""
系统基础数据初始化脚本
从main.py解耦的独立种子数据模块

生产环境执行：
    python -m scripts.seed_data

开发环境（自动）：
    main.py lifespan中在DEBUG模式下自动调用seed_all()
"""
import asyncio
import logging

logger = logging.getLogger(__name__)


async def seed_roles(db) -> dict:
    """初始化系统角色（幂等）"""
    from sqlalchemy import select
    from app.models.system import SysRole

    roles_data = [
        {"code": "SUPER_ADMIN", "name": "超级管理员", "description": "拥有全部权限", "sort_order": 0},
        {"code": "ADMIN",       "name": "管理员",     "description": "负责数据审核与系统管理", "sort_order": 1},
        {"code": "OPERATOR",    "name": "运营人员",   "description": "负责基础数据维护", "sort_order": 2},
        {"code": "COLLECTOR",   "name": "数据采集员", "description": "负责货源信息采集", "sort_order": 3},
    ]
    role_map: dict[str, SysRole] = {}
    for rd in roles_data:
        res = await db.execute(select(SysRole).where(SysRole.code == rd["code"]))
        role = res.scalar_one_or_none()
        if not role:
            role = SysRole(**rd)
            db.add(role)
            await db.flush()
            logger.info(f"[seed] role created: {rd['code']}")
        role_map[rd["code"]] = role
    return role_map


async def seed_users(db, role_map: dict) -> None:
    """初始化默认用户（幂等）"""
    from sqlalchemy import select
    from app.models.system import SysUser, SysUserRole
    from app.core.security import get_password_hash

    default_users = [
        ("admin",      "系统管理员", "Admin@2026",  "系统",   "SUPER_ADMIN"),
        ("collector1", "测试采集员", "Test@2026",   "采集部", "COLLECTOR"),
    ]

    for username, real_name, password, department, role_code in default_users:
        res = await db.execute(select(SysUser).where(SysUser.username == username))
        user = res.scalar_one_or_none()
        if not user:
            user = SysUser(
                username=username,
                real_name=real_name,
                password_hash=get_password_hash(password),
                department=department,
                status=1,
            )
            db.add(user)
            await db.flush()
            db.add(SysUserRole(user_id=user.id, role_id=role_map[role_code].id))
            logger.info(f"[seed] user created: {username}")


async def seed_waterways(db) -> dict:
    """初始化主要内河水系（幂等）"""
    from sqlalchemy import select
    from app.models.address import Waterway

    waterways_data = [
        {"code": "CJ", "name": "长江", "description": "中国最长的河流，内河航运主通道"},
        {"code": "GC", "name": "大运河", "description": "京杭大运河，南北交通大动脉"},
        {"code": "HJ", "name": "淮河", "description": "淮河流域航运网络"},
        {"code": "HH", "name": "黄河", "description": "黄河下游部分河段可通航"},
        {"code": "ZJ", "name": "珠江", "description": "华南内河航运主通道"},
        {"code": "HLJ", "name": "黑龙江", "description": "东北地区主要航运通道"},
        {"code": "MB", "name": "闽江", "description": "福建省内主要通航河流"},
        {"code": "XT", "name": "湘江", "description": "湖南省内主要通航河流"},
    ]

    waterway_map = {}
    for wd in waterways_data:
        res = await db.execute(select(Waterway).where(Waterway.code == wd["code"]))
        ww = res.scalar_one_or_none()
        if not ww:
            ww = Waterway(**wd)
            db.add(ww)
            await db.flush()
            logger.info(f"[seed] waterway created: {wd['name']}")
        waterway_map[wd["code"]] = ww
    return waterway_map


async def seed_regions(db, waterway_map: dict) -> None:
    """初始化商业区域（幂等）"""
    from sqlalchemy import select
    from app.models.address import Region

    regions_data = [
        {"code": "SN", "name": "苏南", "waterway_code": "CJ"},
        {"code": "SZ", "name": "苏中", "waterway_code": "CJ"},
        {"code": "AH", "name": "皖江", "waterway_code": "CJ"},
        {"code": "WH", "name": "武汉", "waterway_code": "CJ"},
        {"code": "CQ", "name": "重庆", "waterway_code": "CJ"},
        {"code": "JZ", "name": "荆州", "waterway_code": "CJ"},
        {"code": "SH", "name": "上海", "waterway_code": "CJ"},
        {"code": "HN", "name": "湖南", "waterway_code": "XT"},
        {"code": "GZ", "name": "广州", "waterway_code": "ZJ"},
        {"code": "WX", "name": "无锡", "waterway_code": "GC"},
        {"code": "SZ2", "name": "苏州", "waterway_code": "GC"},
        {"code": "HZ", "name": "杭州", "waterway_code": "GC"},
        {"code": "NJ", "name": "南京", "waterway_code": "CJ"},
    ]

    for rd in regions_data:
        ww = waterway_map.get(rd["waterway_code"])
        if not ww:
            continue
        res = await db.execute(select(Region).where(Region.code == rd["code"]))
        region = res.scalar_one_or_none()
        if not region:
            region = Region(
                code=rd["code"],
                name=rd["name"],
                main_rivers=[ww.name],   # Region无waterway_id外键，用main_rivers(JSON)存水系
            )
            db.add(region)
            logger.info(f"[seed] region created: {rd['name']}")


async def seed_node_types(db) -> dict:
    """初始化节点类型"""
    from sqlalchemy import select
    from app.models.address import NodeType

    types_data = [
        {"code": "PORT",      "name": "港口"},
        {"code": "WHARF",     "name": "码头"},
        {"code": "LOCK",      "name": "船闸"},
        {"code": "TERMINAL",  "name": "货运站"},
        {"code": "LOGISTICS", "name": "物流园"},
        {"code": "ANCHOR",    "name": "锚地"},
        {"code": "SHIPYARD",  "name": "船厂"},
        {"code": "BRIDGE",    "name": "桥梁控制点"},
    ]

    type_map = {}
    for td in types_data:
        res = await db.execute(select(NodeType).where(NodeType.code == td["code"]))
        nt = res.scalar_one_or_none()
        if not nt:
            nt = NodeType(**td)
            db.add(nt)
            await db.flush()
        type_map[td["code"]] = nt
    return type_map


async def seed_transport_nodes(db, waterway_map: dict, type_map: dict) -> None:
    """初始化主要运输节点"""
    from sqlalchemy import select
    from app.models.address import TransportNode

    nodes_data = [
        {"code": "NJ001", "name": "南京港",   "waterway": "CJ", "type": "PORT",  "lat": 32.0617, "lng": 118.7778},
        {"code": "WH001", "name": "武汉港",   "waterway": "CJ", "type": "PORT",  "lat": 30.5928, "lng": 114.3055},
        {"code": "CQ001", "name": "重庆港",   "waterway": "CJ", "type": "PORT",  "lat": 29.5630, "lng": 106.5516},
        {"code": "SH001", "name": "上海港",   "waterway": "CJ", "type": "PORT",  "lat": 31.2304, "lng": 121.4737},
        {"code": "AH001", "name": "芜湖港",   "waterway": "CJ", "type": "PORT",  "lat": 31.3333, "lng": 118.3667},
        {"code": "AH002", "name": "安庆港",   "waterway": "CJ", "type": "PORT",  "lat": 30.5085, "lng": 116.9742},
        {"code": "JZ001", "name": "荆州港",   "waterway": "CJ", "type": "PORT",  "lat": 30.3340, "lng": 112.2399},
        {"code": "YC001", "name": "宜昌港",   "waterway": "CJ", "type": "PORT",  "lat": 30.6920, "lng": 111.2864},
        {"code": "ZJ001", "name": "镇江港",   "waterway": "CJ", "type": "PORT",  "lat": 32.1875, "lng": 119.4247},
        {"code": "NT001", "name": "南通港",   "waterway": "CJ", "type": "PORT",  "lat": 31.9829, "lng": 120.8942},
    ]

    for nd in nodes_data:
        res = await db.execute(
            select(TransportNode).where(TransportNode.code == nd["code"])
        )
        node = res.scalar_one_or_none()
        if not node:
            ww = waterway_map.get(nd["waterway"])
            nt = type_map.get(nd["type"])
            node = TransportNode(
                code=nd["code"],
                name=nd["name"],
                waterway_id=ww.id if ww else None,
                node_type_id=nt.id if nt else None,
                latitude=nd.get("lat"),
                longitude=nd.get("lng"),
            )
            db.add(node)
            logger.info(f"[seed] transport_node created: {nd['name']}")


async def seed_commodity_categories(db) -> dict:
    """初始化商品大类"""
    from sqlalchemy import select
    from app.models.cargo import CommodityCategory

    categories_data = [
        {"name": "干散货", "code": "DRY_BULK", "description": "煤炭、矿石、粮食、砂石等"},
        {"name": "液态货", "code": "LIQUID",   "description": "成品油、化工液体等"},
        {"name": "集装箱", "code": "CONTAINER","description": "标准集装箱货物"},
        {"name": "件杂货", "code": "GENERAL",  "description": "散装件杂货、机械设备等"},
        {"name": "特种货", "code": "SPECIAL",  "description": "危险品、超重超大件等"},
    ]

    cat_map = {}
    for cd in categories_data:
        res = await db.execute(
            select(CommodityCategory).where(CommodityCategory.code == cd["code"])
        )
        cat = res.scalar_one_or_none()
        if not cat:
            cat = CommodityCategory(**cd)
            db.add(cat)
            await db.flush()
            logger.info(f"[seed] commodity_category created: {cd['name']}")
        cat_map[cd["code"]] = cat
    return cat_map


async def seed_vessel_types(db) -> None:
    """初始化船舶类型字典"""
    from sqlalchemy import select
    from app.models.vessel import VesselTypeDict

    vessel_types = [
        {"code": "BULK",      "name": "散货船"},
        {"code": "TANKER",    "name": "油轮"},
        {"code": "CONTAINER", "name": "集装箱船"},
        {"code": "RO_RO",     "name": "滚装船"},
        {"code": "BARGE",     "name": "驳船"},
        {"code": "PUSHER",    "name": "推船"},
        {"code": "PASSENGER", "name": "客船"},
        {"code": "CARGO",     "name": "货船"},
        {"code": "CHEMICAL",  "name": "化学品船"},
        {"code": "LPG",       "name": "液化气船"},
        {"code": "SAND",      "name": "采砂船"},
        {"code": "CRANE",     "name": "起重船"},
        {"code": "OTHER",     "name": "其他"},
    ]

    for vt in vessel_types:
        res = await db.execute(
            select(VesselTypeDict).where(VesselTypeDict.code == vt["code"])
        )
        if not res.scalar_one_or_none():
            db.add(VesselTypeDict(**vt))
            logger.info(f"[seed] vessel_type created: {vt['name']}")


async def seed_all() -> None:
    """执行所有种子数据初始化（幂等）"""
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            role_map = await seed_roles(db)
            await seed_users(db, role_map)
            waterway_map = await seed_waterways(db)
            await seed_regions(db, waterway_map)
            type_map = await seed_node_types(db)
            await seed_transport_nodes(db, waterway_map, type_map)
            await seed_commodity_categories(db)
            await seed_vessel_types(db)
            await db.commit()
            logger.info("[seed] All seed data initialized successfully")
        except Exception as e:
            await db.rollback()
            logger.error(f"[seed] Seed data failed: {e}")
            raise


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    asyncio.run(seed_all())
