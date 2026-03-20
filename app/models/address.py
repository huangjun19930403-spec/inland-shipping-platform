"""地址数据体系模型"""
from sqlalchemy import (
    Column,
    BigInteger,
    Integer,
    String,
    SmallInteger,
    DECIMAL,
    DateTime,
    JSON,
    ForeignKey,
    UniqueConstraint,
    Index,
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
    audit_status = Column(SmallInteger, nullable=False, default=0, comment="0=待审核,1=已通过,2=已驳回")
    submitter_id = Column(BigInteger, comment="提交人ID")
    audited_at = Column(DateTime, comment="审核时间")
    deleted_at = Column(DateTime, nullable=True, default=None, comment="软删时间，NULL=未删除")
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
    boundary_coordinates = Column(JSON, comment="边界坐标点序列 [[lng,lat],...]")
    boundary_color = Column(String(20), default="#3388ff", comment="边界颜色")
    area_color = Column(String(20), default="#3388ff", comment="填充颜色")
    description = Column(String(512), comment="描述")
    sort_order = Column(Integer, nullable=False, default=0)
    status = Column(SmallInteger, nullable=False, default=0, comment="1=启用,0=停用")
    audit_status = Column(SmallInteger, nullable=False, default=0, comment="0=待审核,1=已通过,2=已驳回")
    audit_remark = Column(String(512), comment="审核意见")
    submitter_id = Column(BigInteger, comment="提交人ID")
    auditor_id = Column(BigInteger, comment="审核人ID")
    audited_at = Column(DateTime, comment="审核时间")
    deleted_at = Column(DateTime, nullable=True, default=None, comment="软删时间，NULL=未删除")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    waterway_relations = relationship(
        "RegionWaterwayRelation",
        back_populates="region",
        cascade="all, delete-orphan",
    )
    city_relations = relationship(
        "RegionCityRelation",
        back_populates="region",
        cascade="all, delete-orphan",
    )
    node_relations = relationship(
        "RegionAddressRelation",
        back_populates="region",
        cascade="all, delete-orphan",
    )

    @property
    def waterway_ids(self) -> list[int]:
        return [r.waterway_id for r in (self.waterway_relations or [])]

    @property
    def city_ids(self) -> list[int]:
        return [r.admin_region_id for r in (self.city_relations or [])]


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
    transport_mode = Column(String(32), nullable=False, default="WATERWAY", comment="WATERWAY/RAILWAY/HIGHWAY/MULTIMODAL")
    icon = Column(String(256), comment="图标URL")
    description = Column(String(512), comment="描述")
    sort_order = Column(Integer, nullable=False, default=0)
    status = Column(SmallInteger, nullable=False, default=1)
    audit_status = Column(SmallInteger, nullable=False, default=0, comment="0=待审核,1=已通过,2=已驳回")
    submitter_id = Column(BigInteger, comment="提交人ID")
    audited_at = Column(DateTime, comment="审核时间")
    deleted_at = Column(DateTime, nullable=True, default=None, comment="软删时间，NULL=未删除")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class TransportNode(Base):
    """运输节点表（仅保留通用字段）"""

    __tablename__ = "transport_node"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(32), unique=True, nullable=False, comment="节点编码")
    name = Column(String(128), nullable=False, comment="节点标准名称")
    name_en = Column(String(256), comment="英文名称")
    node_type_id = Column(BigInteger, ForeignKey("node_type.id"), nullable=False)
    node_category = Column(SmallInteger, nullable=False, default=4, comment="1=装货,2=卸货,3=中转,4=综合,5=航道")
    waterway_id = Column(BigInteger, ForeignKey("waterway.id"), comment="所属水系")

    province = Column(String(32), comment="所属省份")
    city = Column(String(32), comment="所属城市")
    district = Column(String(32), comment="所属区县")
    province_code = Column(String(12), comment="省级行政区划代码")
    city_code = Column(String(12), comment="市级行政区划代码")
    district_code = Column(String(12), comment="区县级行政区划代码")

    address = Column(String(256), comment="详细地址")
    longitude = Column(DECIMAL(11, 8), comment="经度(WGS84)")
    latitude = Column(DECIMAL(10, 8), comment="纬度(WGS84)")
    node_level = Column(SmallInteger, default=3, comment="1=一级,2=二级,3=三级")
    is_hot_node = Column(SmallInteger, nullable=False, default=0, comment="0=否,1=是")

    description = Column(String(512), comment="描述")
    sort_order = Column(Integer, nullable=False, default=0)
    status = Column(SmallInteger, nullable=False, default=1, comment="1=运营中,0=停用,2=建设中")

    audit_status = Column(SmallInteger, nullable=False, default=0, comment="0=待审核,1=已通过,2=已驳回")
    audit_remark = Column(String(512), comment="审核意见")
    submitter_id = Column(BigInteger, comment="提交人ID")
    auditor_id = Column(BigInteger, comment="审核人ID")
    audited_at = Column(DateTime, comment="审核时间")
    deleted_at = Column(DateTime, nullable=True, default=None, comment="软删时间，NULL=未删除")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    node_type = relationship("NodeType", backref="nodes")
    waterway = relationship("Waterway", backref="nodes")
    aliases = relationship("NodeAlias", back_populates="node")
    profile = relationship(
        "TransportNodeProfile",
        back_populates="node",
        uselist=False,
        cascade="all, delete-orphan",
    )
    region_relations = relationship(
        "RegionAddressRelation",
        back_populates="node",
        cascade="all, delete-orphan",
    )

    @property
    def region_ids(self) -> list[int]:
        return [r.region_id for r in (self.region_relations or [])]

    @property
    def primary_region_id(self):
        for rel in self.region_relations or []:
            if rel.is_primary == 1:
                return rel.region_id
        return self.region_relations[0].region_id if self.region_relations else None

    @property
    def river_km(self):
        return self.profile.river_km if self.profile else None

    @property
    def max_tonnage(self):
        return self.profile.max_tonnage if self.profile else None

    @property
    def berth_count(self):
        return self.profile.berth_count if self.profile else None

    @property
    def annual_throughput(self):
        return self.profile.annual_throughput if self.profile else None


