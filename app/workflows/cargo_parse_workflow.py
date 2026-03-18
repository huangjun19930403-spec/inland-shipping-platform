"""
货源解析工作流
职责：端到端编排货运文本解析的完整流程
包括：调用Agent解析 → 持久化AI结果 → 写AiCallLog → 更新原始消息状态
"""
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import BaseWorkflow, WorkflowResult
from app.agents.cargo_agent import CargoAgent, CargoParseOutput
from app.models.ai import AiCallLog
from app.models.cargo import CargoAiParseResult
from app.repositories.ai_repository import AiRepository
from app.repositories.cargo_repository import CargoRepository

logger = logging.getLogger(__name__)


class CargoParseWorkflow(BaseWorkflow):
    """
    货源解析工作流

    Stage 1: 更新原始消息状态为 PARSING
    Stage 2: 调用 CargoAgent 执行AI解析和实体匹配
    Stage 3: 将解析结果写入 CargoAiParseResult（含 ai_model / ai_prompt_tokens）
    Stage 4: 写 AiCallLog + 更新版本统计
    Stage 5: 更新原始消息状态为 PARSED 或 PARSE_FAILED
    """

    name = "cargo_parse_workflow"
    description = "端到端货运文本解析工作流"

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._cargo_repo = CargoRepository(db)
        self._ai_repo = AiRepository(db)
        self._cargo_agent = CargoAgent(db)

    async def execute(self, context: dict[str, Any]) -> WorkflowResult:
        """
        Args:
            context: {
                "raw_message_id": int,
                "raw_text": str
            }

        Returns:
            WorkflowResult.result = {"parse_result_id": int, "overall_confidence": int}
        """
        raw_message_id = context.get("raw_message_id")
        raw_text = context.get("raw_text", "")
        stage_results: dict[str, Any] = {}

        # Stage 1: 标记解析中
        logger.info("[CargoParseWorkflow] START msg_id=%s", raw_message_id)
        await self._cargo_repo.update_parse_status(raw_message_id, "PARSING")
        await self._cargo_repo.save()
        stage_results["stage1"] = "status → PARSING"

        # Stage 2: AI Agent解析
        agent_result = await self._cargo_agent.run({"raw_text": raw_text})
        stage_results["stage2"] = {
            "success": agent_result.success,
            "steps": agent_result.steps,
        }

        if not agent_result.success:
            await self._write_call_log(
                raw_message_id=raw_message_id,
                parse_result_id=None,
                output=None,
                success=False,
                error=agent_result.error,
            )
            await self._cargo_repo.update_parse_status(raw_message_id, "PARSE_FAILED")
            await self._cargo_repo.save()
            return WorkflowResult(
                success=False,
                error=agent_result.error,
                stage_results=stage_results,
            )

        output: CargoParseOutput = agent_result.output
        call_result = output.call_result

        # Stage 3: 持久化AI解析结果
        candidates_data = {
            "origin_candidates": [
                {"id": c.entity_id, "name": c.entity_name, "score": c.match_score}
                for c in output.origin_candidates
            ],
            "dest_candidates": [
                {"id": c.entity_id, "name": c.entity_name, "score": c.match_score}
                for c in output.dest_candidates
            ],
            "commodity_candidates": [
                {"id": c.entity_id, "name": c.entity_name, "score": c.match_score}
                for c in output.commodity_candidates
            ],
        }

        parse_result = CargoAiParseResult(
            raw_message_id=raw_message_id,
            origin_text=output.origin_text,
            dest_text=output.destination_text,
            commodity_text=output.commodity_text,
            tonnage=output.tonnage,
            loading_date=output.loading_date,
            freight_price=output.freight_price,
            contact_person=output.contact,
            origin_node_id=output.origin_node_id,
            dest_node_id=output.dest_node_id,
            commodity_id=output.commodity_standard_id,
            origin_confidence=output.origin_confidence,
            dest_confidence=output.dest_confidence,
            commodity_confidence=output.commodity_confidence,
            overall_confidence=output.overall_confidence,
            origin_candidates=candidates_data["origin_candidates"],
            dest_candidates=candidates_data["dest_candidates"],
            commodity_candidates=candidates_data["commodity_candidates"],
            parse_status="PENDING_CONFIRM",
            ai_model=call_result.model if call_result else None,
            ai_prompt_tokens=(
                (call_result.input_tokens or 0) + (call_result.output_tokens or 0)
                if call_result else None
            ),
        )

        saved = await self._cargo_repo.create_parse_result(parse_result)
        stage_results["stage3"] = f"parse_result_id={saved.id}"

        # Stage 4: 写 AiCallLog + 更新版本统计
        await self._write_call_log(
            raw_message_id=raw_message_id,
            parse_result_id=saved.id,
            output=output,
            success=True,
            error=None,
        )

        # Stage 5: 更新状态为已解析
        await self._cargo_repo.update_parse_status(raw_message_id, "PARSED")
        await self._cargo_repo.save()
        stage_results["stage5"] = "status → PARSED"

        logger.info(
            "[CargoParseWorkflow] DONE msg_id=%s result_id=%s confidence=%s",
            raw_message_id, saved.id, output.overall_confidence,
        )

        return WorkflowResult(
            success=True,
            result={
                "parse_result_id": saved.id,
                "overall_confidence": output.overall_confidence,
            },
            stage_results=stage_results,
        )

    async def _write_call_log(
        self,
        raw_message_id,
        parse_result_id,
        output,
        success: bool,
        error,
    ) -> None:
        """写 AiCallLog 并（成功时）更新版本调用统计"""
        call_result = output.call_result if output else None
        template_id = output.template_id if output else None
        template_version = output.template_version if output else None
        confidence = output.overall_confidence if output else 0

        log = AiCallLog(
            provider=call_result.provider if call_result else "unknown",
            model=call_result.model if call_result else "unknown",
            prompt_template_id=template_id,
            prompt_version=template_version,
            input_tokens=call_result.input_tokens if call_result else None,
            output_tokens=call_result.output_tokens if call_result else None,
            latency_ms=call_result.latency_ms if call_result else None,
            success=success,
            error_message=error,
            raw_message_id=raw_message_id,
            parse_result_id=parse_result_id,
            confidence_score=confidence if success else None,
        )
        await self._ai_repo.create_call_log(log)

        if success and template_id and template_version:
            await self._ai_repo.increment_call_stats(
                template_id=template_id,
                version=template_version,
                success=True,
                confidence=confidence,
            )
