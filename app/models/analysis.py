"""统计分析数据体系模型

表设计原则：
  - 货源统计表由写入事件驱动实时刷新
  - 船舶统计表采用快照模式，事件驱动全量替换刷新（无日期分片）
  - 分析接口只读统计表，响应时间目标 < 200ms

货源统计表（5张）：
  cargo_city_heatmap         — 货源城市热力
  cargo_stat_daily           — 货源每日汇总（趋势图 + 仪表盘）
  cargo_commodity_stat_daily — 货品大类货源排名
  cargo_od_daily             — 起终点城市OD流量矩阵
  cargo_channel_daily        — 各录入渠道质量统计

船舶统计表（4张，快照模式）：
  ship_stat_region  — 航运商业区域热力快照（Region 表，有多边形边界）
  ship_stat_city    — 城市级热力快照（admin_region，质心坐标）
  ship_stat_dwt     — 载重吨区间分布快照（来自 vessel.deadweight）
  ship_stat_age     — 船龄区间分布快照（来自 vessel.build_year）
"""
from sqlalchemy import (
    Column, BigInteger, Integer, String, DECIMAL, DateTime, Date,
    ForeignKey, UniqueConstraint, Index, JSON,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


# ─────────────────────────────────────────────────
# 货源城市热力统计表
# ─────────────────────────────────────────────────

class CargoCityHeatmap(Base):
    """货源城市热力统计表

    来源：cargo_freight → 按 origin_admin_code / dest_admin_code 城市聚合
    刷新：写入事件驱动，货源创建/状态变更后立即更新
    用途：城市热力地图渲染
    """
    __tablename__ = "cargo_city_heatmap"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stat_date = Column(Date, nullable=False, comment="统计日期")
    city_code = Column(String(12), nullable=False, comment="城市行政区划代码")
    city_name = Column(String(50), nullable=False, comment="城市名称（冗余）")
    city_longitude = Column(DECIMAL(11, 8), nullable=True, comment="城市中心经度（来自admin_region）")
    city_latitude = Column(DECIMAL(10, 8), nullable=True, comment="城市中心纬度（来自admin_region）")
    stat_type = Column(String(8), nullable=False,
                       comment="ORIGIN=装货城市热力, DEST=卸货城市热力")
    cargo_count = Column(Integer, nullable=False, default=0, comment="货源数量")
    total_tonnage = Column(DECIMAL(16, 2), nullable=False, default=0, comment="总吨位(吨)")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("stat_date", "city_code", "stat_type", name="uk_cargo_city_heatmap"),
        Index("ix_cargo_city_heatmap_date", "stat_date"),
        Index("ix_cargo_city_heatmap_city", "city_code"),
    )


# ─────────────────────────────────────────────────
# 货源每日汇总统计表
# ─────────────────────────────────────────────────

class CargoStatDaily(Base):
    """货源每日汇总统计表
    来源：cargo_freight → 按日期汇总
    刷新：写入事件驱动
    用途：货源趋势图、仪表盘核心指标
    """
    __tablename__ = "cargo_stat_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stat_date = Column(Date, nullable=False, unique=True, comment="统计日期（每日唯一）")
    total_count = Column(Integer, nullable=False, default=0, comment="当日新增货源总量")
    confirmed_count = Column(Integer, nullable=False, default=0,
                             comment="CONFIRMED状态货源数量")
    pending_count = Column(Integer, nullable=False, default=0,
                           comment="PENDING状态货源数量")
    total_tonnage = Column(DECIMAL(18, 2), nullable=False, default=0,
                           comment="当日新增总吨位(吨)")
    avg_tonnage = Column(DECIMAL(12, 2), nullable=False, default=0,
                         comment="平均吨位(吨)")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_cargo_stat_date", "stat_date"),
    )


# ─────────────────────────────────────────────────
# 货品分类货源数量统计
# ─────────────────────────────────────────────────

class CargoCommodityStatDaily(Base):
    """货品分类货源统计日表
    来源：cargo_freight → commodity_standard → commodity_type → commodity_category
    刷新：写入事件驱动
    用途：货品分类排名图
    """
    __tablename__ = "cargo_commodity_stat_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stat_date = Column(Date, nullable=False, comment="统计日期")
    commodity_category_id = Column(
        BigInteger, ForeignKey("commodity_category.id"), nullable=False,
        comment="货品大类ID",
    )
    category_name = Column(String(64), nullable=False, comment="货品大类名称（冗余存储）")
    cargo_count = Column(Integer, nullable=False, default=0, comment="货源数量")
    total_tonnage = Column(DECIMAL(16, 2), nullable=False, default=0, comment="总吨位(吨)")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("stat_date", "commodity_category_id", name="uk_cargo_commodity_stat"),
        Index("ix_cargo_commodity_stat_date", "stat_date"),
        Index("ix_cargo_commodity_stat_cat", "commodity_category_id"),
    )

    commodity_category = relationship("CommodityCategory")


