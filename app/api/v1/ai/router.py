"""AI管理路由

包含：
- 解析状态查询 / 重新解析（修复 reparse bug）
- 提示词模板管理 CRUD
- 调用日志查询 + 统计
"""
import json
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_roles
from app.models.cargo import CargoRawMessage, CargoAiParseResult
from app.models.ai import AiPromptTemplate, AiPromptVersion
from app.repositories.address_repository import AddressRepository
from app.repositories.ai_repository import AiRepository
from app.repositories.cargo_repository import CargoRepository
from app.schemas.cargo import CargoRawMessageResponse, CargoAiParseResultResponse
from app.schemas.common import success
from app.ai.prompt_manager import invalidate_cache

router = APIRouter()


# ── 解析状态 ────────────────────────────────────────────────────────────────

@router.get("/parse-status/{raw_message_id}", summary="获取原始消息的AI解析状态")
async def get_parse_status(
    raw_message_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR", "COLLECTOR")),
):
    result = await db.execute(
        select(CargoRawMessage).where(CargoRawMessage.id == raw_message_id)
    )
    raw_msg = result.scalar_one_or_none()
    if not raw_msg:
        raise HTTPException(status_code=404, detail="原始消息不存在")

    parse_results_res = await db.execute(
        select(CargoAiParseResult).where(CargoAiParseResult.raw_message_id == raw_message_id)
    )
    parse_results = list(parse_results_res.scalars().all())

    return success(data={
        "raw_message": CargoRawMessageResponse.model_validate(raw_msg),
        "parse_results": [CargoAiParseResultResponse.model_validate(r) for r in parse_results],
        "parse_count": len(parse_results),
    })


@router.post("/reparse/{raw_message_id}", summary="重新触发AI解析")
async def reparse_raw_message(
    raw_message_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR")),
):
    result = await db.execute(
        select(CargoRawMessage).where(CargoRawMessage.id == raw_message_id)
    )
    raw_msg = result.scalar_one_or_none()
    if not raw_msg:
        raise HTTPException(status_code=404, detail="原始消息不存在")
    if raw_msg.status == "PARSING":
        raise HTTPException(status_code=400, detail="正在解析中，请稍候")

    # 重置状态为 PENDING，后台任务负责推进到 PARSING
    raw_msg.status = "PENDING"
    await db.commit()

    from app.tasks.ai_tasks import trigger_cargo_parse
    background_tasks.add_task(trigger_cargo_parse, raw_message_id)

    return success(message="已重新提交AI解析")


# ── 提示词模板管理 ──────────────────────────────────────────────────────────

