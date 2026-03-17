"""航线数据体系模型

三层结构：
  ShippingRoute         — 航线（武汉→南京，抽象商业概念）
  ShippingRoutePath     — 路线方案（主航道/运河绕行线，同一航线下的并行路线）
  ShippingRoutePathNode — 路径节点（每条路线的有序途经港口）
"""
from sqlalchemy import (
    Column, BigInteger, Integer, String, SmallInteger,
    DECIMAL, DateTime, ForeignKey
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class ShippingRoute(Base):
    """商业航线表（起止区域的抽象概念）"""
    __tablename__ = "shipping_route"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(32), unique=True, nullable=False, comment="航线编码，自动生成 RT-XXXXXXXXXXXX")
    name = Column(String(128), nullable=False, comment="航线名称")
    origin_region_id = Column(BigInteger, ForeignKey("region.id"), nullable=False, comment="起始区域")
    dest_region_id = Column(BigInteger, ForeignKey("region.id"), nullable=False, comment="目的区域")
    distance_km = Column(DECIMAL(10, 2), comment="参考距离(km)")
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
    paths = relationship(
        "ShippingRoutePath",
        back_populates="route",
        order_by="ShippingRoutePath.sort_order",
        cascade="all, delete-orphan",
    )


class ShippingRoutePath(Base):
    """航线路线方案表（同一航线下可存在多条并行路线，如主航道、运河绕行线）"""
    __tablename__ = "shipping_route_path"

    id = Column(Integer, primary_key=True, autoincrement=True)
    route_id = Column(BigInteger, ForeignKey("shipping_route.id"), nullable=False, comment="所属航线ID")
    code = Column(String(32), unique=True, nullable=False, comment="路线编码，自动生成 RP-XXXXXXXXXXXX")
    name = Column(String(128), nullable=False, comment="路线名称，如主航道/运河绕行线")
    description = Column(String(512), comment="路线描述")
    sort_order = Column(Integer, nullable=False, default=0, comment="排序，数字越小越靠前")
    status = Column(SmallInteger, nullable=False, default=1, comment="1=启用,0=停用")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    route = relationship("ShippingRoute", back_populates="paths")
    nodes = relationship(
        "ShippingRoutePathNode",
        back_populates="path",
        order_by="ShippingRoutePathNode.sequence",
        cascade="all, delete-orphan",
    )


class ShippingRoutePathNode(Base):
    """路线节点表（记录每条路线的有序途经节点）"""
    __tablename__ = "shipping_route_path_node"

    id = Column(Integer, primary_key=True, autoincrement=True)
    path_id = Column(BigInteger, ForeignKey("shipping_route_path.id"), nullable=False, comment="所属路线ID")
    node_id = Column(BigInteger, ForeignKey("transport_node.id"), nullable=False, comment="途经节点ID")
    sequence = Column(Integer, nullable=False, comment="顺序（从1开始）")
    distance_from_start = Column(DECIMAL(10, 2), comment="距路线起点距离(km)")
    node_role = Column(String(32), default="WAYPOINT", comment="START/WAYPOINT/END")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    path = relationship("ShippingRoutePath", back_populates="nodes")
    node = relationship("TransportNode")