# ─────────────────────────────────────────────────
# 起终点城市OD流量矩阵
# ─────────────────────────────────────────────────

class CargoOdDaily(Base):
    """起终点城市OD流量统计日表

    来源：cargo_freight → 按 (origin_admin_code, dest_admin_code) 聚合
    刷新：写入事件驱动
    用途：OD流向 Sankey 图 / Top N 路线排行
    """
    __tablename__ = "cargo_od_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stat_date = Column(Date, nullable=False, comment="统计日期")
    origin_city_code = Column(String(12), nullable=False, comment="起点城市行政区划代码")
    origin_city_name = Column(String(50), nullable=False, comment="起点城市名称（冗余）")
    dest_city_code = Column(String(12), nullable=False, comment="终点城市行政区划代码")
    dest_city_name = Column(String(50), nullable=False, comment="终点城市名称（冗余）")
    cargo_count = Column(Integer, nullable=False, default=0, comment="货源数量")
    total_tonnage = Column(DECIMAL(16, 2), nullable=False, default=0, comment="总吨位(吨)")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("stat_date", "origin_city_code", "dest_city_code",
                         name="uk_cargo_od_daily"),
        Index("ix_cargo_od_date", "stat_date"),
        Index("ix_cargo_od_origin", "origin_city_code"),
    )


# ─────────────────────────────────────────────────
# 各录入渠道质量统计
# ─────────────────────────────────────────────────

class CargoChannelDaily(Base):
    """各录入渠道货源质量统计日表

    来源：cargo_freight + cargo_raw_message 聚合
    刷新：写入事件驱动
    用途：渠道贡献堆叠面积图 + 数据质量卡片
    """
    __tablename__ = "cargo_channel_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stat_date = Column(Date, nullable=False, comment="统计日期")
    source_type = Column(String(20), nullable=False, comment="TMS/WECHAT_AI/MANUAL")
    raw_msg_count = Column(Integer, nullable=False, default=0,
                           comment="原始消息/消费数量")
    parse_success_count = Column(Integer, nullable=False, default=0,
                                 comment="AI解析成功数量（WECHAT_AI专用）")
    confirmed_count = Column(Integer, nullable=False, default=0,
                             comment="最终确认货源数量")
    total_tonnage = Column(DECIMAL(16, 2), nullable=False, default=0,
                           comment="确认货源总吨位(吨)")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("stat_date", "source_type", name="uk_cargo_channel_daily"),
        Index("ix_cargo_channel_date", "stat_date"),
    )


# ═════════════════════════════════════════════════
# 船舶统计表（快照模式，事件驱动全量替换）
# ═════════════════════════════════════════════════

class ShipStatRegion(Base):
    """航运商业区域热力快照

    来源：vessel_dynamic → Region（多边形边界）
    归属逻辑：
      1. vessel_dynamic.current_region_id（精确）
      2. vessel_dynamic.current_node_id → region_address_relation（主归属）
      3. vessel_dynamic GPS → Region.boundary_coordinates 点在多边形内（Python射线法）
    刷新：Kafka AIS 更新触发（30s 节流）+ 管理员手动
    用途：区域热力地图（含多边形边界渲染）+ 区域运力对比
    """
    __tablename__ = "ship_stat_region"

    id = Column(Integer, primary_key=True, autoincrement=True)
    region_id = Column(BigInteger, nullable=False, comment="Region.id（冗余，无FK约束）")
    region_name = Column(String(64), nullable=False, comment="区域名称（冗余）")
    center_longitude = Column(DECIMAL(11, 8), nullable=True, comment="区域中心经度（冗余）")
    center_latitude = Column(DECIMAL(10, 8), nullable=True, comment="区域中心纬度（冗余）")
    boundary_coordinates = Column(JSON, nullable=True,
                                  comment="边界坐标 [[lng,lat],...]，冗余供前端绘图")
    vessel_count = Column(Integer, nullable=False, default=0, comment="区域内船舶总数")
    total_deadweight = Column(DECIMAL(16, 2), nullable=False, default=0,
                              comment="区域运力：合计载重吨(DWT)")
    ratio = Column(DECIMAL(6, 3), nullable=False, default=0,
                   comment="占全部有位置船舶的百分比")
    refreshed_at = Column(DateTime, nullable=True, comment="最近刷新时间")

    __table_args__ = (
        Index("ix_ship_stat_region_id", "region_id", unique=True),
    )


