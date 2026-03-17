"""船舶数据体系模型"""
from sqlalchemy import (
    Column, BigInteger, Integer, String, Text, Integer, SmallInteger,
    DECIMAL, DateTime, JSON, ForeignKey
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class VesselTypeDict(Base):
    """船舶类型字典表"""
    __tablename__ = "vessel_type_dict"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(32), unique=True, nullable=False, comment="船型编码")
    name = Column(String(64), nullable=False, comment="船型名称")
    name_en = Column(String(128), comment="英文名称")
    transport_type = Column(String(32), default="WATERWAY", comment="运输类型")
    applicable_goods = Column(JSON, comment="适用货品类型")
    min_tonnage = Column(Integer, comment="最小载重吨(DWT)")
    max_tonnage = Column(Integer, comment="最大载重吨(DWT)")
    description = Column(String(512), comment="描述")
    sort_order = Column(Integer, nullable=False, default=0)
    status = Column(SmallInteger, nullable=False, default=1)
    audit_status = Column(SmallInteger, nullable=False, default=0,
                          comment="0=待审核,1=已通过,2=已驳回")
    submitter_id = Column(BigInteger, comment="提交人ID")
    auditor_id = Column(BigInteger, comment="审核人ID")
    audited_at = Column(DateTime, comment="审核时间")
    deleted_at = Column(DateTime, nullable=True, default=None, comment="软删时间，NULL=未删除")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Vessel(Base):
    """船舶主档案表"""
    __tablename__ = "vessel"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vessel_no = Column(String(64), unique=True, nullable=False, comment="船舶检验证书号(业务唯一标识)")
    vessel_name = Column(String(128), nullable=False, comment="当前船名")
    mmsi = Column(String(20), comment="AIS编号/MMSI")
    call_sign = Column(String(32), comment="船舶呼号")
    vessel_type_id = Column(BigInteger, ForeignKey("vessel_type_dict.id"), comment="船舶类型")
    # 船舶尺度
    deadweight = Column(Integer, comment="载重吨(DWT)")
    gross_tonnage = Column(DECIMAL(12, 2), comment="总吨")
    net_tonnage = Column(DECIMAL(12, 2), comment="净吨")
    length = Column(DECIMAL(8, 2), comment="船长(m)")
    breadth = Column(DECIMAL(8, 2), comment="船宽(m)")
    depth = Column(DECIMAL(8, 2), comment="型深(m)")
    max_draft = Column(DECIMAL(8, 3), comment="最大吃水(m)")
    # 建造信息
    build_year = Column(Integer, comment="建造年份")
    build_country = Column(String(64), comment="建造国家")
    build_city = Column(String(64), comment="建造地")
    home_port = Column(String(128), comment="船籍港")
    flag = Column(String(32), default="中国", comment="船旗国")
    # 船东信息
    owner_name = Column(String(128), comment="船东名称")
    contact_phone = Column(String(32), comment="联系电话")
    # 状态管理
    data_status = Column(SmallInteger, default=1, comment="1=有效,0=注销")
    is_deleted = Column(SmallInteger, default=0)
    deleted_at = Column(DateTime, nullable=True, default=None, comment="软删时间，NULL=未删除")
    # 审核相关
    audit_status = Column(SmallInteger, nullable=False, default=0,
                          comment="0=待审核,1=已通过,2=已驳回")
    audit_remark = Column(String(512), comment="审核意见")
    submitter_id = Column(BigInteger, comment="提交人ID")
    auditor_id = Column(BigInteger, comment="审核人ID")
    audited_at = Column(DateTime, comment="审核时间")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    vessel_type = relationship("VesselTypeDict", backref="vessels")
    name_history = relationship("VesselNameHistory", back_populates="vessel")
    ais_history = relationship("VesselAisHistory", back_populates="vessel")
    dynamic = relationship("VesselDynamic", back_populates="vessel", uselist=False)


class VesselNameHistory(Base):
    """船舶历史船名表"""
    __tablename__ = "vessel_name_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vessel_id = Column(BigInteger, ForeignKey("vessel.id"), nullable=False)
    old_name = Column(String(128), nullable=False, comment="原船名")
    new_name = Column(String(128), nullable=False, comment="新船名")
    change_reason = Column(String(256), comment="变更原因")
    changed_by = Column(BigInteger, comment="操作人ID")
    changed_at = Column(DateTime, server_default=func.now(), comment="变更时间")
    created_at = Column(DateTime, server_default=func.now())

    vessel = relationship("Vessel", back_populates="name_history")


class VesselAisHistory(Base):
    """船舶AIS历史表（MMSI变更记录）"""
    __tablename__ = "vessel_ais_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vessel_id = Column(BigInteger, ForeignKey("vessel.id"), nullable=False)
    old_mmsi = Column(String(20), nullable=False, comment="原MMSI")
    new_mmsi = Column(String(20), nullable=False, comment="新MMSI")
    change_reason = Column(String(256), comment="变更原因")
    changed_by = Column(BigInteger, comment="操作人ID")
    changed_at = Column(DateTime, server_default=func.now())
    created_at = Column(DateTime, server_default=func.now())

    vessel = relationship("Vessel", back_populates="ais_history")


class VesselDynamic(Base):
    """船舶动态信息表（每船只保留最新一条）"""
    __tablename__ = "vessel_dynamic"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vessel_id = Column(BigInteger, ForeignKey("vessel.id"), nullable=True, unique=True,
                       comment="每船唯一一条最新动态")
    mmsi = Column(String(20), unique=True, nullable=True, comment="MMSI号（动态更新的唯一键）")
    # 位置信息
    current_longitude = Column(DECIMAL(11, 8), comment="当前经度")
    current_latitude = Column(DECIMAL(10, 8), comment="当前纬度")
    current_node_id = Column(BigInteger, ForeignKey("transport_node.id"), comment="当前所在节点")
    # 状态信息
    vessel_status = Column(String(32), default="UNDERWAY",
                           comment="EMPTY/LOADED/IN_PORT/ANCHORED/UNDERWAY/MAINTENANCE")
    current_draft = Column(DECIMAL(8, 3), comment="当前吃水(m)")
    dest_node_id = Column(BigInteger, ForeignKey("transport_node.id"), comment="目的港节点")
    eta = Column(DateTime, comment="预计到达时间")
    speed = Column(DECIMAL(5, 2), comment="当前航速(节)")
    heading = Column(DECIMAL(5, 2), comment="当前船首向(度)")
    cargo_info = Column(String(256), comment="当前载货信息")
    remark = Column(String(512), comment="备注")
    updated_by = Column(BigInteger, comment="更新人ID")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    vessel = relationship("Vessel", back_populates="dynamic")
    current_node = relationship("TransportNode", foreign_keys=[current_node_id])
    dest_node = relationship("TransportNode", foreign_keys=[dest_node_id])
