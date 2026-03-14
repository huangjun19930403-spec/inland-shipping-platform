"""
中国内河航运数据采集与分析平台 — 后端主入口
AI 融合架构 · FastAPI + SQLAlchemy Async + Claude AI

启动方式:
    uvicorn main:app --reload --host 0.0.0.0 --port 8000

文档地址:
    http://localhost:8000/docs       (Swagger UI)
    http://localhost:8000/redoc      (ReDoc)
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import init_db
from app.api.v1 import api_router
from app.tasks.scheduler import setup_scheduler, shutdown_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("inland")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化DB + 定时任务，关闭时优雅退出"""
    logger.info("=== 内河航运平台启动中 ===")
    await init_db()
    logger.info("数据库初始化完成")

    # 初始化基础数据（首次启动）
    await _seed_initial_data()
    logger.info("基础数据初始化完成")

    setup_scheduler()

    yield

    shutdown_scheduler()
    logger.info("=== 内河航运平台已停止 ===")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
## 中国内河航运数据采集与分析平台 API

### AI 融合架构

本平台以 **AI 为核心驱动力**，围绕以下能力构建：

- 🤖 **AI 货源解析**：粘贴微信群原始文本，Claude AI 自动提取结构化信息
- 🔍 **智能地址匹配**：模糊匹配别名库，支持多种写法识别
- 📊 **热力分析**：货源分布 & 运力分布空间可视化
- 🔄 **自动统计聚合**：定时任务自动生成每日热力数据

### 用户角色