@router.get("/prompts", summary="列出所有提示词模板")
async def list_prompt_templates(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR")),
):
    ai_repo = AiRepository(db)
    templates = await ai_repo.list_templates()
    return success(data=[
        {
            "id": t.id,
            "name": t.name,
            "use_case": t.use_case,
            "description": t.description,
            "active_version": t.active_version,
            "is_active": t.is_active,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in templates
    ])


@router.get("/prompts/{template_id}/versions", summary="列出提示词版本")
async def list_prompt_versions(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR")),
):
    ai_repo = AiRepository(db)
    template = await ai_repo.get_template_by_id(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    versions = await ai_repo.list_versions(template_id)
    return success(data=[
        {
            "id": v.id,
            "version": v.version,
            "system_prompt": v.system_prompt,
            "user_template": v.user_template,
            "change_note": v.change_note,
            "call_count": v.call_count,
            "success_count": v.success_count,
            "confirm_count": v.confirm_count,
            "correction_count": v.correction_count,
            "avg_confidence": round(v.avg_confidence, 1),
            "created_at": v.created_at.isoformat() if v.created_at else None,
            "deprecated_at": v.deprecated_at.isoformat() if v.deprecated_at else None,
        }
        for v in versions
    ])


@router.post("/prompts/{template_id}/versions", summary="新增提示词版本")
async def create_prompt_version(
    template_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN")),
):
    """
    body: {
        "system_prompt": str,
        "user_template": str,
        "change_note": str (可选),
        "activate": bool (可选，默认false)
    }
    """
    ai_repo = AiRepository(db)
    template = await ai_repo.get_template_by_id(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    system_prompt = body.get("system_prompt", "").strip()
    user_template = body.get("user_template", "").strip()
    if not system_prompt or not user_template:
        raise HTTPException(status_code=400, detail="system_prompt 和 user_template 不能为空")

    next_version = await ai_repo.get_next_version_no(template_id)
    ver = AiPromptVersion(
        template_id=template_id,
        version=next_version,
        system_prompt=system_prompt,
        user_template=user_template,
        change_note=body.get("change_note"),
        created_by=body.get("created_by", "operator"),
    )
    saved = await ai_repo.create_version(ver)

    # 如请求激活，更新模板的 active_version
    if body.get("activate"):
        template.active_version = next_version
        await db.flush()
        invalidate_cache(template.name)

    await db.commit()
    return success(data={"version": saved.version, "id": saved.id})


@router.put("/prompts/{template_id}/activate/{version}", summary="激活指定版本")
async def activate_prompt_version(
    template_id: int,
    version: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN")),
):
    ai_repo = AiRepository(db)
    template = await ai_repo.get_template_by_id(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    ver = await ai_repo.get_version(template_id, version)
    if not ver:
        raise HTTPException(status_code=404, detail=f"版本 {version} 不存在")

    template.active_version = version
    await db.commit()
    invalidate_cache(template.name)
    return success(message=f"已激活版本 {version}")


# ── 调用日志 ────────────────────────────────────────────────────────────────

@router.get("/call-logs", summary="查询AI调用日志")
async def list_call_logs(
    provider: Optional[str] = None,
    template_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR")),
):
    ai_repo = AiRepository(db)
    offset = (page - 1) * page_size
    logs, total = await ai_repo.list_call_logs(
        provider=provider,
        template_id=template_id,
        offset=offset,
        limit=page_size,
    )
    return success(data={
        "items": [
            {
                "id": log.id,
                "provider": log.provider,
                "model": log.model,
                "prompt_template_id": log.prompt_template_id,
                "prompt_version": log.prompt_version,
                "input_tokens": log.input_tokens,
                "output_tokens": log.output_tokens,
                "latency_ms": log.latency_ms,
                "success": log.success,
                "error_message": log.error_message,
                "raw_message_id": log.raw_message_id,
                "parse_result_id": log.parse_result_id,
                "confidence_score": log.confidence_score,
                "human_confirmed": log.human_confirmed,
                "corrected_fields": json.loads(log.corrected_fields) if log.corrected_fields else [],
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@router.get("/call-logs/stats", summary="AI调用统计（按provider/model聚合）")
async def get_call_log_stats(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR")),
):
    ai_repo = AiRepository(db)
    stats = await ai_repo.get_call_log_stats()
    return success(data=stats)


@router.post("/match-suggestions/node", summary="标准节点匹配建议")
async def suggest_nodes(
    body: dict,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR", "COLLECTOR")),
):
    keyword = (body.get("keyword") or "").strip()
    limit = int(body.get("limit") or 10)
    if not keyword:
        raise HTTPException(status_code=400, detail="keyword 不能为空")
    repo = AddressRepository(db)
    items, total = await repo.search_nodes_by_alias(keyword, offset=0, limit=limit)
    return success(data={
        "keyword": keyword,
        "total": total,
        "items": [
            {
                "id": item.id,
                "code": item.code,
                "name": item.name,
                "city": item.city,
                "province": item.province,
                "score": 100 if item.name == keyword else 80,
            }
            for item in items
        ],
    })


@router.post("/match-suggestions/commodity", summary="标准货品匹配建议")
async def suggest_commodity(
    body: dict,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR", "COLLECTOR")),
):
    keyword = (body.get("keyword") or "").strip()
    limit = int(body.get("limit") or 10)
    if not keyword:
        raise HTTPException(status_code=400, detail="keyword 不能为空")
    repo = CargoRepository(db)
    items = await repo.standards.search_by_name(keyword)
    return success(data={
        "keyword": keyword,
        "total": len(items[:limit]),
        "items": [
            {
                "id": item.id,
                "code": item.code,
                "name": item.name,
                "danger_level": item.danger_level,
                "common_unit": item.common_unit,
                "score": 100 if item.name == keyword else 80,
            }
            for item in items[:limit]
        ],
    })


@router.post("/analysis-explain", summary="统计结果解释生成")
async def explain_analysis_result(
    body: dict,
    _=Depends(require_roles("ADMIN", "OPERATOR", "COLLECTOR")),
):
    metric = body.get("metric") or "unknown"
    time_scope = body.get("time_scope") or "未指定时间"
    highlights = body.get("highlights") or []
    risks = body.get("risks") or []
    conclusion = body.get("conclusion") or "当前统计结果总体平稳。"
    text = (
        f"在 {time_scope} 的 {metric} 分析中，"
        f"核心结论为：{conclusion}。"
        f"重点现象：{'; '.join(highlights) if highlights else '暂无显著异常'}。"
        f"风险提示：{'; '.join(risks) if risks else '未发现高风险异常'}。"
        "口径说明：本解释基于统计聚合结果自动生成，请结合审核状态确认数据有效性。"
    )
    return success(data={"explain_text": text, "prompt_version": "phase1-default-v1"})
