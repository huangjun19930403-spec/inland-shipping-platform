from __future__ import annotations

from typing import Any

from app.core.config import settings


def review_quality_with_qwen_if_available(*, enabled: bool, quality_report: dict[str, Any]) -> dict[str, Any]:
    if not enabled:
        return {"status": "QWEN_SKIPPED", "reason": "use_qwen_if_available=false", "suggestions": []}
    if not (settings.DASHSCOPE_API_KEY or "").strip():
        return {"status": "QWEN_SKIPPED", "reason": "DASHSCOPE_API_KEY is not configured", "suggestions": []}
    # Keep geometry deterministic: Qwen is not allowed to create or mutate
    # formal geometry. The build report contains a deterministic fallback summary
    # and records that a configured Qwen key can be used by follow-up review jobs.
    suggestions = [
        "基于 revier 水系边界生成的中心线需要关键航段人工复核。",
        "运输节点 connector 已作为路径验证入口，后续应结合码头泊位、桥梁、船闸和 AIS 轨迹继续增强。",
        "当前 seed 可作为生产预制候选航道图，不等同于官方通航安全图。",
    ]
    return {
        "status": "QWEN_READY_FOR_OPTIONAL_REVIEW",
        "model": settings.FREIGHT_AI_REVIEW_MODEL,
        "suggestions": suggestions,
        "affects_geometry": False,
        "affects_production_decision": False,
        "quality_score": quality_report.get("quality_score_after"),
    }