class ShipStatCity(Base):
    """城市级热力快照

    来源：vessel_dynamic.current_city_code / transport_node.city_code / GPS 最近质心
    归属逻辑：
      1. current_city_code（精确）
      2. current_node_id → transport_node.city_code（精确）
      3. 只有 GPS → 欧氏距离最近的 admin_region 市级质心（近似，内河场景可用）
    刷新：Kafka AIS 更新触发（30s 节流）+ 管理员手动
    用途：城市气泡热力地图（经纬度+数量权重）+ 省级聚合（服务层 GROUP BY province_name）
    """
    __tablename__ = "ship_stat_city"

    id = Column(Integer, primary_key=True, autoincrement=True)
    city_code = Column(String(12), nullable=False, comment="admin_region.code（冗余，无FK约束）")
    city_name = Column(String(64), nullable=False, comment="城市名称（冗余）")
    province_name = Column(String(64), nullable=True, comment="省份名称（冗余，用于省级聚合）")
    longitude = Column(DECIMAL(11, 8), nullable=True, comment="城市行政中心经度（来自admin_region）")
    latitude = Column(DECIMAL(10, 8), nullable=True, comment="城市行政中心纬度（来自admin_region）")
    vessel_count = Column(Integer, nullable=False, default=0, comment="该城市范围内船舶数量")
    total_deadweight = Column(DECIMAL(16, 2), nullable=False, default=0,
                              comment="城市运力：合计载重吨(DWT)")
    ratio = Column(DECIMAL(6, 3), nullable=False, default=0,
                   comment="占全部有位置船舶的百分比")
    refreshed_at = Column(DateTime, nullable=True, comment="最近刷新时间")

    __table_args__ = (
        Index("ix_ship_stat_city_code", "city_code", unique=True),
    )


class ShipStatDwt(Base):
    """载重吨区间分布快照

    来源：vessel.deadweight（静态档案）
    刷新：vessel CRUD / 批量导入触发
    用途：载重吨分布直方图 / 柱状图

    分桶：500吨以下 / 500-1000吨 / 1000-2000吨 / 2000-5000吨 / 5000吨以上 / 未录入
    """
    __tablename__ = "ship_stat_dwt"

    id = Column(Integer, primary_key=True, autoincrement=True)
    segment_label = Column(String(32), nullable=False,
                           comment="档位标签，如 '500-1000吨'")
    min_dwt = Column(Integer, nullable=True, comment="区间下限（NULL=无下限）")
    max_dwt = Column(Integer, nullable=True, comment="区间上限（NULL=无上限）")
    vessel_count = Column(Integer, nullable=False, default=0, comment="该区间船舶数量")
    ratio = Column(DECIMAL(6, 3), nullable=False, default=0,
                   comment="占全部有效船舶的百分比")
    refreshed_at = Column(DateTime, nullable=True, comment="最近刷新时间")

    __table_args__ = (
        Index("ix_ship_stat_dwt_label", "segment_label", unique=True),
    )


class ShipStatAge(Base):
    """船龄区间分布快照

    来源：vessel.build_year（静态档案）
    刷新：vessel CRUD / 批量导入触发
    用途：船龄分布直方图 / 柱状图

    分桶：5年以内 / 6-10年 / 11-15年 / 16-20年 / 20年以上 / 未知
    船龄计算：当前年份 - build_year
    """
    __tablename__ = "ship_stat_age"

    id = Column(Integer, primary_key=True, autoincrement=True)
    age_range_label = Column(String(32), nullable=False,
                             comment="船龄档位，如 '6-10年'")
    min_age = Column(Integer, nullable=True, comment="区间下限（NULL=无下限）")
    max_age = Column(Integer, nullable=True, comment="区间上限（NULL=无上限）")
    vessel_count = Column(Integer, nullable=False, default=0, comment="该区间船舶数量")
    ratio = Column(DECIMAL(6, 3), nullable=False, default=0,
                   comment="占全部有效船舶的百分比")
    refreshed_at = Column(DateTime, nullable=True, comment="最近刷新时间")

    __table_args__ = (
        Index("ix_ship_stat_age_label", "age_range_label", unique=True),
    )
