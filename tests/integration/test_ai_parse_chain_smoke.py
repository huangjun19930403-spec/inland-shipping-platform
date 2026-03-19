"""核心 AI 解析链路 smoke tests（Phase 6）。"""
from datetime import datetime

import pytest
from sqlalchemy import select

from app.ai.providers.base import LLMCallResult
from app.models.ai import AiCallLog, AiPromptTemplate, AiPromptVersion
from app.models.cargo import CargoAiParseResult, CargoRawMessage
from app.workflows.cargo_parse_workflow import CargoParseWorkflow


@pytest.mark.asyncio
async def test_ai_parse_workflow_smoke(db_session, monkeypatch):
    template = AiPromptTemplate(
        name="cargo_parse",
        use_case="cargo_parse",
        description="phase6 smoke template",
        active_version=1,
        is_active=True,
    )
    db_session.add(template)
    await db_session.flush()
    db_session.add(
        AiPromptVersion(
            template_id=template.id,
            version=1,
            system_prompt="你是货源解析助手",
            user_template="请解析文本：{raw_text}",
            created_by=1,
        )
    )

    raw = CargoRawMessage(
        raw_text="南京到武汉，动力煤1200吨，运价80，电话13800000000",
        source_type="WECHAT_GROUP",
        group_name="测试群",
        sender_name="张三",
        message_time=datetime(2026, 3, 19, 9, 0, 0),
        collector_id=1,
        status="PENDING",
    )
    db_session.add(raw)
    await db_session.commit()

    async def _fake_json_completion(system_prompt: str, user_message: str, provider_name=None):
        parsed = {
            "origin": {"value": "南京", "confidence": 90},
            "destination": {"value": "武汉", "confidence": 88},
            "commodity": {"value": "动力煤", "confidence": 86},
            "tonnage": {"value": 1200.0, "unit": "吨", "confidence": 90},
            "loading_date": {"value": None, "confidence": 70},
            "freight_price": {"value": 80.0, "unit": "元/吨", "confidence": 80},
            "contact": {"value": "13800000000", "confidence": 95},
            "remarks": "AI smoke test",
        }
        call_result = LLMCallResult(
            content='{"ok":true}',
            input_tokens=120,
            output_tokens=80,
            model="mock-model",
            provider="mock-provider",
            latency_ms=10,
        )
        return parsed, call_result

    monkeypatch.setattr("app.tools.cargo_tools.json_completion", _fake_json_completion)

    workflow = CargoParseWorkflow(db_session)
    workflow_result = await workflow.execute(
        {"raw_message_id": raw.id, "raw_text": raw.raw_text}
    )
    assert workflow_result.success is True

    refreshed_raw = (
        await db_session.execute(
            select(CargoRawMessage).where(CargoRawMessage.id == raw.id)
        )
    ).scalar_one()
    assert refreshed_raw.status == "PARSED"

    parse_results = (
        await db_session.execute(
            select(CargoAiParseResult).where(CargoAiParseResult.raw_message_id == raw.id)
        )
    ).scalars().all()
    assert len(parse_results) == 1
    assert parse_results[0].parse_status == "PENDING_CONFIRM"
    assert parse_results[0].ai_model == "mock-model"

    call_logs = (
        await db_session.execute(
            select(AiCallLog).where(AiCallLog.raw_message_id == raw.id)
        )
    ).scalars().all()
    assert len(call_logs) == 1
    assert call_logs[0].success is True
