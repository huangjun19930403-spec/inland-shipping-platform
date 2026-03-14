"""
提示词模板管理
集中管理所有系统提示词，避免散落在业务代码中
"""
from dataclasses import dataclass
from typing import Any


@dataclass
class PromptTemplate:
    """提示词模板"""
    name: str
    system: str
    user_template: str

    def format_user(self, **kwargs: Any) -> str:
        return self.user_template.format(**kwargs)


# ─────────────────────────────────────────────────
# 货源解析提示词
# ─────────────────────────────────────────────────

CARGO_PARSE_TEMPLATE = PromptTemplate(
    name="cargo_parse",
    system="""你是中国内河航运领域的智能数据解析专家。
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
5. 货名尽量标准化（如"动力煤"、"冶金煤"、"粗砂"）""",
    user_template="""请从以下货运文本中提取结构化信息：

{raw_text}

输出JSON格式：
{{
    "origin": {{"value": "起运地名称或null", "confidence": 0-100}},
    "destination": {{"value": "目的地名称或null", "confidence": 0-100}},
    "commodity": {{"value": "货物名称或null", "confidence": 0-100}},
    "tonnage": {{"value": 数字或null, "unit": "吨", "confidence": 0-100}},
    "loading_date": {{"value": "YYYY-MM-DD或null", "confidence": 0-100}},
    "freight_price": {{"value": 数字或null, "unit": "元/吨", "confidence": 0-100}},
    "contact": {{"value": "联系方式或null", "confidence": 0-100}},
    "remarks": "其他重要信息"
}}""",
)


# ─────────────────────────────────────────────────
# 数据分析提示词
# ─────────────────────────────────────────────────

CARGO_TREND_ANALYSIS_TEMPLATE = PromptTemplate(
    name="cargo_trend_analysis",
    system="""你是内河航运市场分析师。
根据提供的货运数据，生成简洁的市场趋势分析报告。
重点关注：货量变化趋势、主要货种结构、热门航线、运价走势。
输出为结构化JSON。""",
    user_template="""分析以下{days}天的内河航运数据：

{data_summary}

输出JSON：
{{
    "trend_summary": "整体趋势描述（100字以内）",
    "cargo_highlights": ["重要货种动态1", "重要货种动态2"],
    "route_highlights": ["热门航线1", "热门航线2"],
    "risk_factors": ["风险因素1"],
    "recommendation": "操作建议（50字以内）"
}}""",
)


# ─────────────────────────────────────────────────
# 航线推荐提示词
# ─────────────────────────────────────────────────

ROUTE_RECOMMEND_TEMPLATE = PromptTemplate(
    name="route_recommend",
    system="""你是内河航运航线规划专家。
根据起终点和货物类型，推荐最优内河航线方案。
考虑因素：水深限制、桥梁净空、闸口通行、里程距离。
输出为结构化JSON。""",
    user_template="""请为以下货运任务推荐航线方案：
起点：{origin}
终点：{destination}
货物：{commodity}
船型：{vessel_type}
吨位：{tonnage}吨

已知可用航线：
{available_routes}

输出JSON：
{{
    "recommended_route_id": 航线ID或null,
    "route_description": "航线说明",
    "estimated_distance_km": 估算里程,
    "key_constraints": ["关键限制1", "限制2"],
    "alternative_suggestion": "备选建议"
}}""",
)


# ─────────────────────────────────────────────────
# 提示词注册表
# ─────────────────────────────────────────────────

PROMPT_REGISTRY: dict[str, PromptTemplate] = {
    "cargo_parse": CARGO_PARSE_TEMPLATE,
    "cargo_trend_analysis": CARGO_TREND_ANALYSIS_TEMPLATE,
    "route_recommend": ROUTE_RECOMMEND_TEMPLATE,
}


def get_template(name: str) -> PromptTemplate:
    """获取提示词模板"""
    template = PROMPT_REGISTRY.get(name)
    if not template:
        raise KeyError(f"Prompt template '{name}' not found")
    return template
