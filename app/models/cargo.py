"""货品和货源数据体系模型"""
from sqlalchemy import (
    Column, BigInteger, Integer, String, Text, Integer, SmallInteger,
    DECIMAL, DateTime, JSON, ForeignKey, Date
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class CommodityCategory(Base):
    """货品大类表"""
    __tablename__ = "commodity_category"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(32), comment="分类编码")
    name = Column(String(64), nullable=False, comment="大类名称")
    name_en = Column(String(128), comment="英文名称")
    description = Column(String(512), comment="描述")
    sort_order = Column(Integer, nullable=False, default=0)
    status = Column(SmallInteger, nullable=False, default=1)
    # 审核相关
    audit_status = Column(SmallInteger, default=1, comment="0=待审核,1=已通过,2=已驳回")
    submitter_id = Column(BigInteger, comment="提交人ID")
    auditor_id = Column(BigInteger, comment="审核人ID")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    types = relationship("CommodityType", back_populates="category")


class CommodityType(Base):
    """货品类型表"""
    __tablename__ = "commodity_type"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category_id = Column(BigInteger, ForeignKey("commodity_category.id"), nullable=False)
    code = Column(String(32), comment="类型编码")
    name = Column(String(64), nullable=False, comment="类型名称")
    name_en = Column(String(128), comment="英文名称")
    description = Column(String(512), comment="描述")
    sort_order = Column(Integer, nullable=False, default=0)
    status = Column(SmallInteger, nullable=False, default=1)
    audit_status = Column(SmallInteger, default=1)
    submitter_id = Column(BigInteger, comment="提交人ID")
    auditor_id = Column(BigInteger, comment="审核人ID")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    category = relationship("CommodityCategory", back_populates="types")
    standards = relationship("CommodityStandard", back_populates="commodity_type")


class CommodityStandard(Base):
    """标准货品表"""
    __tablename__ = "commodity_standard"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type_id = Column(BigInteger, ForeignKey("commodity_type.id"), nullable=False)
    code = Column(String(32), comment="货品编码")
    name = Column(String(128), nullable=False, comment="货品标准名称")
    name_en = Column(String(256), comment="英文名称")
    commodity_class = Column(String(32), comment="货品分类:散货/件杂/液体/集装箱/特种")
    industry = Column(String(64), comment="行业分类")
    density = Column(DECIMAL(8, 4), comment="密度(t/m³)")
    is_dangerous = Column(SmallInteger, default=0, comment="0=否,1=是")
    loading_method = Column(String(64), comment="装货方式")
    recommended_ship_type = Column(String(128), comment="推荐船型")
    description = Column(String(512), comment="描述")
    sort_order = Column(Integer, nullable=False, default=0)
    status = Column(SmallInteger, nullable=False, default=1)
    audit_status = Column(SmallInteger, default=1, comment="0=待审核,1=已通过,2=已驳回")
    audit_remark = Column(String(512), comment="审核意见")
    submitter_id = Column(BigInteger, comment="提交人ID")
    auditor_id = Column(BigInteger, comment="审核人ID")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    commodity_type = relationship("CommodityType", back_populates="standards")
    aliases = relationship("CommodityAlias", back_populates="commodity")


class CommodityAlias(Base):
    """货品别名表"""
    __tablename__ = "commodity_alias"

    id = Column(Integer, primary_key=True, autoincrement=True)
    commodity_id = Column(BigInteger, ForeignKey("commodity_standard.id"), nullable=False)
    alias_name = Column(String(128), nullable=False, comment="别名")
    alias_type = Column(String(32), default="COMMON",
                        comment="COMMON/ABBR/DIALECT/INDUSTRY")
    priority = Column(Integer, nullable=False, default=0, comment="匹配优先级")
    status = Column(SmallInteger, nullable=False, default=1)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    commodity = relationship("CommodityStandard", back_populates="aliases")


class CargoRawMessage(Base):
    """原始货源文本表"""
    __tablename__ = "cargo_raw_message"

    id = Column(Integer, primary_key=True, autoincrement=True)
    raw_text = Column(Text, nullable=False, comment="原始文本内容")
    source_type = Column(String(32), default="WECHAT_GROUP",
                         comment="WECHAT_GROUP/PHONE/WEBSITE/OTHER")
    group_name = Column(String(128), comment="群名称")
    sender_name = Column(String(64), comment="发送人")
    message_time = Column(DateTime, comment="消息时间")
    collector_id = Column(BigInteger, comment="采集员ID")
    status = Column(String(32), default="PENDING",
                    comment="PENDING/PARSING/PARSED/INVALID")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    parse_results = relationship("CargoAiParseResult", back_populates="raw_message")


