"""统计分析数据体系模型

表设计原则：
  - 所有统计表均有 stat_date 维度 + 统计指标字段
  - 不允许分析接口直接查询业务表；统计数据由每日 ETL 任务生成
  - 索引覆盖常用查询维度（stat_date / region_id / commodity_id）
"""
from sqlalchemy import (
    Column, BigInteger, Integer, String, DECIMAL, DateTime, Date,
    ForeignKey, UniqueConstraint, Index, SmallInteger,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


# ─────────────────────────────────────────────────
# 货源热力统计日表
# ─────────────────────────────────────────────────

class CargoHeatmapDaily(Base):
    """货源热力统计日表
    来源：cargo_opportunity → 按节点聚合装/卸货数量
    """
    __tablename__ = "cargo_heatmap_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stat_date = Column(Date, nullable=False, comment="统计日期")
    node_id = Column(BigInteger, ForeignKey("transport_node.id"), nullable=False, comment="运输节点ID")
    stat_type = Column(
        String(16), nullable=False,
        comment="ORIGIN=装货节点, DEST=卸货节点",
    )
    cargo_count = Column(Integer, nullable=False, default=0, comment="货源数量")
    total_tonnage = Column(DECIMAL(16, 2), nullable=False, default=0, comment="总吨位(吨)")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("stat_date", "node_id", "stat_type", name="uk_cargo_heatmap_daily"),
        Index("ix_cargo_heatmap_date", "stat_date"),
        Index("ix_cargo_heatmap_node", "node_id"),
    )

    node = relationship("TransportNode")


# ─────────────────────────────────────────────────
# 船舶热力统计日表
# ─────────────────────────────────────────────────

class ShipHeatmapDaily(Base):
    """船舶热力统计日表
    来源：vessel_dynamic（AIS当前位置）→ 按节点聚合船舶数量与载重
    """
    __tablename__ = "ship_heatmap_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stat_date = Column(Date, nullable=False, comment="统计日期")
    node_id = Column(BigInteger, ForeignKey("transport_node.id"), nullable=False, comment="运输节点ID")
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
# 货源每日汇总统计表（用于趋势图）
# ─────────────────────────────────────────────────

class CargoStatDaily(Base):
    """货源每日汇总统计表
    来源：cargo_opportunity → 按日期汇总
    用途：货源趋势图、仪表盘核心指标
    """
    __tablename__ = "cargo_stat_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stat_date = Column(Date, nullable=False, unique=True, comment="统计日期（每日唯一）")
    total_count = Column(Integer, nullable=False, default=0, comment="当日新增货源总量")
    active_count = Column(Integer, nullable=False, default=0, comment="CONFIRMED状态货源数量")
    pending_count = Column(Integer, nullable=False, default=0, comment="PENDING状态货源数量")
    total_tonnage = Column(DECIMAL(18, 2), nullable=False, default=0, comment="当日新增总吨位(吨)")
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
    来源：cargo_opportunity → commodity_standard → commodity_type → commodity_category
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
# 区域货源分布统计
# ─────────────────────────────────────────────────

class CargoRegionStatDaily(Base):
    """区域货源分布统计日表
    来源：cargo_opportunity.origin_region_id / dest_region_id
    用途：区域货源分布占比 + 排名
    """
    __tablename__ = "cargo_region_stat_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stat_date = Column(Date, nullable=False, comment="统计日期")
    region_id = Column(BigInteger, ForeignKey("region.id"), nullable=False, comment="区域ID")
    region_name = Column(String(64), nullable=False, comment="区域名称（冗余存储）")
    stat_type = Column(String(8), nullable=False, comment="ORIGIN=货源发出, DEST=货源到达")
    cargo_count = Column(Integer, nullable=False, default=0, comment="货源数量")
    total_tonnage = Column(DECIMAL(16, 2), nullable=False, default=0, comment="总吨位(吨)")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("stat_date", "region_id", "stat_type", name="uk_cargo_region_stat"),
        Index("ix_cargo_region_stat_date", "stat_date"),
        Index("ix_cargo_region_stat_region", "region_id"),
    )

    region = relationship("Region")


# ─────────────────────────────────────────────────
# 区域运力分布统计
# ─────────────────────────────────────────────────

class ShipCapacityRegionDaily(Base):
    """区域运力分布统计日表
    来源：vessel + vessel_dynamic → transport_node.region_id
    用途：区域运力分布（船舶数量 + 总载重吨）
    """
    __tablename__ = "ship_capacity_region_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stat_date = Column(Date, nullable=False, comment="统计日期")
    region_id = Column(BigInteger, ForeignKey("region.id"), nullable=False, comment="区域ID")
    region_name = Column(String(64), nullable=False, comment="区域名称（冗余存储）")
    vessel_count = Column(Integer, nullable=False, default=0, comment="船舶数量")
    total_deadweight = Column(DECIMAL(16, 2), nullable=False, default=0, comment="总载重吨(DWT)")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("stat_date", "region_id", name="uk_ship_capacity_region"),
        Index("ix_ship_capacity_region_date", "stat_date"),
        Index("ix_ship_capacity_region_id", "region_id"),
    )

    region = relationship("Region")


# ─────────────────────────────────────────────────
# 船舶类型数量统计
# ─────────────────────────────────────────────────

class ShipTypeStatDaily(Base):
    """船舶类型数量统计日表
    来源：vessel → vessel_type_dict
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
    total_deadweight = Column(DECIMAL(16, 2), nullable=False, default=0, comment="总载重吨(DWT)")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("stat_date", "vessel_type_id", name="uk_ship_type_stat"),
        Index("ix_ship_type_stat_date", "stat_date"),
    )

    vessel_type = relationship("VesselTypeDict")


# ─────────────────────────────────────────────────
# 船龄分布统计
# ─────────────────────────────────────────────────

class ShipAgeStatDaily(Base):
    """船龄分布统计日表
    来源：vessel.build_year → 船龄 = 当前年 - build_year
    分组区间：0-5 / 5-10 / 10-15 / 15-20 / 20+
    用途：船龄分布直方图
    """
    __tablename__ = "ship_age_stat_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stat_date = Column(Date, nullable=False, comment="统计日期")
    age_group = Column(
        String(8), nullable=False,
        comment="船龄分组：0-5 / 5-10 / 10-15 / 15-20 / 20+",
    )
    vessel_count = Column(Integer, nullable=False, default=0, comment="该船龄段船舶数量")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("stat_date", "age_group", name="uk_ship_age_stat"),
        Index("ix_ship_age_stat_date", "stat_date"),
    )
