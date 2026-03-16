"""地址数据体系模型"""
from sqlalchemy import (
    Column, BigInteger, Integer, String, Text, Integer, SmallInteger,
    DECIMAL, DateTime, JSON, ForeignKey
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class Waterway(Base):
    """水系表"""
    __tablename__ = "waterway"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(32), unique=True, nullable=False, comment="水系编码")
    name = Column(String(64), nullable=False, comment="水系名称")
    name_en = Column(String(128), comment="英文名称")
    level = Column(SmallInteger, nullable=False, default=1, comment="1=主干水系,2=支流,3=运河")
    parent_id = Column(BigInteger, ForeignKey("waterway.id"), comment="上级水系ID")
    provinces = Column(String(256), comment="流经省份")
    total_length_km = Column(DECIMAL(10, 2), comment="总长度(km)")
    navigable_length_km = Column(DECIMAL(10, 2), comment="通航里程(km)")
    description = Column(String(512), comment="描述")
    sort_order = Column(Integer, nullable=False, default=0)
    status = Column(SmallInteger, nullable=False, default=1, comment="1=启用,0=停用")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    children = relationship("Waterway", backref="parent", remote_side=[id])


class Region(Base):
    """航运商业区域表"""
    __tablename__ = "region"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, nullable=False, comment="区域编码（系统自动生成，格式 RG-NNN）")
    name = Column(String(64), nullable=False, comment="区域名称")
    name_en = Column(String(128), comment="英文名称")
    center_longitude = Column(DECIMAL(11, 8), comment="区域中心经度（由边界坐标自动计算）")
    center_latitude = Column(DECIMAL(10, 8), comment="区域中心纬度（由边界坐标自动计算）")
    main_rivers = Column(JSON, comment="主要水系 ID 数组（Waterway.id）")
    main_cities = Column(JSON, comment="主要城市 ID 数组（AdminRegion.id，由边界自动计算）")
    boundary_coordinates = Column(JSON, comment="边界坐标点序列 [[lng,lat],...]")
    boundary_color = Column(String(20), default="#3388ff", comment="边界颜色")
    area_color = Column(String(20), default="#3388ff", comment="填充颜色")
    description = Column(String(512), comment="描述")
    sort_order = Column(Integer, nullable=False, default=0)
    status = Column(SmallInteger, nullable=False, default=0, comment="1=启用,0=停用")
    # 审核相关（与 TransportNode 一致）
    audit_status = Column(SmallInteger, nullable=False, default=0,
                          comment="0=待审核,1=已通过,2=已驳回")
    audit_remark = Column(String(512), comment="审核意见")
    submitter_id = Column(BigInteger, comment="提交人ID")
    auditor_id = Column(BigInteger, comment="审核人ID")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class AdminRegion(Base):
    """行政区划表"""
    __tablename__ = "admin_region"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(12), unique=True, nullable=False, comment="行政区划代码")
    name = Column(String(64), nullable=False, comment="名称")
    short_name = Column(String(32), comment="简称")
    pinyin = Column(String(128), comment="拼音")
    level = Column(SmallInteger, nullable=False, comment="1=省,2=市,3=区县")
    parent_code = Column(String(12), ForeignKey("admin_region.code"), comment="上级代码")
    full_path = Column(String(256), comment="完整路径")
    longitude = Column(DECIMAL(11, 8), comment="行政中心经度")
    latitude = Column(DECIMAL(10, 8), comment="行政中心纬度")
    sort_order = Column(Integer, default=0)
    status = Column(SmallInteger, nullable=False, default=1)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class NodeType(Base):
    """节点类型表"""
    __tablename__ = "node_type"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(32), unique=True, nullable=False, comment="类型编码")
    name = Column(String(64), nullable=False, comment="类型名称")
    name_en = Column(String(128), comment="英文名称")
    transport_mode = Column(String(32), nullable=False, default="WATERWAY",
                            comment="WATERWAY/RAILWAY/HIGHWAY/MULTIMODAL")
    icon = Column(String(256), comment="图标URL")
    description = Column(String(512), comment="描述")
    sort_order = Column(Integer, nullable=False, default=0)
    status = Column(SmallInteger, nullable=False, default=1)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class TransportNode(Base):
    """运输节点表"""
    __tablename__ = "transport_node"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(32), unique=True, nullable=False, comment="节点编码")
    name = Column(String(128), nullable=False, comment="节点标准名称")
    name_en = Column(String(256), comment="英文名称")
    node_type_id = Column(BigInteger, ForeignKey("node_type.id"), nullable=False)
    node_category = Column(SmallInteger, nullable=False, default=4,
                           comment="1=装货,2=卸货,3=中转,4=综合,5=航道")
    waterway_id = Column(BigInteger, ForeignKey("waterway.id"), comment="所属水系")
    region_id = Column(BigInteger, ForeignKey("region.id"), comment="所属商业区域")
    province = Column(String(32), comment="所属省份")
    city = Column(String(32), comment="所属城市")
    district = Column(String(32), comment="所属区县")
    address = Column(String(256), comment="详细地址")
    longitude = Column(DECIMAL(11, 8), comment="经度(WGS84)")
    latitude = Column(DECIMAL(10, 8), comment="纬度(WGS84)")
    node_level = Column(SmallInteger, default=3, comment="1=一级,2=二级,3=三级")
    is_hot_node = Column(SmallInteger, nullable=False, default=0, comment="0=否,1=是")
    river_km = Column(DECIMAL(10, 2), comment="航道里程标(km)")
    max_tonnage = Column(Integer, comment="最大靠泊吨位(吨)")
    berth_count = Column(Integer, comment="泊位数量")
    annual_throughput = Column(String(64), comment="年吞吐量")
    description = Column(String(512), comment="描述")
    sort_order = Column(Integer, nullable=False, default=0)
    status = Column(SmallInteger, nullable=False, default=1, comment="1=运营中,0=停用,2=建设中")
    # 审核相关
    audit_status = Column(SmallInteger, default=1, comment="0=待审核,1=已通过,2=已驳回")
    audit_remark = Column(String(512), comment="审核意见")
    submitter_id = Column(BigInteger, comment="提交人ID")
    auditor_id = Column(BigInteger, comment="审核人ID")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    node_type = relationship("NodeType", backref="nodes")
    waterway = relationship("Waterway", backref="nodes")
    region = relationship("Region", backref="nodes")
    aliases = relationship("NodeAlias", back_populates="node")


class NodeAlias(Base):
    """节点别名表"""
    __tablename__ = "node_alias"

    id = Column(Integer, primary_key=True, autoincrement=True)
    node_id = Column(BigInteger, ForeignKey("transport_node.id"), nullable=False)
    alias_name = Column(String(128), unique=True, nullable=False, comment="别名")
    alias_type = Column(String(32), nullable=False, default="COMMON",
                        comment="COMMON/ABBR/HISTORICAL/SYSTEM")
    source = Column(String(64), comment="别名来源")
    priority = Column(Integer, nullable=False, default=0, comment="匹配优先级")
    status = Column(SmallInteger, nullable=False, default=1)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    node = relationship("TransportNode", back_populates="aliases")


class RegionAddressRelation(Base):
    """节点与区域关系表"""
    __tablename__ = "region_address_relation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    region_id = Column(BigInteger, ForeignKey("region.id"), nullable=False)
    transport_node_id = Column(BigInteger, ForeignKey("transport_node.id"), nullable=False)
    is_primary = Column(SmallInteger, nullable=False, default=1, comment="1=主归属")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
