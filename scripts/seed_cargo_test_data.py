"""
货源模块测试数据初始化脚本

功能：
  1. 写入主要内河港口城市的行政区划（admin_region level=2），含经纬度
  2. 写入货品大类 → 货品类型 → 标准货品（各 5~10 条）
  3. 写入 30 条 cargo_freight 手动货源记录（不同路线、日期、货品、状态）
  4. 触发一次 refresh_cargo_stats 统计聚合，填充分析统计表

执行方式（在项目根目录）：
    python -m scripts.seed_cargo_test_data

幂等：重复执行不会重复写入（通过 code/freight_no 唯一约束判断）
"""
import asyncio
import logging
import uuid
from datetime import date, timedelta
import random

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────
# 1. 行政区划 — 主要内河港口城市（level=2）
# ─────────────────────────────────────────────────

CITIES = [
    # (code, name, short_name, pinyin, parent_code, longitude, latitude)
    ("320100", "南京市", "南京", "nanjing",  "320000", 118.7969, 32.0603),
    ("320500", "苏州市", "苏州", "suzhou",   "320000", 120.5853, 31.2990),
    ("320600", "南通市", "南通", "nantong",  "320000", 120.8651, 32.0160),
    ("320700", "连云港市","连云港","lianyungang","320000",119.1725,34.5997),
    ("310100", "上海市", "上海", "shanghai", "310000", 121.4737, 31.2304),
    ("420100", "武汉市", "武汉", "wuhan",    "420000", 114.3054, 30.5931),
    ("500100", "重庆市", "重庆", "chongqing","500000", 106.5516, 29.5630),
    ("440100", "广州市", "广州", "guangzhou","440000", 113.2644, 23.1291),
    ("510100", "成都市", "成都", "chengdu",  "510000", 104.0657, 30.6595),
    ("230100", "哈尔滨市","哈尔滨","haerbin", "230000", 126.5350, 45.8038),
    ("120100", "天津市", "天津", "tianjin",  "120000", 117.1901, 39.1256),
    ("370200", "青岛市", "青岛", "qingdao",  "370000", 120.3826, 36.0671),
    ("330100", "杭州市", "杭州", "hangzhou", "330000", 120.1551, 30.2741),
    ("360100", "南昌市", "南昌", "nanchang", "360000", 115.8581, 28.6820),
    ("430100", "长沙市", "长沙", "changsha", "430000", 112.9388, 28.2278),
    ("350200", "厦门市", "厦门", "xiamen",   "350000", 118.1000, 24.4797),
    ("410100", "郑州市", "郑州", "zhengzhou","410000", 113.6254, 34.7466),
]


# ─────────────────────────────────────────────────
# 2. 货品体系
# ─────────────────────────────────────────────────

