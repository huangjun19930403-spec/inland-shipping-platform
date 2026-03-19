"""AI 管理表数据访问层

封装 AiPromptTemplate / AiPromptVersion / AiCallLog 的所有数据库操作。
"""
import logging
from typing import Optional, Sequence

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import AiPromptTemplate, AiPromptVersion, AiCallLog
from app.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class AiRepository(BaseRepository):
    model_class = AiCallLog

    # ── AiCallLog ──────────────────────────────────────────────────────────

    async def create_call_log(self, log: AiCallLog) -> AiCallLog:
        return await self.create(log)

    async def update_call_log(self, log_id: int, **kwargs) -> Optional[AiCallLog]:
        result = await self._db.execute(
            select(AiCallLog).where(AiCallLog.id == log_id)
        )
        instance = result.scalar_one_or_none()
        if instance:
            for k, v in kwargs.items():
                setattr(instance, k, v)
            await self._db.flush()
        return instance

    async def get_call_log_by_parse_result(
        self, parse_result_id: int
    ) -> Optional[AiCallLog]:
        """获取与指定解析结果关联的最新调用日志"""
        result = await self._db.execute(
            select(AiCallLog)
            .where(AiCallLog.parse_result_id == parse_result_id)
            .order_by(desc(AiCallLog.id))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_call_logs(
        self,
        provider: Optional[str] = None,
        template_id: Optional[int] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[AiCallLog], int]:
        from sqlalchemy import and_

        filters = []
        if provider:
            filters.append(AiCallLog.provider == provider)
        if template_id:
            filters.append(AiCallLog.prompt_template_id == template_id)

        q = select(AiCallLog)
        if filters:
            q = q.where(and_(*filters))

        total_result = await self._db.execute(
            select(func.count()).select_from(q.subquery())
        )
        total = total_result.scalar_one()

        result = await self._db.execute(
            q.order_by(desc(AiCallLog.created_at)).offset(offset).limit(limit)
        )
        return result.scalars().all(), total

    async def get_call_log_stats(self) -> dict:
        """聚合统计：各 provider/model 的调用次数、平均 latency、token 消耗"""
        result = await self._db.execute(
            select(
                AiCallLog.provider,
                AiCallLog.model,
                func.count(AiCallLog.id).label("total_calls"),
                func.sum(AiCallLog.input_tokens).label("total_input_tokens"),
                func.sum(AiCallLog.output_tokens).label("total_output_tokens"),
                func.avg(AiCallLog.latency_ms).label("avg_latency_ms"),
                func.sum(
                    func.cast(AiCallLog.success, Integer)
                ).label("success_count"),
            ).group_by(AiCallLog.provider, AiCallLog.model)
        )
        rows = result.all()
        return [
            {
                "provider": r.provider,
                "model": r.model,
                "total_calls": r.total_calls,
                "total_input_tokens": r.total_input_tokens or 0,
                "total_output_tokens": r.total_output_tokens or 0,
                "avg_latency_ms": round(r.avg_latency_ms or 0, 1),
                "success_count": r.success_count or 0,
            }
            for r in rows
        ]

    # ── AiPromptTemplate ───────────────────────────────────────────────────

    async def list_templates(self) -> Sequence[AiPromptTemplate]:
        result = await self._db.execute(
            select(AiPromptTemplate).order_by(AiPromptTemplate.id)
        )
        return result.scalars().all()

    async def get_template_by_name(self, name: str) -> Optional[AiPromptTemplate]:
        result = await self._db.execute(
            select(AiPromptTemplate).where(AiPromptTemplate.name == name)
        )
        return result.scalar_one_or_none()

    async def get_template_by_id(
        self, template_id: int
    ) -> Optional[AiPromptTemplate]:
        result = await self._db.execute(
            select(AiPromptTemplate).where(AiPromptTemplate.id == template_id)
        )
        return result.scalar_one_or_none()

    # ── AiPromptVersion ────────────────────────────────────────────────────

    async def list_versions(
        self, template_id: int
    ) -> Sequence[AiPromptVersion]:
        result = await self._db.execute(
            select(AiPromptVersion)
            .where(AiPromptVersion.template_id == template_id)
            .order_by(desc(AiPromptVersion.version))
        )
        return result.scalars().all()

    async def get_version(
        self, template_id: int, version: int
    ) -> Optional[AiPromptVersion]:
        result = await self._db.execute(
            select(AiPromptVersion).where(
                AiPromptVersion.template_id == template_id,
                AiPromptVersion.version == version,
            )
        )
        return result.scalar_one_or_none()

    async def create_version(self, ver: AiPromptVersion) -> AiPromptVersion:
        return await self.create(ver)

    async def get_next_version_no(self, template_id: int) -> int:
        """获取下一个可用版本号"""
        result = await self._db.execute(
            select(func.max(AiPromptVersion.version)).where(
                AiPromptVersion.template_id == template_id
            )
        )
        max_ver = result.scalar_one_or_none()
        return (max_ver or 0) + 1

    async def increment_call_stats(
        self,
        template_id: int,
        version: int,
        success: bool,
        confidence: int,
    ) -> None:
        """原子递增调用计数，滚动更新平均置信度"""
        ver = await self.get_version(template_id, version)
        if not ver:
            return
        ver.call_count += 1
        if success:
            ver.success_count += 1
        if ver.call_count > 0:
            ver.avg_confidence = (
                (ver.avg_confidence * (ver.call_count - 1) + confidence)
                / ver.call_count
            )
        await self._db.flush()

    async def increment_confirm_stats(
        self,
        template_id: int,
        version: int,
        corrected: bool,
    ) -> None:
        """人工确认后更新 confirm_count / correction_count"""
        ver = await self.get_version(template_id, version)
        if not ver:
            return
        if corrected:
            ver.correction_count += 1
        else:
            ver.confirm_count += 1
        await self._db.flush()


# SQLAlchemy Integer import needed for cast in stats query
from sqlalchemy import Integer  # noqa: E402
