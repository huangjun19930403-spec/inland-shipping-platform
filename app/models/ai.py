"""AI 管理表 ORM 模型

三张表：
- AiPromptTemplate  提示词模板主表（每个 use_case 一条记录）
- AiPromptVersion   提示词版本历史（每次修改保存完整内容，含效果统计）
- AiCallLog         每次 LLM 调用的完整记录（含人工确认后的反馈回写）
"""
from sqlalchemy import (
    BigInteger, Boolean, Column, Float, ForeignKey,
    Integer, JSON, String, Text, DateTime,
)
from sqlalchemy.sql import func

from app.models.base import Base


class AiPromptTemplate(Base):
    """提示词模板主表

    每个 use_case 对应一条记录（如 cargo_parse）。
    active_version 指向当前生效的版本号（对应 AiPromptVersion.version）。
    """
    __tablename__ = "ai_prompt_template"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(
        String(64), unique=True, nullable=False,
        comment="模板唯一标识，如 cargo_parse",
    )
    use_case = Column(String(64), nullable=True, comment="使用场景")
    description = Column(Text, nullable=True, comment="模板详细说明")
    active_version = Column(
        Integer, nullable=False, default=1,
        comment="当前生效的版本号",
    )
    is_active = Column(
        Boolean, nullable=False, default=True,
        comment="False 时不可被调用",
    )
    created_by = Column(BigInteger, nullable=True, comment="创建人 ID")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class AiPromptVersion(Base):
    """提示词版本历史

    保存每次变更的完整 prompt 内容。
    效果统计字段（call_count、confirm_count 等）由程序在运行时自动累积，
    开发者无需手动维护，通过 AiRepository 原子更新。
    """
    __tablename__ = "ai_prompt_version"

    id = Column(Integer, primary_key=True, autoincrement=True)
    template_id = Column(
        BigInteger, ForeignKey("ai_prompt_template.id"), nullable=False,
    )
    version = Column(Integer, nullable=False, comment="版本号，从 1 递增")
    system_prompt = Column(Text, nullable=False, comment="系统提示词正文")
    user_template = Column(
        Text, nullable=False,
        comment="用户消息模板，用 {变量名} 作占位符",
    )
    change_note = Column(String(512), nullable=True, comment="本次变更说明")

    # 效果统计（运行时自动累积）
    call_count = Column(Integer, nullable=False, default=0, comment="总调用次数")
    success_count = Column(Integer, nullable=False, default=0, comment="调用成功次数")
    confirm_count = Column(
        Integer, nullable=False, default=0,
        comment="被人工无修改直接确认次数（AI 完全正确）",
    )
    correction_count = Column(
        Integer, nullable=False, default=0,
        comment="被人工修正后确认次数（AI 有误）",
    )
    avg_confidence = Column(
        Float, nullable=False, default=0.0,
        comment="历次调用平均置信度（滚动更新）",
    )

    created_by = Column(BigInteger, nullable=True, comment="创建人 ID")
    created_at = Column(DateTime, server_default=func.now())
    deprecated_at = Column(DateTime, nullable=True, comment="废弃时间，NULL=仍可用")


class AiCallLog(Base):
    """AI 调用日志

    每次 LLM 请求写一条记录。
    人工确认/修正后，回写 human_confirmed 和 corrected_fields，
    为提示词效果分析提供数据基础。
    """
    __tablename__ = "ai_call_log"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 调用标识
    provider = Column(
        String(32), nullable=False,
        comment="anthropic / openai / deepseek / tongyi",
    )
    model = Column(String(64), nullable=False, comment="实际使用的模型 ID")
    prompt_template_id = Column(
        BigInteger, ForeignKey("ai_prompt_template.id"), nullable=True,
        comment="关联的提示词模板",
    )
    prompt_version = Column(Integer, nullable=True, comment="使用的提示词版本号")

    # 性能指标
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    latency_ms = Column(Integer, nullable=False, default=0)

    # 结果
    success = Column(Boolean, nullable=False, default=True)
    error_message = Column(String(512), nullable=True)

    # 业务关联（货运解析场景）
    raw_message_id = Column(
        BigInteger, ForeignKey("cargo_raw_message.id"), nullable=True,
    )
    parse_result_id = Column(
        BigInteger, ForeignKey("cargo_ai_parse_result.id"), nullable=True,
    )

    # 效果评估（人工确认后回写）
    confidence_score = Column(
        Integer, nullable=True,
        comment="本次解析整体置信度 0-100",
    )
    human_confirmed = Column(
        Boolean, nullable=True,
        comment="True=无修改确认（AI对了），False=有修改确认（AI错了），NULL=未处理",
    )
    corrected_fields = Column(
        JSON, nullable=True,
        comment='被人工修正的字段列表，如 ["origin_node","commodity"]',
    )

    created_at = Column(DateTime, server_default=func.now())