COMMODITY_DATA = [
    {
        "name": "散货", "code": "BULK",
        "description": "散装干货，包括矿石、粮食、煤炭等",
        "types": [
            {
                "name": "矿石类", "code": "BULK_ORE",
                "standards": [
                    {"name": "铁矿石", "code": "IRON_ORE",   "commodity_class": "散货", "density": "2.50", "loading_method": "抓斗"},
                    {"name": "铜矿石", "code": "COPPER_ORE",  "commodity_class": "散货", "density": "2.00", "loading_method": "抓斗"},
                    {"name": "锰矿石", "code": "MANGAN_ORE",  "commodity_class": "散货", "density": "1.80", "loading_method": "抓斗"},
                ],
            },
            {
                "name": "煤炭类", "code": "BULK_COAL",
                "standards": [
                    {"name": "动力煤", "code": "STEAM_COAL",  "commodity_class": "散货", "density": "0.85", "loading_method": "皮带传输"},
                    {"name": "焦煤",   "code": "COKING_COAL", "commodity_class": "散货", "density": "0.90", "loading_method": "皮带传输"},
                ],
            },
            {
                "name": "粮食类", "code": "BULK_GRAIN",
                "standards": [
                    {"name": "大豆",   "code": "SOYBEAN",     "commodity_class": "散货", "density": "0.72", "loading_method": "气力输送"},
                    {"name": "玉米",   "code": "CORN",         "commodity_class": "散货", "density": "0.75", "loading_method": "气力输送"},
                    {"name": "小麦",   "code": "WHEAT",        "commodity_class": "散货", "density": "0.78", "loading_method": "气力输送"},
                ],
            },
        ],
    },
    {
        "name": "液货", "code": "LIQUID",
        "description": "液态散装货物，包括石油制品、化工液体等",
        "types": [
            {
                "name": "石油制品", "code": "PETROLEUM",
                "standards": [
                    {"name": "汽油",   "code": "GASOLINE",    "commodity_class": "液体", "density": "0.73", "is_dangerous": 1, "loading_method": "管道输送"},
                    {"name": "柴油",   "code": "DIESEL",       "commodity_class": "液体", "density": "0.84", "is_dangerous": 1, "loading_method": "管道输送"},
                    {"name": "燃料油", "code": "FUEL_OIL",     "commodity_class": "液体", "density": "0.96", "is_dangerous": 1, "loading_method": "管道输送"},
                ],
            },
            {
                "name": "化工液体", "code": "CHEMICAL_LIQ",
                "standards": [
                    {"name": "甲醇",   "code": "METHANOL",    "commodity_class": "液体", "density": "0.79", "is_dangerous": 1, "loading_method": "管道输送"},
                    {"name": "液碱",   "code": "CAUSTIC_SODA", "commodity_class": "液体", "density": "1.53", "loading_method": "管道输送"},
                ],
            },
        ],
    },
    {
        "name": "集装箱货", "code": "CONTAINER",
        "description": "适合集装箱运输的货物",
        "types": [
            {
                "name": "日用品", "code": "DAILY_GOODS",
                "standards": [
                    {"name": "家电",   "code": "HOME_APPLIANCE", "commodity_class": "集装箱", "loading_method": "吊装"},
                    {"name": "服装",   "code": "CLOTHING",       "commodity_class": "集装箱", "loading_method": "吊装"},
                    {"name": "家具",   "code": "FURNITURE",      "commodity_class": "集装箱", "loading_method": "吊装"},
                ],
            },
        ],
    },
    {
        "name": "件杂货", "code": "GENERAL",
        "description": "不需要专用船舶的普通货物",
        "types": [
            {
                "name": "建材类", "code": "BUILD_MAT",
                "standards": [
                    {"name": "钢材",   "code": "STEEL",          "commodity_class": "件杂", "density": "7.85", "loading_method": "吊装"},
                    {"name": "水泥",   "code": "CEMENT",          "commodity_class": "件杂", "density": "1.50", "loading_method": "人工/抓斗"},
                    {"name": "砂石",   "code": "SAND_GRAVEL",     "commodity_class": "件杂", "density": "1.60", "loading_method": "抓斗"},
                ],
            },
        ],
    },
]


# ─────────────────────────────────────────────────
# 3. 货源测试记录模板
# ─────────────────────────────────────────────────
# 会在脚本中结合真实 commodity_id 和 admin_code 动态生成

FREIGHT_TEMPLATES = [
    # (origin_code, dest_code, commodity_code, tonnage, freight_price, price_type, contact_person, contact_phone)
    ("420100", "310100", "IRON_ORE",     5000,  38.5, 1, "王建国", "13800138001"),
    ("500100", "420100", "STEAM_COAL",   8000,  42.0, 1, "李明",   "13900139002"),
    ("320100", "310100", "SOYBEAN",      2000,  55.0, 1, "张伟",   "13700137003"),
    ("430100", "320100", "STEEL",        3500,  68.0, 1, "陈刚",   "13600136004"),
    ("440100", "420100", "GASOLINE",     4000, 120.0, 1, "赵磊",   "13500135005"),
    ("310100", "230100", "CLOTHING",     1200,  95.0, 1, "孙芳",   "13400134006"),
    ("120100", "310100", "DIESEL",       6000, 115.0, 1, "周杰",   "13300133007"),
    ("320500", "330100", "HOME_APPLIANCE",800, 180.0, 3, "吴丽",   "13200132008"),
    ("360100", "310100", "CORN",         3000,  48.0, 1, "郑文",   "13100131009"),
    ("420100", "500100", "COKING_COAL",  7000,  45.0, 1, "王勇",   "13000130010"),
    ("310100", "440100", "FURNITURE",    600,  220.0, 3, "陈静",   "18800188011"),
    ("320600", "420100", "CEMENT",       4500,  35.0, 1, "刘洋",   "18700187012"),
    ("410100", "320100", "SAND_GRAVEL",  9000,  28.0, 1, "张军",   "18600186013"),
    ("500100", "310100", "IRON_ORE",     6000,  52.0, 1, "李华",   "18500185014"),
    ("430100", "440100", "METHANOL",     2500, 130.0, 1, "赵伟",   "18400184015"),
    ("420100", "320100", "WHEAT",        4000,  50.0, 1, "孙强",   "18300183016"),
    ("310100", "320100", "COPPER_ORE",   3000,  65.0, 1, "周丽",   "18200182017"),
    ("330100", "310100", "SOYBEAN",      1800,  58.0, 1, "吴涛",   "18100181018"),
    ("370200", "310100", "STEEL",        5000,  72.0, 1, "郑红",   "13811138119"),
    ("350200", "440100", "HOME_APPLIANCE",950, 190.0, 3, "王静",   "13711137120"),
    ("420100", "410100", "STEAM_COAL",   10000, 40.0, 1, "刘明",   "13611136121"),
    ("500100", "430100", "IRON_ORE",     4500,  55.0, 1, "陈强",   "13511135122"),
    ("320100", "420100", "GASOLINE",     3500, 125.0, 1, "张磊",   "13411134123"),
    ("310100", "500100", "CORN",         2800,  52.0, 1, "李芳",   "13311133124"),
    ("440100", "310100", "CAUSTIC_SODA", 1500, 145.0, 1, "赵洋",   "13211132125"),
    ("230100", "310100", "CLOTHING",     700,  200.0, 3, "孙军",   "13111131126"),
    ("120100", "420100", "DIESEL",       5500, 118.0, 1, "周涛",   "13011130127"),
    ("360100", "420100", "CEMENT",       6000,  32.0, 1, "吴强",   "18911189128"),
    ("320100", "330100", "MANGAN_ORE",   2200,  70.0, 1, "郑磊",   "18811188129"),
    ("410100", "440100", "FUEL_OIL",     4000, 110.0, 1, "王伟",   "18711187130"),
]


