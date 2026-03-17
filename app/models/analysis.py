"""统计分析数据体系模型

表设计原则：
  - 货源统计表由写入事件驱动实时刷新（替换原每日 ETL 批处理）
  - 船舶统计表继续使用每日 02:00 定时任务刷新（AIS数据周期性）
  - 分析接口只读统计表，响应时间目标 < 200ms

货源统计表（4张）：
  cargo_city_heatmap         — 货源城市热力（替换原节点级 cargo_heatmap_daily）
  cargo_stat_daily           — 货源每日汇总（趋势图 + 仪表盘）
  cargo_commodity_stat_daily — 货品大类货源排名
  cargo_od_daily             — 起终点城市OD流量矩阵
  cargo_channel_daily        — 各录入渠道质量统计

船舶统计表（2张，保持不变）：
  ship_heatmap_daily         — 船舶热力（节点级，AIS位置）
  ship_type_stat_daily       — 船型数量占比
"""
from sqlalchemy import (
    Column, BigInteger, Integer, String, DECIMAL, DateTime, Date,
    ForeignKey, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


# ─────────────────────────────────────────────────
# 货源城市热力统计表（替换原节点级 cargo_heatmap_daily）
# ─────────────────────────────────────────────────

class CargoCityHeatmap(Base):
    """货源城市热力统计表

    来源：cargo_freight → 按 origin_admin_code / dest_admin_code 城市聚合
    刷新：写入事件驱动（非定时任务），货源创建/状态变更后立即更新
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
# 船舶热力统计日表（保持不变，节点级）
# ─────────────────────────────────────────────────

class ShipHeatmapDaily(Base):
    """船舶热力统计日表
    来源：vessel_dynamic（AIS当前位置）→ 按节点聚合船舶数量与载重
    刷新：每日 02:00 定时任务
    """
    __tablename__ = "ship_heatmap_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stat_date = Column(Date, nullable=False, comment="统计日期")
    node_id = Column(BigInteger, ForeignKey("transport_node.id"), nullable=False,
                     comment="运输节点ID")
    vessel_count = Column(Integer, nullable=False, default=0, comment="在港/在途船舶数量")
    total_deadweight = Column(DECIMAL(16, 2), nullable=False, default=0, comment="总载重吨(DWT)")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("stat_date", "node_id", name="uk_ship_heatmap_daily"),
        Index("ix_ship_heatmap_date", "stat_date"),
        Index("ix_ship_heatmap_node", "node_id"),
    )

    node = relationship("TransportNode")


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
    统计范围：仅 origin_admin_code 和 dest_admin_code 均不为空的记录
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

    字段说明：
    - raw_msg_count:       原始消息数（TMS 渠道为消费条数，MANUAL 渠道为 0）
    - parse_success_count: AI解析成功数（WECHAT_AI 专用，其他渠道为 0）
    - confirmed_count:     最终确认进入货源的数量
    """
    __tablename__ = "cargo_channel_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stat_date = Column(Date, nullable=False, comment="统计日期")
    source_type = Column(String(20), nullable=False,
                         comment="TMS/WECHAT_AI/MANUAL")
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


# ─────────────────────────────────────────────────
# 船舶类型数量统计（保持不变）
# ─────────────────────────────────────────────────

class ShipTypeStatDaily(Base):
    """船舶类型数量统计日表
    来源：vessel → vessel_type_dict
    刷新：每日 02:00 定时任务
    用途：船舶类型数量占比饼图
    """
    __tablename__ = "ship_type_stat_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stat_date = Column(Date, nullable=False, comment="统计日期")
    vessel_type_id = Column(
        BigInteger, ForeignKey("vessel_type_dict.id"), nullable=False,
        comment="船舶类型ID",
    )
    type_name = Column(String(64), nullable=False, comment="船舶类型名称（冗余存储）")
    vessel_count = Column(Integer, nullable=False, default=0, comment="船舶数量")
    total_deadweight = Column(DECIMAL(16, 2), nullable=False, default=0,
                              comment="总载重吨(DWT)")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("stat_date", "vessel_type_id", name="uk_ship_type_stat"),
        Index("ix_ship_type_stat_date", "stat_date"),
    )

    vessel_type = relationship("VesselTypeDict")
