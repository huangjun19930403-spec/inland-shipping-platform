"""
AI 货源文本解析引擎
——核心AI融合架构模块——

职责：
1. 调用 Claude API 对非结构化货源文本进行 NLP 解析，提取关键字段
2. 将提取结果与地址别名库、货品别名库做智能模糊匹配
3. 输出结构化解析结果 + 置信度评分 + 候选列表
4. 将结果持久化到 cargo_ai_parse_result 表
"""
import json
import re
import difflib
from typing import Optional
from datetime import date, datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.cargo import CargoRawMessage, CargoAiParseResult
from app.models.address import TransportNode, NodeAlias
from app.models.cargo import CommodityStandard, CommodityAlias


# ── Claude 提示词模板 ──────────────────────────────────────────────────────────

PARSE_SYSTEM_PROMPT = """你是中国内河航运货源信息解析专家。
你的任务是从货主、货代发布的非结构化货源信息文本中，精确提取结构化字段。

【提取规则】
1. 起点（origin）：货物装载地点，可能是港口、码头、城市、地区名称
2. 终点（destination）：货物卸载地点，同上
3. 货品（commodity）：货物品名，注意内河航运常见：煤炭、矿石、砂石、粮食、钢铁等
4. 吨位（tonnage）：货物数量，单位为吨。提取数字，如"5000吨"→5000
5. 装货时间（loading_date）：装货日期，格式化为 YYYY-MM-DD；"今天"→今日日期；"明天"→明日
6. 运价（freight）：运输价格，提取数字
7. 计价方式（price_type）：1=按吨,2=按方,3=包干,4=按箱,5=面议
8. 联系人（contact_person）：联系人姓名
9. 联系电话（contact_phone）：手机或固话号码

【输出格式】严格 JSON，不要任何多余内容：
{
  "origin": "提取的起点文本，无法识别则null",
  "destination": "提取的终点文本，无法识别则null",
  "commodity": "提取的货品名称，无法识别则null",
  "tonnage": 数字或null,
  "loading_date": "YYYY-MM-DD或null",
  "freight": 数字或null,
  "price_type": 整数1-5或null,
  "contact_person": "姓名或null",
  "contact_phone": "电话号码或null",
  "confidence": {
    "origin": 0-100的整数,
    "destination": 0-100的整数,
    "commodity": 0-100的整数,
    "tonnage": 0-100的整数,
    "overall": 0-100的整数
  },
  "parse_notes": "解析备注，说明不确定之处"
}"""


def _build_user_prompt(raw_text: str) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    return f"今天日期：{today}\n\n请解析以下货源信息：\n\n{raw_text}"


# ── 模糊匹配工具 ──────────────────────────────────────────────────────────────

def _fuzzy_score(query: str, target: str) -> float:
    """计算两个字符串的相似度（0~1）"""
    if not query or not target:
        return 0.0
    query = query.strip().lower()
    target = target.strip().lower()
    if query == target:
        return 1.0
    if query in target or target in query:
        return 0.85
    return difflib.SequenceMatcher(None, query, target).ratio()


async def _match_node(
    db: AsyncSession, query: Optional[str]
) -> tuple[Optional[int], int, list]:
    """
    将文本与 transport_node + node_alias 进行模糊匹配。
    返回 (best_node_id, confidence_0_100, candidates_list)
    """
    if not query:
        return None, 0, []

    # 搜索别名表（alias_name LIKE）
    alias_res = await db.execute(
        select(NodeAlias, TransportNode)
        .join(TransportNode, NodeAlias.node_id == TransportNode.id)
        .where(NodeAlias.status == 1, TransportNode.status == 1)
    )
    rows = alias_res.all()

    # 也搜索节点标准名
    node_res = await db.execute(
        select(TransportNode).where(TransportNode.status == 1)
    )
    nodes = list(node_res.scalars().all())

    scored: list[dict] = []

    for alias, node in rows:
        score = _fuzzy_score(query, alias.alias_name)
        if score >= 0.5:
            scored.append({
                "id": node.id,
                "name": node.name,
                "matched_alias": alias.alias_name,
                "score": round(score * 100),
                "priority": alias.priority,
            })

    for node in nodes:
        score = _fuzzy_score(query, node.name)
        if score >= 0.5:
            scored.append({
                "id": node.id,
                "name": node.name,
                "matched_alias": node.name,
                "score": round(score * 100),
                "priority": 5,  # 标准名优先级高
            })

    if not scored:
        return None, 0, []

    # 去重（同一节点保留最高分）
    seen: dict[int, dict] = {}
    for s in scored:
        nid = s["id"]
        if nid not in seen or s["score"] > seen[nid]["score"]:
            seen[nid] = s

    # 按 score desc, priority desc 排序
    candidates = sorted(seen.values(), key=lambda x: (x["score"], x["priority"]), reverse=True)
    top = candidates[0]
    confidence = min(top["score"], 100)

    return top["id"], confidence, candidates[:5]


