"""统计分析数据体系模型"""
from sqlalchemy import (
    Column, BigInteger, Integer, String, Integer, DECIMAL, DateTime, Date, ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class HeatmapStatDaily(Base):
    """热力统计日表（每日定时聚合生成）"""
    __tablename__ = "heatmap_stat_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stat_date = Column(Date, nullable=False, comment="统计日期")
    node_id = Column(BigInteger, ForeignKey("transport_node.id"), nullable=False, comment="运输节点ID")
    stat_type = Column(String(32), nullable=False,
                       comment="CARGO_ORIGIN=装货统计,CARGO_DEST=卸货统计,VESSEL=运力统计")
    # 货源统计指标
    cargo_count = Column(Integer, default=0, comment="货源数量")
    total_tonnage = Column(DECIMAL(16, 2), default=0, comment="总吨位(吨)")
    # 运力统计指标
    vessel_count = Column(Integer, default=0, comment="船舶数量")
    total_deadweight = Column(DECIMAL(16, 2), default=0, comment="总载重吨(DWT)")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("stat_date", "node_id", "stat_type", name="uk_heatmap_daily"),
    )

    node = relationship("TransportNode")
