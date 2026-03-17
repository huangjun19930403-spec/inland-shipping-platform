"""航线数据体系模型"""
from sqlalchemy import (
    Column, BigInteger, Integer, String, Integer, SmallInteger,
    DECIMAL, DateTime, ForeignKey
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class ShippingRoute(Base):
    """商业航线表"""
    __tablename__ = "shipping_route"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(32), unique=True, nullable=False, comment="航线编码")
    name = Column(String(128), nullable=False, comment="航线名称")
    origin_region_id = Column(BigInteger, ForeignKey("region.id"), nullable=False, comment="起始区域")
    dest_region_id = Column(BigInteger, ForeignKey("region.id"), nullable=False, comment="目的区域")
    distance_km = Column(DECIMAL(10, 2), comment="航线距离(km)")
    duration_hours = Column(DECIMAL(8, 2), comment="标准航行时长(小时)")
    description = Column(String(512), comment="航线描述")
    sort_order = Column(Integer, nullable=False, default=0)
    status = Column(SmallInteger, nullable=False, default=1, comment="1=启用,0=停用")
    created_by = Column(BigInteger, comment="创建人ID")
    deleted_at = Column(DateTime, nullable=True, default=None, comment="软删时间，NULL=未删除")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    origin_region = relationship("Region", foreign_keys=[origin_region_id])
    dest_region = relationship("Region", foreign_keys=[dest_region_id])
    path_nodes = relationship("ShippingRoutePath", back_populates="route",
                              order_by="ShippingRoutePath.sequence")


class ShippingRoutePath(Base):
    """航线线路节点路径表（记录途经的真实航道节点序列）"""
    __tablename__ = "shipping_route_path"

    id = Column(Integer, primary_key=True, autoincrement=True)
    route_id = Column(BigInteger, ForeignKey("shipping_route.id"), nullable=False)
    node_id = Column(BigInteger, ForeignKey("transport_node.id"), nullable=False)
    sequence = Column(Integer, nullable=False, comment="序号（从1开始）")
    distance_from_start = Column(DECIMAL(10, 2), comment="距起点距离(km)")
    node_role = Column(String(32), default="WAYPOINT",
                       comment="START/WAYPOINT/END（路径节点角色）")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    route = relationship("ShippingRoute", back_populates="path_nodes")
    node = relationship("TransportNode")
