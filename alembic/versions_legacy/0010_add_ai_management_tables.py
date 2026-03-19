"""add ai management tables (prompt templates, versions, call logs)

Revision ID: 0010
Revises: 0009
Create Date: 2026-03-18

变更内容：
  1. 新建 ai_prompt_template  — 提示词模板主表
  2. 新建 ai_prompt_version   — 提示词版本表（含统计字段）
  3. 新建 ai_call_log         — AI 调用日志表
  4. 插入种子数据：cargo_parse 模板 v1（从硬编码迁移）

删除遗留模块（数据无需保留）：
  - 原 llm_client.py / prompt_templates.py / database_tools.py 均为代码级删除，
    无对应数据库表，migration 无需处理。
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

# ── 种子数据：cargo_parse v1 ────────────────────────────────────────────────

_SYSTEM_PROMPT = """你是中国内河航运领域的智能数据解析专家。
你的任务是从船舶货运微信群、物流平台等渠道的原始文本中，提取结构化的货运信息。

内河航运常见术语：
- 起运港/发货地：起点、装货地、发地
- 目的港/卸货地：终点、卸货地、到地
- 货物/品名：大宗散货（煤炭、铁矿石、砂石料、粮食、钢铁）、液货（成品油、化工品）
- 吨位/载重：吨、万吨，注意区分"配货"和"求配"
- 运价/运费：元/吨，有时写作"一百五/吨"、"150一吨"
- 联系方式：手机号、微信号

输出规则：
1. 严格输出JSON，无额外文字
2. 无法确定的字段填null
3. 置信度范围0-100，100为完全确定
4. 地名尽量标准化（如"南京港"→"南京"，"芜湖"直接输出）
5. 货名尽量标准化（如"动力煤"、"冶金煤"、"粗砂"）"""

_USER_TEMPLATE = """请从以下货运文本中提取结构化信息：

{raw_text}

输出JSON格式：
{
    "origin": {"value": "起运地名称或null", "confidence": 0-100},
    "destination": {"value": "目的地名称或null", "confidence": 0-100},
    "commodity": {"value": "货物名称或null", "confidence": 0-100},
    "tonnage": {"value": 数字或null, "unit": "吨", "confidence": 0-100},
    "loading_date": {"value": "YYYY-MM-DD或null", "confidence": 0-100},
    "freight_price": {"value": 数字或null, "unit": "元/吨", "confidence": 0-100},
    "contact": {"value": "联系方式或null", "confidence": 0-100},
    "remarks": "其他重要信息"
}"""


def upgrade() -> None:
    # ── 1. ai_prompt_template ────────────────────────────────────────────────
    op.create_table(
        "ai_prompt_template",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("use_case", sa.String(200), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("active_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    # ── 2. ai_prompt_version ─────────────────────────────────────────────────
    op.create_table(
        "ai_prompt_version",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "template_id",
            sa.Integer,
            sa.ForeignKey("ai_prompt_template.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("system_prompt", sa.Text, nullable=False),
        sa.Column("user_template", sa.Text, nullable=False),
        sa.Column("change_note", sa.Text, nullable=True),
        sa.Column("call_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("confirm_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("correction_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("avg_confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("deprecated_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("template_id", "version", name="uq_prompt_version"),
    )
    op.create_index("ix_ai_prompt_version_template_id", "ai_prompt_version", ["template_id"])

    # ── 3. ai_call_log ───────────────────────────────────────────────────────
    op.create_table(
        "ai_call_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column(
            "prompt_template_id",
            sa.Integer,
            sa.ForeignKey("ai_prompt_template.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("prompt_version", sa.Integer, nullable=True),
        sa.Column("input_tokens", sa.Integer, nullable=True),
        sa.Column("output_tokens", sa.Integer, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("success", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "raw_message_id",
            sa.Integer,
            sa.ForeignKey("cargo_raw_message.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "parse_result_id",
            sa.Integer,
            sa.ForeignKey("cargo_ai_parse_result.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("confidence_score", sa.Integer, nullable=True),
        sa.Column("human_confirmed", sa.Boolean, nullable=True),
        sa.Column("corrected_fields", sa.Text, nullable=True),  # JSON array string
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_ai_call_log_raw_message_id", "ai_call_log", ["raw_message_id"])
    op.create_index("ix_ai_call_log_parse_result_id", "ai_call_log", ["parse_result_id"])
    op.create_index("ix_ai_call_log_provider_model", "ai_call_log", ["provider", "model"])
    op.create_index("ix_ai_call_log_created_at", "ai_call_log", ["created_at"])

    # ── 4. 种子数据 ──────────────────────────────────────────────────────────
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO ai_prompt_template "
            "(name, use_case, description, active_version, is_active, created_by) "
            "VALUES (:name, :use_case, :description, :active_version, 1, 'system')"
        ),
        {
            "name": "cargo_parse",
            "use_case": "货运文本解析",
            "description": "从内河航运群聊/平台原始文本中提取结构化货运信息",
            "active_version": 1,
        },
    )
    tmpl_id = conn.execute(
        sa.text("SELECT id FROM ai_prompt_template WHERE name = 'cargo_parse'")
    ).scalar()

    conn.execute(
        sa.text(
            "INSERT INTO ai_prompt_version "
            "(template_id, version, system_prompt, user_template, change_note, created_by) "
            "VALUES (:template_id, :version, :system_prompt, :user_template, :change_note, 'system')"
        ),
        {
            "template_id": tmpl_id,
            "version": 1,
            "system_prompt": _SYSTEM_PROMPT,
            "user_template": _USER_TEMPLATE,
            "change_note": "初始版本，从硬编码 prompt_templates.py 迁移",
        },
    )


def downgrade() -> None:
    op.drop_table("ai_call_log")
    op.drop_table("ai_prompt_version")
    op.drop_table("ai_prompt_template")
