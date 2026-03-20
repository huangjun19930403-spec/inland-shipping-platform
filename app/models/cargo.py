"""货品和货源数据体系模型

CargoFreight 替换原 CargoOpportunity，支持三路录入渠道（TMS/WECHAT_AI/MANUAL）
和多精度位置存储（节点级/城市级/坐标级/原文）。
TmsCargoRaw 暂存 TMS 原始报文，供节点匹配和幂等控制。
CargoAiParseResult 新增城市级位置字段，解耦节点强依赖。
"""
from sqlalchemy import (
    Column, BigInteger, Integer, String, Text, SmallInteger,
    DECIMAL, DateTime, JSON, ForeignKey, Date, UniqueConstraint, Index
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
    audit_status = Column(SmallInteger, nullable=False, default=0,
                          comment="0=待审核,1=已通过,2=已驳回")
    submitter_id = Column(BigInteger, comment="提交人ID")
    auditor_id = Column(BigInteger, comment="审核人ID")
    audited_at = Column(DateTime, comment="审核时间")
    deleted_at = Column(DateTime, nullable=True, default=None, comment="软删时间，NULL=未删除")
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
    audit_status = Column(SmallInteger, nullable=False, default=0,
                          comment="0=待审核,1=已通过,2=已驳回")
    submitter_id = Column(BigInteger, comment="提交人ID")
    auditor_id = Column(BigInteger, comment="审核人ID")
    audited_at = Column(DateTime, comment="审核时间")
    deleted_at = Column(DateTime, nullable=True, default=None, comment="软删时间，NULL=未删除")
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
    audit_status = Column(SmallInteger, nullable=False, default=0,
                          comment="0=待审核,1=已通过,2=已驳回")
    audit_remark = Column(String(512), comment="审核意见")
    submitter_id = Column(BigInteger, comment="提交人ID")
    auditor_id = Column(BigInteger, comment="审核人ID")
    audited_at = Column(DateTime, comment="审核时间")
    deleted_at = Column(DateTime, nullable=True, default=None, comment="软删时间，NULL=未删除")
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
    """原始货源文本表（微信群/其他渠道的原始消息）"""
    __tablename__ = "cargo_raw_message"

    id = Column(Integer, primary_key=True, autoincrement=True)
    raw_text = Column(Text, nullable=False, comment="原始文本内容")
    source_type = Column(String(32), default="WECHAT_GROUP",
                         comment="WECHAT_GROUP/WECHAT_PRIVATE/SMS/OTHER")
    group_name = Column(String(128), comment="群名称")
    sender_name = Column(String(64), comment="发送人")
    message_time = Column(DateTime, comment="消息时间")
    collector_id = Column(BigInteger, comment="采集员ID")
    status = Column(String(32), default="PENDING",
                    comment="PENDING/PARSING/PARSED/PARSE_FAILED/INVALID")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    parse_results = relationship("CargoAiParseResult", back_populates="raw_message")


class CargoAiParseResult(Base):
    """AI解析结果表

    字段设计说明：
    - origin_node_id / dest_node_id 均为可空，AI匹配不到节点时为NULL
    - origin_admin_code / dest_admin_code 城市级行政区划代码（AI新增匹配层级）
    - origin_location_type / dest_location_type 标记位置精度，帮助操作员判断可信度
    """
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
    # AI匹配结果 — 节点级（可空）
    origin_node_id = Column(BigInteger, ForeignKey("transport_node.id"), nullable=True,
                            comment="匹配的起点节点ID，可空")
    dest_node_id = Column(BigInteger, ForeignKey("transport_node.id"), nullable=True,
                          comment="匹配的终点节点ID，可空")
    # AI匹配结果 — 城市级（可空，节点匹配失败时的回退）
    origin_admin_code = Column(String(12), nullable=True, comment="起点城市行政区划代码")
    origin_admin_name = Column(String(50), nullable=True, comment="起点城市名称（冗余）")
    origin_location_type = Column(String(20), default="UNKNOWN",
                                  comment="NODE/CITY/WATERWAY/PORT/UNKNOWN")
    dest_admin_code = Column(String(12), nullable=True, comment="终点城市行政区划代码")
    dest_admin_name = Column(String(50), nullable=True, comment="终点城市名称（冗余）")
    dest_location_type = Column(String(20), default="UNKNOWN",
                                comment="NODE/CITY/WATERWAY/PORT/UNKNOWN")
    # 货品匹配
    commodity_id = Column(BigInteger, ForeignKey("commodity_standard.id"), nullable=True,
                          comment="匹配的货品ID")
    # 结构化数值字段
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
    # 候选匹配（JSON: [{id, name, score, matched_via}]）
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


class CargoFreight(Base):
    """货源主表（替换原 CargoOpportunity）

    支持三路录入渠道和多精度位置存储：
    - TMS:       source_type=TMS，坐标直接来自TMS报文，自动尝试节点匹配
    - WECHAT_AI: source_type=WECHAT_AI，经AI解析+操作员确认后入库
    - MANUAL:    source_type=MANUAL，操作员手动录入，城市级或节点级均可

    位置精度字段（origin_precision / dest_precision）：
    - NODE:        已精确关联到 transport_node
    - CITY:        城市级，已关联到 admin_region（城市）
    - COORDINATE:  仅有坐标（TMS来源但未匹配到节点/城市）
    - UNKNOWN:     无法识别
    """
    __tablename__ = "cargo_freight"

    id = Column(Integer, primary_key=True, autoincrement=True)
    freight_no = Column(String(32), unique=True, nullable=False,
                        comment="货源编号，格式 CS-YYYYMMDD-XXXXXXXX")
    source_type = Column(String(20), nullable=False, default="MANUAL",
                         comment="TMS/WECHAT_AI/MANUAL")
    status = Column(String(20), nullable=False, default="CONFIRMED",
                    comment="PENDING/CONFIRMED/CANCELLED/EXPIRED")

    # ── 装货地（多精度，至少有 origin_raw_text） ──
    origin_node_id = Column(BigInteger, ForeignKey("transport_node.id"), nullable=True,
                            comment="装货节点ID，可空")
    origin_admin_code = Column(String(12), nullable=True, index=True,
                               comment="装货城市行政区划代码（统计主维度）")
    origin_admin_name = Column(String(50), nullable=True, comment="装货城市名称（冗余）")
    origin_region_id = Column(BigInteger, ForeignKey("region.id"), nullable=True,
                              comment="装货商业区域（系统自动推断）")
    origin_longitude = Column(DECIMAL(11, 8), nullable=True, comment="装货地经度")
    origin_latitude = Column(DECIMAL(10, 8), nullable=True, comment="装货地纬度")
    origin_raw_text = Column(String(200), nullable=True, comment="装货地原始文本")
    origin_precision = Column(String(12), nullable=False, default="UNKNOWN",
                              comment="NODE/CITY/COORDINATE/UNKNOWN")

    # ── 卸货地（结构同装货地） ──
    dest_node_id = Column(BigInteger, ForeignKey("transport_node.id"), nullable=True,
                          comment="卸货节点ID，可空")
    dest_admin_code = Column(String(12), nullable=True, index=True,
                             comment="卸货城市行政区划代码（统计主维度）")
    dest_admin_name = Column(String(50), nullable=True, comment="卸货城市名称（冗余）")
    dest_region_id = Column(BigInteger, ForeignKey("region.id"), nullable=True,
                            comment="卸货商业区域（系统自动推断）")
    dest_longitude = Column(DECIMAL(11, 8), nullable=True, comment="卸货地经度")
    dest_latitude = Column(DECIMAL(10, 8), nullable=True, comment="卸货地纬度")
    dest_raw_text = Column(String(200), nullable=True, comment="卸货地原始文本")
    dest_precision = Column(String(12), nullable=False, default="UNKNOWN",
                            comment="NODE/CITY/COORDINATE/UNKNOWN")

    # ── 货物信息 ──
    commodity_id = Column(BigInteger, ForeignKey("commodity_standard.id"), nullable=True)
    commodity_text = Column(String(100), nullable=True, comment="原始货品描述")
    tonnage = Column(DECIMAL(12, 2), nullable=True, comment="货物吨位(吨)")
    volume = Column(DECIMAL(12, 2), nullable=True, comment="货物方数(m³)")
    loading_date = Column(Date, nullable=True, comment="装货日期")
    expire_date = Column(Date, nullable=True, comment="货源有效截止日")

    # ── 价格与联系方式 ──
    freight_price = Column(DECIMAL(12, 2), nullable=True, comment="运价")
    price_type = Column(SmallInteger, nullable=True,
                        comment="1=按吨,2=按方,3=包干,4=按箱,5=面议")
    price_unit = Column(String(32), nullable=True, comment="计价单位")
    contact_person = Column(String(64), nullable=True, comment="联系人")
    contact_phone = Column(String(32), nullable=True, comment="联系电话")
    remark = Column(Text, nullable=True, comment="备注")

    # ── 来源追踪 ──
    raw_message_id = Column(BigInteger, ForeignKey("cargo_raw_message.id"), nullable=True,
                            comment="原始文本ID（WECHAT_AI渠道）")
    parse_result_id = Column(BigInteger, ForeignKey("cargo_ai_parse_result.id"), nullable=True,
                             comment="AI解析结果ID（WECHAT_AI渠道）")
    tms_external_id = Column(String(100), nullable=True, unique=True,
                             comment="TMS系统原始单号（TMS渠道）")
    tms_raw_data = Column(JSON, nullable=True, comment="TMS原始报文快照")
    collector_id = Column(BigInteger, nullable=True, comment="采集员/录入员ID")
    source_message_time = Column(DateTime, nullable=True, comment="来源消息时间（用于时效分析）")

    # ── 一期分析支撑字段 ──
    location_match_level = Column(
        String(20),
        nullable=False,
        default="UNKNOWN",
        comment="NODE/CITY/REGION/UNKNOWN",
    )
    data_quality_score = Column(DECIMAL(5, 2), nullable=False, default=0, comment="数据质量评分 0-100")
    analysis_status = Column(
        String(20),
        nullable=False,
        default="READY",
        comment="PENDING/READY/ANALYZED/FAILED",
    )

    # ── 审核流程 ──
    audit_status = Column(SmallInteger, nullable=False, default=0,
                          comment="0=待审核,1=已通过,2=已驳回")
    submitter_id = Column(BigInteger, nullable=True, comment="提交人ID")
    auditor_id = Column(BigInteger, nullable=True, comment="审核人ID")
    audited_at = Column(DateTime, nullable=True, comment="审核时间")
    audit_remark = Column(String(500), nullable=True, comment="审核意见")

    deleted_at = Column(DateTime, nullable=True, default=None, comment="软删时间")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    origin_node = relationship("TransportNode", foreign_keys=[origin_node_id])
    dest_node = relationship("TransportNode", foreign_keys=[dest_node_id])
    commodity = relationship("CommodityStandard")
    origin_region = relationship("Region", foreign_keys=[origin_region_id])
    dest_region = relationship("Region", foreign_keys=[dest_region_id])

    __table_args__ = (
        Index("ix_cargo_freight_origin_city", "origin_admin_code"),
        Index("ix_cargo_freight_dest_city", "dest_admin_code"),
        Index("ix_cargo_freight_source", "source_type"),
        Index("ix_cargo_freight_status", "status"),
        Index("ix_cargo_freight_analysis_status", "analysis_status"),
        Index("ix_cargo_freight_location_level", "location_match_level"),
        Index("ix_cargo_freight_source_message_time", "source_message_time"),
        Index("ix_cargo_freight_created", "created_at"),
    )


class TmsCargoRaw(Base):
    """TMS原始货源消息暂存表

    消费 RQ Topic "tms.cargo.available" 后写入此表，用于：
    1. 幂等控制（tms_message_id UNIQUE）
    2. 节点匹配结果记录
    3. 失败重试追踪
    """
    __tablename__ = "tms_cargo_raw"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tms_message_id = Column(String(100), unique=True, nullable=False,
                            comment="TMS侧唯一消息ID，防重复消费")
    raw_payload = Column(JSON, nullable=False, comment="TMS原始报文完整内容")

    # TMS提供的原始位置数据
    tms_origin_name = Column(String(200), nullable=True, comment="TMS装货地名称")
    tms_origin_lng = Column(DECIMAL(11, 8), nullable=True, comment="TMS装货地经度")
    tms_origin_lat = Column(DECIMAL(10, 8), nullable=True, comment="TMS装货地纬度")
    tms_origin_region = Column(String(100), nullable=True, comment="TMS装货区域字段")
    tms_dest_name = Column(String(200), nullable=True, comment="TMS卸货地名称")
    tms_dest_lng = Column(DECIMAL(11, 8), nullable=True, comment="TMS卸货地经度")
    tms_dest_lat = Column(DECIMAL(10, 8), nullable=True, comment="TMS卸货地纬度")
    tms_dest_region = Column(String(100), nullable=True, comment="TMS卸货区域字段")

    # 本系统节点匹配结果
    matched_origin_node_id = Column(BigInteger, ForeignKey("transport_node.id"), nullable=True)
    matched_origin_admin_code = Column(String(12), nullable=True, comment="匹配的装货城市代码")
    matched_dest_node_id = Column(BigInteger, ForeignKey("transport_node.id"), nullable=True)
    matched_dest_admin_code = Column(String(12), nullable=True, comment="匹配的卸货城市代码")
    match_strategy = Column(String(50), nullable=True,
                            comment="NAME_EXACT/NAME_FUZZY/PROXIMITY/REGION/FALLBACK")
    match_confidence = Column(SmallInteger, default=0, comment="匹配置信度 0-100")

    # 处理状态
    process_status = Column(String(20), default="PENDING",
                            comment="PENDING/MATCHED/IMPORTED/FAILED")
    freight_id = Column(BigInteger, ForeignKey("cargo_freight.id"), nullable=True,
                        comment="成功创建后关联的货源ID")
    error_msg = Column(String(500), nullable=True, comment="失败原因")

    consumed_at = Column(DateTime, nullable=True, comment="消费时间")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    matched_origin_node = relationship("TransportNode", foreign_keys=[matched_origin_node_id])
    matched_dest_node = relationship("TransportNode", foreign_keys=[matched_dest_node_id])
    freight = relationship("CargoFreight", foreign_keys=[freight_id])