async def seed_admin_regions(db) -> dict:
    """写入主要港口城市行政区划，返回 {code: id} 映射"""
    from sqlalchemy import select
    from app.models.address import AdminRegion

    code_to_id = {}
    for city in CITIES:
        code, name, short_name, pinyin, parent_code, lng, lat = city
        res = await db.execute(select(AdminRegion).where(AdminRegion.code == code))
        obj = res.scalar_one_or_none()
        if not obj:
            obj = AdminRegion(
                code=code,
                name=name,
                short_name=short_name,
                pinyin=pinyin,
                level=2,
                parent_code=parent_code,
                longitude=lng,
                latitude=lat,
                sort_order=0,
                status=1,
            )
            db.add(obj)
            await db.flush()
            logger.info(f"[seed_cargo] admin_region created: {name}")
        code_to_id[code] = obj.id
    return code_to_id


async def seed_commodities(db) -> dict:
    """写入货品体系，返回 {standard_code: id} 映射"""
    from sqlalchemy import select
    from app.models.cargo import (
        CommodityCategory, CommodityType, CommodityStandard
    )
    from decimal import Decimal

    standard_map = {}  # {code: id}

    for cat_data in COMMODITY_DATA:
        # 货品大类
        res = await db.execute(
            select(CommodityCategory).where(CommodityCategory.code == cat_data["code"])
        )
        cat = res.scalar_one_or_none()
        if not cat:
            cat = CommodityCategory(
                code=cat_data["code"],
                name=cat_data["name"],
                description=cat_data.get("description"),
                sort_order=0,
                status=1,
                audit_status=1,  # 直接通过，测试数据不走审核
                submitter_id=1,
                auditor_id=1,
            )
            db.add(cat)
            await db.flush()
            logger.info(f"[seed_cargo] category: {cat.name}")

        for type_data in cat_data["types"]:
            # 货品类型
            res = await db.execute(
                select(CommodityType).where(CommodityType.code == type_data["code"])
            )
            ctype = res.scalar_one_or_none()
            if not ctype:
                ctype = CommodityType(
                    category_id=cat.id,
                    code=type_data["code"],
                    name=type_data["name"],
                    sort_order=0,
                    status=1,
                    audit_status=1,
                    submitter_id=1,
                    auditor_id=1,
                )
                db.add(ctype)
                await db.flush()

            for std_data in type_data["standards"]:
                # 标准货品
                res = await db.execute(
                    select(CommodityStandard).where(
                        CommodityStandard.code == std_data["code"]
                    )
                )
                std = res.scalar_one_or_none()
                if not std:
                    std = CommodityStandard(
                        type_id=ctype.id,
                        code=std_data["code"],
                        name=std_data["name"],
                        commodity_class=std_data.get("commodity_class"),
                        density=Decimal(str(std_data["density"])) if std_data.get("density") else None,
                        is_dangerous=std_data.get("is_dangerous", 0),
                        loading_method=std_data.get("loading_method"),
                        sort_order=0,
                        status=1,
                        audit_status=1,
                        submitter_id=1,
                        auditor_id=1,
                    )
                    db.add(std)
                    await db.flush()
                    logger.info(f"[seed_cargo] standard: {std.name}")
                standard_map[std_data["code"]] = std.id

    return standard_map