async def _match_commodity(
    db: AsyncSession, query: Optional[str]
) -> tuple[Optional[int], int, list]:
    """将文本与 commodity_standard + commodity_alias 进行模糊匹配"""
    if not query:
        return None, 0, []

    alias_res = await db.execute(
        select(CommodityAlias, CommodityStandard)
        .join(CommodityStandard, CommodityAlias.commodity_id == CommodityStandard.id)
        .where(CommodityAlias.status == 1, CommodityStandard.status == 1)
    )
    rows = alias_res.all()

    std_res = await db.execute(
        select(CommodityStandard).where(CommodityStandard.status == 1)
    )
    standards = list(std_res.scalars().all())

    scored: list[dict] = []

    for alias, std in rows:
        score = _fuzzy_score(query, alias.alias_name)
        if score >= 0.5:
            scored.append({
                "id": std.id,
                "name": std.name,
                "matched_alias": alias.alias_name,
                "score": round(score * 100),
                "priority": alias.priority,
            })

    for std in standards:
        score = _fuzzy_score(query, std.name)
        if score >= 0.5:
            scored.append({
                "id": std.id,
                "name": std.name,
                "matched_alias": std.name,
                "score": round(score * 100),
                "priority": 5,
            })

    if not scored:
        return None, 0, []

    seen: dict[int, dict] = {}
    for s in scored:
        if s["id"] not in seen or s["score"] > seen[s["id"]]["score"]:
            seen[s["id"]] = s

    candidates = sorted(seen.values(), key=lambda x: (x["score"], x["priority"]), reverse=True)
    top = candidates[0]
    return top["id"], min(top["score"], 100), candidates[:5]


# ── Claude API 调用 ──────────────────────────────────────────────────────────

async def _call_claude(raw_text: str) -> dict:
    """调用 Claude API 解析货源文本，返回结构化 JSON"""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        message = client.messages.create(
            model=settings.AI_MODEL,
            max_tokens=1024,
            system=PARSE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_user_prompt(raw_text)}],
        )
        text = message.content[0].text.strip()
        # 提取 JSON（兼容 Claude 有时加 ```json 代码块）
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        return json.loads(text)
    except Exception as e:
        # AI 不可用时返回空结构
        return {
            "origin": None, "destination": None, "commodity": None,
            "tonnage": None, "loading_date": None, "freight": None,
            "price_type": None, "contact_person": None, "contact_phone": None,
            "confidence": {"origin": 0, "destination": 0, "commodity": 0, "tonnage": 0, "overall": 0},
            "parse_notes": f"AI解析失败: {str(e)}",
        }


# ── 主解析入口 ────────────────────────────────────────────────────────────────

async def parse_cargo_text(
    db: AsyncSession,
    raw_message_id: int,
    collector_id: Optional[int] = None,
) -> CargoAiParseResult:
    """
    主解析函数：
    1. 读取原始文本
    2. 调用 Claude API 提取字段
    3. 模糊匹配地址/货品
    4. 创建并保存 CargoAiParseResult
    """
    # 1. 获取原始消息
    raw_res = await db.execute(
        select(CargoRawMessage).where(CargoRawMessage.id == raw_message_id)
    )
    raw_msg: CargoRawMessage = raw_res.scalar_one_or_none()
    if not raw_msg:
        raise ValueError(f"CargoRawMessage {raw_message_id} not found")

    # 更新状态为解析中
    raw_msg.status = "PARSING"
    await db.flush()

    # 2. 调用 Claude
    parsed = await _call_claude(raw_msg.raw_text)
    confidence = parsed.get("confidence", {})

    # 3. 解析装货日期
    loading_date: Optional[date] = None
    if parsed.get("loading_date"):
        try:
            loading_date = datetime.strptime(parsed["loading_date"], "%Y-%m-%d").date()
        except ValueError:
            pass

    # 4. 模糊匹配地址和货品
    origin_node_id, origin_conf, origin_candidates = await _match_node(db, parsed.get("origin"))
    dest_node_id, dest_conf, dest_candidates = await _match_node(db, parsed.get("destination"))
    commodity_id, commodity_conf, commodity_candidates = await _match_commodity(db, parsed.get("commodity"))

    # 使用 AI 置信度与匹配置信度的加权平均
    ai_origin_conf = confidence.get("origin", 0)
    ai_dest_conf = confidence.get("destination", 0)
    ai_commodity_conf = confidence.get("commodity", 0)
    ai_tonnage_conf = confidence.get("tonnage", 0)

    final_origin_conf = int((ai_origin_conf + origin_conf) / 2) if origin_node_id else ai_origin_conf
    final_dest_conf = int((ai_dest_conf + dest_conf) / 2) if dest_node_id else ai_dest_conf
    final_commodity_conf = int((ai_commodity_conf + commodity_conf) / 2) if commodity_id else ai_commodity_conf
    overall_conf = int((final_origin_conf + final_dest_conf + final_commodity_conf + ai_tonnage_conf) / 4)

    # 5. 创建解析结果
    result = CargoAiParseResult(
        raw_message_id=raw_message_id,
        origin_text=parsed.get("origin"),
        dest_text=parsed.get("destination"),
        commodity_text=parsed.get("commodity"),
        tonnage_text=str(parsed.get("tonnage")) if parsed.get("tonnage") else None,
        loading_date_text=parsed.get("loading_date"),
        freight_text=str(parsed.get("freight")) if parsed.get("freight") else None,
        contact_text=parsed.get("contact_phone"),
        origin_node_id=origin_node_id,
        dest_node_id=dest_node_id,
        commodity_id=commodity_id,
        tonnage=parsed.get("tonnage"),
        loading_date=loading_date,
        freight_price=parsed.get("freight"),
        price_type=parsed.get("price_type"),
        contact_person=parsed.get("contact_person"),
        contact_phone=parsed.get("contact_phone"),
        origin_confidence=final_origin_conf,
        dest_confidence=final_dest_conf,
        commodity_confidence=final_commodity_conf,
        tonnage_confidence=ai_tonnage_conf,
        overall_confidence=overall_conf,
        origin_candidates=origin_candidates,
        dest_candidates=dest_candidates,
        commodity_candidates=commodity_candidates,
        ai_model=settings.AI_MODEL,
        parse_status="PENDING_CONFIRM",
    )
    db.add(result)

    # 6. 更新原始消息状态
    raw_msg.status = "PARSED"
    await db.flush()
    await db.refresh(result)
    return result