| 角色 | 代码 | 权限 |
|------|------|------|
| 超级管理员 | SUPER_ADMIN | 全部权限，可自审 |
| 管理员 | ADMIN | 审核权限 + 数据管理 |
| 运营人员 | OPERATOR | 数据录入 + 部分管理 |
| 数据采集员 | COLLECTOR | 货源采集 + 数据查看 |
    """,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册所有路由
app.include_router(api_router, prefix="/api/v1")


@app.get("/", tags=["健康检查"])
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health", tags=["健康检查"])
async def health():
    return {"status": "ok"}


# ── 初始化基础数据 ────────────────────────────────────────────────────────────

async def _seed_initial_data():
    """首次启动时写入基础数据（幂等操作）"""
    from app.core.database import AsyncSessionLocal
    from app.models.system import SysUser, SysRole, SysUserRole
    from app.core.security import get_password_hash
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        # 角色
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
            role_map[rd["code"]] = role

        # 超级管理员账号
        res = await db.execute(select(SysUser).where(SysUser.username == "admin"))
        admin = res.scalar_one_or_none()
        if not admin:
            admin = SysUser(
                username="admin",
                real_name="系统管理员",
                password_hash=get_password_hash("Admin@2026"),
                department="系统",
                status=1,
            )
            db.add(admin)
            await db.flush()
            db.add(SysUserRole(user_id=admin.id, role_id=role_map["SUPER_ADMIN"].id))

        # 测试采集员账号
        res = await db.execute(select(SysUser).where(SysUser.username == "collector1"))
        c = res.scalar_one_or_none()
        if not c:
            c = SysUser(
                username="collector1",
                real_name="张采集",
                password_hash=get_password_hash("Test@2026"),
                department="数据部",
                status=1,
            )
            db.add(c)
            await db.flush()
            db.add(SysUserRole(user_id=c.id, role_id=role_map["COLLECTOR"].id))

        await _seed_address_data(db)
        await _seed_commodity_data(db)
        await _seed_vessel_type_data(db)
        await db.commit()


async def _seed_address_data(db):
    """写入地址基础数据"""
    from app.models.address import Waterway, Region, NodeType, TransportNode, NodeAlias
    from sqlalchemy import select

    # 水系
    waterways = [
        {"code": "CJ",  "name": "长江", "level": 1, "sort_order": 1},
        {"code": "JHY", "name": "京杭运河", "level": 3, "sort_order": 2},
        {"code": "HH",  "name": "淮河", "level": 1, "sort_order": 3},
        {"code": "ZJ",  "name": "珠江", "level": 1, "sort_order": 4},
        {"code": "GJ",  "name": "赣江", "level": 2, "sort_order": 5},
        {"code": "XJ",  "name": "湘江", "level": 2, "sort_order": 6},
        {"code": "HJ",  "name": "汉江", "level": 2, "sort_order": 7},
        {"code": "MSJ", "name": "岷沱江", "level": 2, "sort_order": 8},
    ]
    ww_map: dict[str, Waterway] = {}
    for wd in waterways:
        res = await db.execute(select(Waterway).where(Waterway.code == wd["code"]))
        ww = res.scalar_one_or_none()
        if not ww:
            ww = Waterway(**wd, status=1)
            db.add(ww)
            await db.flush()
        ww_map[wd["code"]] = ww

    # 区域
    regions_data = [
        {"code": "SN",  "name": "苏南区域",   "sort_order": 1},
        {"code": "SZ",  "name": "苏中区域",   "sort_order": 2},
        {"code": "SB",  "name": "苏北区域",   "sort_order": 3},
        {"code": "AJ",  "name": "皖江区域",   "sort_order": 4},
        {"code": "AB",  "name": "皖北区域",   "sort_order": 5},
        {"code": "GB",  "name": "赣北区域",   "sort_order": 6},
        {"code": "HD",  "name": "鄂东区域",   "sort_order": 7},
        {"code": "XB",  "name": "湘北区域",   "sort_order": 8},
        {"code": "ZB",  "name": "浙北区域",   "sort_order": 9},
        {"code": "SH",  "name": "沪上区域",   "sort_order": 10},
        {"code": "SDY", "name": "山东运河区域", "sort_order": 11},
        {"code": "RZS", "name": "渝川区域",   "sort_order": 12},
        {"code": "PSJ", "name": "珠三角区域", "sort_order": 13},
    ]
    region_map: dict[str, Region] = {}
    for rd in regions_data:
        res = await db.execute(select(Region).where(Region.code == rd["code"]))
        region = res.scalar_one_or_none()
        if not region:
            region = Region(**rd, status=1)
            db.add(region)
            await db.flush()
        region_map[rd["code"]] = region

    # 节点类型
    node_types = [
        {"code": "PORT",       "name": "港口",           "sort_order": 1},
        {"code": "WHARF",      "name": "码头",           "sort_order": 2},
        {"code": "ANCHOR",     "name": "锚地",           "sort_order": 3},
        {"code": "LOCK",       "name": "船闸",           "sort_order": 4},
        {"code": "LOGISTICS",  "name": "物流园",         "sort_order": 5},
        {"code": "RAILWAY",    "name": "铁路站",         "sort_order": 6, "transport_mode": "RAILWAY"},
        {"code": "HIGHWAY",    "name": "公路枢纽",       "sort_order": 7, "transport_mode": "HIGHWAY"},
        {"code": "MULTIMODAL", "name": "多式联运枢纽",   "sort_order": 8, "transport_mode": "MULTIMODAL"},
    ]
    nt_map: dict[str, NodeType] = {}
    for ntd in node_types:
        res = await db.execute(select(NodeType).where(NodeType.code == ntd["code"]))
        nt = res.scalar_one_or_none()
        if not nt:
            # transport_mode may already be in ntd dict
            nt = NodeType(**{**{"transport_mode": "WATERWAY"}, **ntd, "status": 1})
            db.add(nt)
            await db.flush()
        nt_map[ntd["code"]] = nt

    # 重要运输节点（长三角、长江沿线）
    nodes_data = [
        {
            "code": "NJG",  "name": "南京港",
            "node_type_id": nt_map["PORT"].id, "node_category": 4,
            "waterway_id": ww_map["CJ"].id, "region_id": region_map["SN"].id,
            "province": "江苏", "city": "南京",
            "longitude": 118.7969, "latitude": 32.0603,
            "node_level": 1, "is_hot_node": 1, "audit_status": 1,
        },
        {
            "code": "LTG",  "name": "龙潭港",
            "node_type_id": nt_map["WHARF"].id, "node_category": 4,
            "waterway_id": ww_map["CJ"].id, "region_id": region_map["SN"].id,
            "province": "江苏", "city": "南京",
            "longitude": 119.0481, "latitude": 32.1352,
            "node_level": 2, "is_hot_node": 1, "audit_status": 1,
        },
        {
            "code": "WHG",  "name": "武汉港",
            "node_type_id": nt_map["PORT"].id, "node_category": 4,
            "waterway_id": ww_map["CJ"].id, "region_id": region_map["HD"].id,
            "province": "湖北", "city": "武汉",
            "longitude": 114.3162, "latitude": 30.5928,
            "node_level": 1, "is_hot_node": 1, "audit_status": 1,
        },
        {
            "code": "CQG",  "name": "重庆港",
            "node_type_id": nt_map["PORT"].id, "node_category": 4,
            "waterway_id": ww_map["CJ"].id, "region_id": region_map["RZS"].id,
            "province": "重庆", "city": "重庆",
            "longitude": 106.5516, "latitude": 29.5630,
            "node_level": 1, "is_hot_node": 1, "audit_status": 1,
        },
        {
            "code": "SHSG", "name": "上海港",
            "node_type_id": nt_map["PORT"].id, "node_category": 4,
            "waterway_id": ww_map["CJ"].id, "region_id": region_map["SH"].id,
            "province": "上海", "city": "上海",
            "longitude": 121.5070, "latitude": 31.2304,
            "node_level": 1, "is_hot_node": 1, "audit_status": 1,
        },
        {
            "code": "AHG",  "name": "安庆港",
            "node_type_id": nt_map["PORT"].id, "node_category": 4,
            "waterway_id": ww_map["CJ"].id, "region_id": region_map["AJ"].id,
            "province": "安徽", "city": "安庆",
            "longitude": 117.0531, "latitude": 30.5130,
            "node_level": 2, "is_hot_node": 1, "audit_status": 1,
        },
        {
            "code": "YCG",  "name": "宜昌港",
            "node_type_id": nt_map["PORT"].id, "node_category": 4,
            "waterway_id": ww_map["CJ"].id, "region_id": region_map["HD"].id,
            "province": "湖北", "city": "宜昌",
            "longitude": 111.2865, "latitude": 30.6916,
            "node_level": 2, "is_hot_node": 1, "audit_status": 1,
        },
        {
            "code": "JJG",  "name": "九江港",
            "node_type_id": nt_map["PORT"].id, "node_category": 4,
            "waterway_id": ww_map["CJ"].id, "region_id": region_map["GB"].id,
            "province": "江西", "city": "九江",
            "longitude": 115.9917, "latitude": 29.7057,
            "node_level": 2, "is_hot_node": 1, "audit_status": 1,
        },
        {
            "code": "YZG",  "name": "扬州港",
            "node_type_id": nt_map["PORT"].id, "node_category": 4,
            "waterway_id": ww_map["JHY"].id, "region_id": region_map["SZ"].id,
            "province": "江苏", "city": "扬州",
            "longitude": 119.4127, "latitude": 32.3943,
            "node_level": 2, "is_hot_node": 1, "audit_status": 1,
        },
        {
            "code": "ZJG",  "name": "镇江港",
            "node_type_id": nt_map["PORT"].id, "node_category": 4,
            "waterway_id": ww_map["CJ"].id, "region_id": region_map["SN"].id,
            "province": "江苏", "city": "镇江",
            "longitude": 119.4551, "latitude": 32.1875,
            "node_level": 2, "is_hot_node": 1, "audit_status": 1,
        },
    ]
    for nd in nodes_data:
        res = await db.execute(select(TransportNode).where(TransportNode.code == nd["code"]))
        if not res.scalar_one_or_none():
            node = TransportNode(**nd, status=1, sort_order=0)
            db.add(node)
            await db.flush()
            # 自动创建标准名别名
            alias = NodeAlias(
                node_id=node.id, alias_name=node.name,
                alias_type="SYSTEM", priority=100, status=1,
            )
            db.add(alias)


async def _seed_commodity_data(db):
    """写入货品基础数据"""
    from app.models.cargo import (
        CommodityCategory, CommodityType, CommodityStandard, CommodityAlias
    )
    from sqlalchemy import select

    # 大类
    cats_data = [
        {"name": "干散货", "code": "DRY",    "sort_order": 1},
        {"name": "液体散货", "code": "LIQUID","sort_order": 2},
        {"name": "件杂货", "code": "BREAK",  "sort_order": 3},
        {"name": "集装箱货", "code": "CTN",  "sort_order": 4},
        {"name": "特种货", "code": "SPECIAL","sort_order": 5},
    ]
    cat_map: dict[str, CommodityCategory] = {}
    for cd in cats_data:
        res = await db.execute(select(CommodityCategory).where(CommodityCategory.code == cd["code"]))
        cat = res.scalar_one_or_none()
        if not cat:
            cat = CommodityCategory(**cd, status=1, audit_status=1)
            db.add(cat)
            await db.flush()
        cat_map[cd["code"]] = cat

    # 类型 + 标准货品
    types_and_standards = [
        # 干散货
        {"type": {"category_id": cat_map["DRY"].id, "name": "煤炭类", "code": "COAL", "sort_order": 1},
         "standards": [
             {"name": "动力煤", "aliases": ["电煤", "煤炭", "煤", "火电煤", "动力用煤"]},
             {"name": "焦煤",   "aliases": ["炼焦煤", "主焦煤"]},
             {"name": "无烟煤", "aliases": ["白煤", "硬煤"]},
         ]},
        {"type": {"category_id": cat_map["DRY"].id, "name": "矿石类", "code": "ORE", "sort_order": 2},
         "standards": [
             {"name": "铁矿石", "aliases": ["铁矿", "铁砂", "铁粉"]},
             {"name": "锰矿石", "aliases": ["锰矿", "锰砂"]},
             {"name": "铜矿石", "aliases": ["铜矿", "铜精矿"]},
         ]},
        {"type": {"category_id": cat_map["DRY"].id, "name": "砂石类", "code": "SAND", "sort_order": 3},
         "standards": [
             {"name": "河砂",   "aliases": ["江砂", "黄砂", "砂子", "机制砂"]},
             {"name": "碎石",   "aliases": ["石子", "瓜子片", "石碴"]},
             {"name": "建筑砂", "aliases": ["砂", "细骨料"]},
         ]},
        {"type": {"category_id": cat_map["DRY"].id, "name": "粮食类", "code": "GRAIN", "sort_order": 4},
         "standards": [
             {"name": "大豆", "aliases": ["豆子", "黄豆", "毛豆"]},
             {"name": "玉米", "aliases": ["苞谷", "棒子"]},
             {"name": "小麦", "aliases": ["麦子", "冬小麦"]},
             {"name": "稻谷", "aliases": ["稻", "大米原料", "水稻"]},
         ]},
        {"type": {"category_id": cat_map["DRY"].id, "name": "钢铁类", "code": "STEEL", "sort_order": 5},
         "standards": [
             {"name": "钢材",   "aliases": ["螺纹钢", "线材", "型钢", "钢筋"]},
             {"name": "生铁",   "aliases": ["铁块", "铸铁"]},
             {"name": "废钢",   "aliases": ["废铁", "废旧钢铁"]},
         ]},
        # 液体散货
        {"type": {"category_id": cat_map["LIQUID"].id, "name": "油品类", "code": "OIL", "sort_order": 1},
         "standards": [
             {"name": "成品油", "aliases": ["汽油", "柴油", "油品"]},
             {"name": "原油",   "aliases": ["毛油", "混合原油"]},
             {"name": "化工液体", "aliases": ["化工品", "液体化工"]},
         ]},
    ]

    for item in types_and_standards:
        td = item["type"]
        res = await db.execute(
            select(CommodityType).where(
                CommodityType.category_id == td["category_id"],
                CommodityType.code == td["code"]
            )
        )
        ctype = res.scalar_one_or_none()
        if not ctype:
            ctype = CommodityType(**td, status=1, audit_status=1)
            db.add(ctype)
            await db.flush()

        for sd in item["standards"]:
            res = await db.execute(
                select(CommodityStandard).where(
                    CommodityStandard.type_id == ctype.id,
                    CommodityStandard.name == sd["name"]
                )
            )
            std = res.scalar_one_or_none()
            if not std:
                std = CommodityStandard(
                    type_id=ctype.id, name=sd["name"],
                    status=1, audit_status=1,
                )
                db.add(std)
                await db.flush()
                # 写入别名（含标准名本身）
                for idx, aname in enumerate([sd["name"]] + sd["aliases"]):
                    res2 = await db.execute(
                        select(CommodityAlias).where(CommodityAlias.alias_name == aname)
                    )
                    if not res2.scalar_one_or_none():
                        db.add(CommodityAlias(
                            commodity_id=std.id,
                            alias_name=aname,
                            alias_type="SYSTEM" if idx == 0 else "COMMON",
                            priority=100 if idx == 0 else (50 - idx),
                            status=1,
                        ))


async def _seed_vessel_type_data(db):
    """写入船舶类型基础数据"""
    from app.models.vessel import VesselTypeDict
    from sqlalchemy import select

    types = [
        {"code": "BC",  "name": "散货船",     "sort_order": 1},
        {"code": "TC",  "name": "油船",       "sort_order": 2},
        {"code": "CC",  "name": "集装箱船",   "sort_order": 3},
        {"code": "GC",  "name": "件杂货船",   "sort_order": 4},
        {"code": "PB",  "name": "推驳船",     "sort_order": 5},
        {"code": "SB",  "name": "自卸船",     "sort_order": 6},
        {"code": "RO",  "name": "滚装船",     "sort_order": 7},
        {"code": "TG",  "name": "拖轮",       "sort_order": 8},
        {"code": "BG",  "name": "驳船",       "sort_order": 9},
        {"code": "CHM", "name": "化学品船",   "sort_order": 10},
        {"code": "LNG", "name": "液化气船",   "sort_order": 11},
        {"code": "CEM", "name": "水泥船",     "sort_order": 12},
        {"code": "SND", "name": "采砂船",     "sort_order": 13},
    ]
    for td in types:
        res = await db.execute(select(VesselTypeDict).where(VesselTypeDict.code == td["code"]))
        if not res.scalar_one_or_none():
            db.add(VesselTypeDict(**td, status=1, audit_status=1))