class CargoAiParseResult(Base):
    """AI解析结果表"""
    __tablename__ = "cargo_ai_parse_result"

    id = Column(Integer, primary_key=True, autoincrement=True)
    raw_message_id = Column(BigInteger, ForeignKey("cargo_raw_message.id"), nullable=False)
    # AI提取的原始文本信息
    origin_text = Column(String(256), comment="起点原始文本")
    dest_text = Column(String(256), comment="终点原始文本")
    commodity_text = Column(String(256), comment="货品原始文本")
    tonnage_text = Column(String(64), comment="吨位原始文本")
    loading_date_text = Column(String(64), comment="时间原始文本")
    freight_text = Column(String(128), comment="运价原始文本")
    contact_text = Column(String(256), comment="联系方式原始文本")
    # AI匹配结果
    origin_node_id = Column(BigInteger, ForeignKey("transport_node.id"), comment="匹配的起点节点ID")
    dest_node_id = Column(BigInteger, ForeignKey("transport_node.id"), comment="匹配的终点节点ID")
    commodity_id = Column(BigInteger, ForeignKey("commodity_standard.id"), comment="匹配的货品ID")
    tonnage = Column(DECIMAL(12, 2), comment="解析的吨位")
    loading_date = Column(Date, comment="解析的装货日期")
    freight_price = Column(DECIMAL(12, 2), comment="解析的运价")
    price_type = Column(SmallInteger, comment="计价方式:1=按吨,2=按方,3=包干,4=按箱,5=面议")
    contact_person = Column(String(64), comment="解析的联系人")
    contact_phone = Column(String(32), comment="解析的联系电话")
    # 置信度评分（0-100）
    origin_confidence = Column(Integer, default=0)
    dest_confidence = Column(Integer, default=0)
    commodity_confidence = Column(Integer, default=0)
    tonnage_confidence = Column(Integer, default=0)
    overall_confidence = Column(Integer, default=0)
    # 候选匹配（JSON: [{id, name, score}]）
    origin_candidates = Column(JSON, comment="起点候选列表")
    dest_candidates = Column(JSON, comment="终点候选列表")
    commodity_candidates = Column(JSON, comment="货品候选列表")
    # AI模型信息
    ai_model = Column(String(64), comment="使用的AI模型")
    ai_prompt_tokens = Column(Integer, comment="消耗tokens")
    # 处理状态
    parse_status = Column(String(32), default="PENDING_CONFIRM",
                          comment="PENDING_CONFIRM/CONFIRMED/DISCARDED")
    # 人工确认信息
    confirmed_by = Column(BigInteger, comment="确认人ID")
    confirmed_at = Column(DateTime, comment="确认时间")
    discard_reason = Column(String(256), comment="废弃原因")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    raw_message = relationship("CargoRawMessage", back_populates="parse_results")
    origin_node = relationship("TransportNode", foreign_keys=[origin_node_id])
    dest_node = relationship("TransportNode", foreign_keys=[dest_node_id])
    commodity = relationship("CommodityStandard")


class CargoOpportunity(Base):
    """货源信息表（正式数据）"""
    __tablename__ = "cargo_opportunity"

    id = Column(Integer, primary_key=True, autoincrement=True)
    opportunity_no = Column(String(32), unique=True, nullable=False, comment="货源编号")
    # 核心信息
    origin_node_id = Column(BigInteger, ForeignKey("transport_node.id"), nullable=False, comment="装货节点")
    dest_node_id = Column(BigInteger, ForeignKey("transport_node.id"), nullable=False, comment="卸货节点")
    commodity_id = Column(BigInteger, ForeignKey("commodity_standard.id"), nullable=False)
    tonnage = Column(DECIMAL(12, 2), nullable=False, comment="货物吨位(吨)")
    # 自动关联
    origin_region_id = Column(BigInteger, ForeignKey("region.id"), comment="装货区域(系统自动)")
    dest_region_id = Column(BigInteger, ForeignKey("region.id"), comment="卸货区域(系统自动)")
    route_id = Column(BigInteger, ForeignKey("shipping_route.id"), comment="匹配航线(系统自动)")
    # 可选信息
    loading_date = Column(Date, comment="装货日期")
    freight_price = Column(DECIMAL(12, 2), comment="运价")
    price_type = Column(SmallInteger, comment="1=按吨,2=按方,3=包干,4=按箱,5=面议")
    price_unit = Column(String(32), comment="计价单位:元/吨,元/方等")
    contact_person = Column(String(64), comment="联系人")
    contact_phone = Column(String(32), comment="联系电话")
    source_type = Column(String(32), default="WECHAT_GROUP",
                         comment="来源:WECHAT_GROUP/PHONE/WEBSITE/OTHER")
    remark = Column(String(512), comment="备注")
    # 来源追溯
    raw_message_id = Column(BigInteger, ForeignKey("cargo_raw_message.id"), comment="原始文本")
    parse_result_id = Column(BigInteger, ForeignKey("cargo_ai_parse_result.id"), comment="解析结果")
    # 状态
    status = Column(String(32), default="CONFIRMED",
                    comment="PENDING_CONFIRM/CONFIRMED/CANCELLED")
    input_type = Column(String(32), default="MANUAL", comment="录入方式:MANUAL/AI_PARSE")
    collector_id = Column(BigInteger, comment="采集员ID")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    origin_node = relationship("TransportNode", foreign_keys=[origin_node_id])
    dest_node = relationship("TransportNode", foreign_keys=[dest_node_id])
    commodity = relationship("CommodityStandard")
    origin_region = relationship("Region", foreign_keys=[origin_region_id])
    dest_region = relationship("Region", foreign_keys=[dest_region_id])