async def seed_cargo_freights(db, standard_map: dict) -> int:
    """写入 30 条货源记录，跨越最近 7 天，返回写入条数"""
    from sqlalchemy import select
    from app.models.cargo import CargoFreight

    today = date.today()
    count = 0

    for i, tmpl in enumerate(FREIGHT_TEMPLATES):
        (origin_code, dest_code, commodity_code,
         tonnage, freight_price, price_type,
         contact_person, contact_phone) = tmpl

        freight_date = today - timedelta(days=(i % 7))
        freight_no = f"CS-{freight_date.strftime('%Y%m%d')}-TEST{i+1:04d}"

        res = await db.execute(
            select(CargoFreight).where(CargoFreight.freight_no == freight_no)
        )
        if res.scalar_one_or_none():
            count += 1  # 已存在，跳过
            continue

        # 根据城市代码获取城市名
        city_name_map = {c[0]: c[1] for c in CITIES}
        origin_name = city_name_map.get(origin_code, origin_code)
        dest_name = city_name_map.get(dest_code, dest_code)

        commodity_id = standard_map.get(commodity_code)

        freight = CargoFreight(
            freight_no=freight_no,
            source_type="MANUAL",
            status="CONFIRMED",
            origin_admin_code=origin_code,
            origin_admin_name=origin_name,
            origin_raw_text=f"{origin_name}码头",
            origin_precision="CITY",
            dest_admin_code=dest_code,
            dest_admin_name=dest_name,
            dest_raw_text=f"{dest_name}码头",
            dest_precision="CITY",
            commodity_id=commodity_id,
            commodity_text=commodity_code,
            tonnage=tonnage,
            loading_date=freight_date,
            expire_date=freight_date + timedelta(days=7),
            freight_price=freight_price,
            price_type=price_type,
            price_unit="元/吨" if price_type == 1 else "元/单",
            contact_person=contact_person,
            contact_phone=contact_phone,
            collector_id=2,
            submitter_id=2,
            audit_status=1,  # 已审核通过
            auditor_id=1,
            deleted_at=None,
        )
        db.add(freight)
        await db.flush()
        count += 1

    logger.info(f"[seed_cargo] freights created/found: {count}")
    return count


async def seed_all_cargo() -> None:
    """货源测试数据全量写入入口"""
    from app.core.database import AsyncSessionLocal
    from app.tasks.stat_tasks import refresh_cargo_stats
    from datetime import timedelta

    async with AsyncSessionLocal() as db:
        try:
            print("=== 货源模块测试数据初始化开始 ===")

            # 1. 行政区划
            print("[1/4] 写入港口城市行政区划...")
            await seed_admin_regions(db)

            # 2. 货品体系
            print("[2/4] 写入货品大类/类型/标准...")
            standard_map = await seed_commodities(db)
            print(f"      标准货品共 {len(standard_map)} 条")

            # 3. 货源记录
            print("[3/4] 写入 30 条测试货源记录...")
            cnt = await seed_cargo_freights(db, standard_map)
            print(f"      写入货源记录 {cnt} 条")

            await db.commit()
            print("      数据库提交完成")

        except Exception as e:
            await db.rollback()
            print(f"[ERROR] 数据写入失败: {e}")
            raise

    # 4. 触发统计刷新（最近7天）
    print("[4/4] 触发统计聚合（最近 7 天）...")
    today = date.today()
    for i in range(7):
        stat_date = today - timedelta(days=i)
        await refresh_cargo_stats(stat_date)
        print(f"      统计完成: {stat_date}")

    print("=== 初始化完成 ===")
    print()
    print("可用账号：")
    print("  admin      密码: Admin@2026  角色: SUPER_ADMIN")
    print("  collector1 密码: Test@2026   角色: COLLECTOR")
    print()
    print("接口文档：http://localhost:8000/docs")


if __name__ == "__main__":
    import sys
    import os
    # 确保项目根目录在 sys.path 中
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    asyncio.run(seed_all_cargo())