class TransportNodeProfile(Base):
    """运输节点扩展属性（码头/港口等差异化属性）"""

    __tablename__ = "transport_node_profile"

    id = Column(Integer, primary_key=True, autoincrement=True)
    transport_node_id = Column(BigInteger, ForeignKey("transport_node.id"), nullable=False, unique=True)
    river_km = Column(DECIMAL(10, 2), comment="航道里程标(km)")
    max_tonnage = Column(Integer, comment="最大靠泊吨位(吨)")
    berth_count = Column(Integer, comment="泊位数量")
    annual_throughput = Column(String(64), comment="年吞吐量")
    extra_attributes = Column(JSON, comment="扩展属性JSON（多式联运差异字段）")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    node = relationship("TransportNode", back_populates="profile")


class NodeAlias(Base):
    """节点别名表"""

    __tablename__ = "node_alias"

    id = Column(Integer, primary_key=True, autoincrement=True)
    node_id = Column(BigInteger, ForeignKey("transport_node.id"), nullable=False)
    alias_name = Column(String(128), unique=True, nullable=False, comment="别名")
    alias_type = Column(String(32), nullable=False, default="COMMON", comment="COMMON/ABBR/HISTORICAL/SYSTEM")
    source = Column(String(64), comment="别名来源")
    priority = Column(Integer, nullable=False, default=0, comment="匹配优先级")
    status = Column(SmallInteger, nullable=False, default=1)
    deleted_at = Column(DateTime, nullable=True, default=None, comment="软删时间，NULL=未删除")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    node = relationship("TransportNode", back_populates="aliases")


class RegionAddressRelation(Base):
    """节点与区域关系表（唯一主表达）"""

    __tablename__ = "region_address_relation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    region_id = Column(BigInteger, ForeignKey("region.id"), nullable=False)
    transport_node_id = Column(BigInteger, ForeignKey("transport_node.id"), nullable=False)
    is_primary = Column(SmallInteger, nullable=False, default=1, comment="1=主归属")
    relation_type = Column(String(32), nullable=False, default="BELONGS", comment="BELONGS/COVERS/NEARBY")
    source = Column(String(64), nullable=False, default="SYSTEM_GEO", comment="SYSTEM_GEO/MANUAL/SEED/IMPORT")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    region = relationship("Region", back_populates="node_relations")
    node = relationship("TransportNode", back_populates="region_relations")

    __table_args__ = (
        UniqueConstraint("region_id", "transport_node_id", name="uk_region_node"),
        Index("ix_region_node_region", "region_id"),
        Index("ix_region_node_node", "transport_node_id"),
    )


class RegionWaterwayRelation(Base):
    """区域与水系关系表"""

    __tablename__ = "region_waterway_relation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    region_id = Column(BigInteger, ForeignKey("region.id"), nullable=False)
    waterway_id = Column(BigInteger, ForeignKey("waterway.id"), nullable=False)
    relation_type = Column(String(32), nullable=False, default="MAIN", comment="MAIN/SECONDARY")
    source = Column(String(64), nullable=False, default="SEED", comment="SEED/MANUAL/SYSTEM")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    region = relationship("Region", back_populates="waterway_relations")
    waterway = relationship("Waterway")

    __table_args__ = (
        UniqueConstraint("region_id", "waterway_id", name="uk_region_waterway"),
        Index("ix_region_waterway_region", "region_id"),
        Index("ix_region_waterway_waterway", "waterway_id"),
    )


class RegionCityRelation(Base):
    """区域与城市关系表"""

    __tablename__ = "region_city_relation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    region_id = Column(BigInteger, ForeignKey("region.id"), nullable=False)
    admin_region_id = Column(BigInteger, ForeignKey("admin_region.id"), nullable=False)
    relation_type = Column(String(32), nullable=False, default="MAIN", comment="MAIN/COVERED")
    source = Column(String(64), nullable=False, default="SYSTEM_GEO", comment="SYSTEM_GEO/SEED/MANUAL")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    region = relationship("Region", back_populates="city_relations")
    admin_region = relationship("AdminRegion")

    __table_args__ = (
        UniqueConstraint("region_id", "admin_region_id", name="uk_region_city"),
        Index("ix_region_city_region", "region_id"),
        Index("ix_region_city_admin", "admin_region_id"),
    )
