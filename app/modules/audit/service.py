"""audit 模块 service。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.models.address import Region, TransportNode
from app.models.commodity import CommodityStandard
from app.models.freight import Freight
from app.models.vessel import VesselAffiliationEvidence, VesselControllerEvidence, VesselProfile
from app.modules.dictionary.service import CodeSequenceService
from app.modules.audit.repository import (
    AuditRecordRepository,
    AuditTaskRepository,
    AuditTaskSnapshotRepository,
)
from app.modules.audit.schemas import (
    AuditMetadataOption,
    AuditMetadataResponse,
    AuditPendingCountResponse,
    AuditRecordResponse,
    AuditTaskCreateRequest,
    AuditTaskDetailResponse,
    AuditTaskResponse,
    PageResponse,
)

_FINAL_STATUSES = {"APPROVED", "REJECTED", "CANCELED"}

_STATUS_META = {
    "PENDING": ("待审核", "warning"),
    "APPROVED": ("已通过", "success"),
    "REJECTED": ("已驳回", "danger"),
    "CANCELED": ("已取消", "info"),
}
_OBJECT_TYPE_META = {
    "TRANSPORT_NODE": ("运输节点", "primary"),
    "REGION": ("业务区域", "success"),
    "COMMODITY_STANDARD": ("标准货品", "warning"),
    "VESSEL_PROFILE": ("船舶档案", "info"),
    "VESSEL_RELATION": ("船舶主关系", "primary"),
    "VESSEL_CERTIFICATE": ("船舶证书", "warning"),
    "VESSEL_OCR_ADOPTION": ("OCR 采纳", "warning"),
    "VESSEL_CONTROLLER_EVIDENCE": ("实际控制人证据", "primary"),
    "VESSEL_AFFILIATION_EVIDENCE": ("挂靠关系证据", "primary"),
    "VESSEL_RISK_REVIEW": ("船舶风险复核", "danger"),
    "VESSEL_BLACKLIST_SIGNAL": ("船舶名单信号", "danger"),
    "FREIGHT": ("机会样本", "danger"),
}
_CHANGE_TYPE_META = {
    "CREATE": ("新增", "success"),
    "UPDATE": ("修改", "warning"),
    "DELETE": ("删除", "danger"),
    "ENABLE": ("启用", "success"),
    "DISABLE": ("停用", "info"),
}
_ACTION_META = {
    "SUBMIT": ("提交", "info"),
    "ASSIGN": ("指派", "primary"),
    "APPROVE": ("通过", "success"),
    "REJECT": ("驳回", "danger"),
    "CANCEL": ("取消", "info"),
}
_SOURCE_MODULE_META = {
    "ADDRESS": ("地址节点", "primary"),
    "REGION": ("业务区域", "success"),
    "COMMODITY": ("货品", "warning"),
    "VESSEL": ("船舶", "info"),
    "FREIGHT": ("货源", "danger"),
}
_AUDIT_TARGET_MODELS = {
    "TRANSPORT_NODE": TransportNode,
    "REGION": Region,
    "COMMODITY_STANDARD": CommodityStandard,
    "VESSEL_PROFILE": VesselProfile,
    "VESSEL_CONTROLLER_EVIDENCE": VesselControllerEvidence,
    "VESSEL_AFFILIATION_EVIDENCE": VesselAffiliationEvidence,
    "FREIGHT": Freight,
}


def _meta_name(meta: dict[str, tuple[str, str]], code: str | None) -> str | None:
    if not code:
        return None
    return meta.get(code, (code, "info"))[0]


def _meta_color(meta: dict[str, tuple[str, str]], code: str | None) -> str | None:
    if not code:
        return None
    return meta.get(code, (code, "info"))[1]


def _meta_options(meta: dict[str, tuple[str, str]]) -> list[AuditMetadataOption]:
    return [
        AuditMetadataOption(code=code, name=name, color=color)
        for code, (name, color) in meta.items()
    ]


def _to_task_response(entity) -> AuditTaskResponse:
    object_type_code = entity.object_type_code or entity.biz_type_code or entity.biz_code
    object_code = entity.object_code or entity.biz_code
    object_name = entity.object_name or object_code
    source_module_code = entity.source_module_code or entity.biz_type_code
    status_name = _meta_name(_STATUS_META, entity.audit_status)
    return AuditTaskResponse(
        id=entity.id,
        task_no=entity.task_no,
        task_type=entity.biz_type_code,
        task_type_name=_meta_name(_SOURCE_MODULE_META, entity.biz_type_code) or _meta_name(_OBJECT_TYPE_META, entity.biz_type_code),
        object_id=entity.biz_id,
        object_type=object_type_code,
        object_type_code=object_type_code,
        object_type_name=_meta_name(_OBJECT_TYPE_META, object_type_code),
        object_code=object_code,
        object_name=object_name,
        change_type_code=entity.change_type_code,
        change_type_name=_meta_name(_CHANGE_TYPE_META, entity.change_type_code),
        source_module_code=source_module_code,
        source_module_name=_meta_name(_SOURCE_MODULE_META, source_module_code),
        submitter_id=entity.submitter_id,
        submitter_name=entity.submitter_name,
        assignee_user_id=entity.current_handler_id,
        current_handler_id=entity.current_handler_id,
        current_handler_name=entity.current_handler_name,
        status_code=entity.audit_status,
        status_name=status_name,
        status_color=_meta_color(_STATUS_META, entity.audit_status),
        is_actionable=entity.audit_status not in _FINAL_STATUSES,
        audit_remark=entity.audit_remark,
        submitted_at=entity.submitted_at,
        completed_at=entity.completed_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_record_response(entity) -> AuditRecordResponse:
    return AuditRecordResponse(
        id=entity.id,
        task_id=entity.task_id,
        action_code=entity.action_code,
        action_name=_meta_name(_ACTION_META, entity.action_code) or entity.action_code,
        operator_id=entity.operator_id,
        operator_name=None,
        from_status_code=entity.from_status_code,
        from_status_name=_meta_name(_STATUS_META, entity.from_status_code),
        to_status_code=entity.to_status_code,
        to_status_name=_meta_name(_STATUS_META, entity.to_status_code),
        remark=entity.remark,
        created_at=entity.created_at,
    )


def _ensure_task_actionable(task) -> None:
    if task.audit_status in _FINAL_STATUSES:
        raise ValidationError(f"task already finished with status {task.audit_status}")


class AuditTaskService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.task_repo = AuditTaskRepository(db)
        self.record_repo = AuditRecordRepository(db)
        self.snapshot_repo = AuditTaskSnapshotRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def get_metadata(self) -> AuditMetadataResponse:
        return AuditMetadataResponse(
            statuses=_meta_options(_STATUS_META),
            object_types=_meta_options(_OBJECT_TYPE_META),
            change_types=_meta_options(_CHANGE_TYPE_META),
            actions=_meta_options(_ACTION_META),
            source_modules=_meta_options(_SOURCE_MODULE_META),
        )

    async def list_tasks(
        self,
        keyword: str | None,
        queue_type: str | None,
        task_type: str | None,
        status_code: str | None,
        object_type: str | None,
        object_type_code: str | None,
        object_id: int | None,
        submitter_id: int | None,
        assignee_user_id: int | None,
        current_handler_id: int | None,
        submitted_from: datetime | None,
        submitted_to: datetime | None,
        page: int,
        page_size: int,
    ) -> PageResponse[AuditTaskResponse]:
        rows, total = await self.task_repo.list_tasks(
            keyword=keyword,
            queue_type=queue_type,
            task_type=task_type,
            status_code=status_code,
            object_type=object_type,
            object_type_code=object_type_code,
            object_id=object_id,
            submitter_id=submitter_id,
            assignee_user_id=assignee_user_id,
            current_handler_id=current_handler_id,
            submitted_from=submitted_from,
            submitted_to=submitted_to,
            page=page,
            page_size=page_size,
        )
        return PageResponse[AuditTaskResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_task_response(item) for item in rows],
        )

    async def create_task(self, payload: AuditTaskCreateRequest) -> AuditTaskResponse:
        now = datetime.utcnow()
        task_no = (payload.task_no or "").strip()
        if not task_no:
            task_no = await self.sequence_service.next_code("AUDIT_TASK_NO")
        if not task_no:
            raise ValidationError("task_no cannot be empty")
        task = await self.task_repo.create_task(
            {
                "task_no": task_no,
                "biz_type_code": payload.task_type.strip(),
                "biz_id": payload.object_id,
                "biz_code": payload.object_code or payload.object_type,
                "object_type_code": payload.object_type_code or payload.object_type or payload.task_type,
                "object_code": payload.object_code,
                "object_name": payload.object_name,
                "change_type_code": payload.change_type_code or "UPDATE",
                "source_module_code": payload.source_module_code or payload.task_type,
                "submitter_id": payload.submitter_id,
                "submitter_name": payload.submitter_name,
                "current_handler_id": payload.assignee_user_id,
                "current_handler_name": payload.current_handler_name,
                "audit_status": "PENDING",
                "audit_remark": payload.comment,
                "submitted_at": now,
                "completed_at": None,
            }
        )
        await self.record_repo.create_record(
            {
                "task_id": task.id,
                "action_code": "SUBMIT",
                "operator_id": payload.submitter_id,
                "from_status_code": None,
                "to_status_code": "PENDING",
                "remark": payload.comment,
                "created_at": now,
            }
        )
        if any(
            [
                payload.before_snapshot_json,
                payload.after_snapshot_json,
                payload.diff_json,
                payload.summary_json,
            ]
        ):
            await self.snapshot_repo.upsert_snapshot(
                task.id,
                {
                    "before_snapshot_json": payload.before_snapshot_json,
                    "after_snapshot_json": payload.after_snapshot_json,
                    "diff_json": payload.diff_json,
                    "summary_json": payload.summary_json,
                },
            )
        await self.db.commit()
        return _to_task_response(task)

    async def get_task_detail(self, task_id: int) -> AuditTaskDetailResponse:
        task = await self.task_repo.get_task_by_id(task_id)
        if task is None:
            raise NotFoundError("AuditTask", task_id)
        rows, _ = await self.record_repo.list_records(task_id, page=1, page_size=500)
        snapshot = await self.snapshot_repo.get_snapshot_by_task_id(task_id)
        task_response = _to_task_response(task)
        summary: dict[str, Any] = {}
        before_snapshot: dict[str, Any] = {}
        after_snapshot: dict[str, Any] = {}
        diff_items: list[dict[str, Any]] = []
        if snapshot is not None:
            summary = snapshot.summary_json or {}
            before_snapshot = snapshot.before_snapshot_json or {}
            after_snapshot = snapshot.after_snapshot_json or {}
            diff_items = snapshot.diff_json or []
        if not summary:
            summary = {
                "object_type": task_response.object_type_name or task_response.object_type_code,
                "object_code": task_response.object_code,
                "object_name": task_response.object_name,
            }
        bridge_context = await self._vessel_bridge_context(task)
        return AuditTaskDetailResponse(
            task=task_response,
            object_summary=summary,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            diff_items=diff_items,
            snapshot_summary=summary,
            records=[_to_record_response(item) for item in rows],
            available_actions=["ASSIGN", "APPROVE", "REJECT", "CANCEL"] if task.audit_status not in _FINAL_STATUSES else [],
            **bridge_context,
        )

    async def assign_task(self, task_id: int, assignee_user_id: int, operator_user_id: int) -> None:
        task = await self.task_repo.get_task_by_id(task_id)
        if task is None:
            raise NotFoundError("AuditTask", task_id)
        _ensure_task_actionable(task)
        from_status = task.audit_status
        ok = await self.task_repo.assign_task(task_id, assignee_user_id)
        if not ok:
            raise NotFoundError("AuditTask", task_id)
        await self.task_repo.update_task(
            task_id,
            {"current_handler_id": assignee_user_id},
        )
        await self.record_repo.create_record(
            {
                "task_id": task_id,
                "action_code": "ASSIGN",
                "operator_id": operator_user_id,
                "from_status_code": from_status,
                "to_status_code": from_status,
                "remark": f"assign_to={assignee_user_id}",
            }
        )
        await self.db.commit()

    async def approve_task(
        self,
        task_id: int,
        comment: str | None,
        operator_user_id: int,
        operator_name: str | None = None,
    ) -> None:
        await self._finish_task(
            task_id=task_id,
            target_status="APPROVED",
            action_code="APPROVE",
            comment=comment,
            operator_user_id=operator_user_id,
            operator_name=operator_name,
        )

    async def reject_task(
        self,
        task_id: int,
        comment: str | None,
        operator_user_id: int,
        operator_name: str | None = None,
    ) -> None:
        await self._finish_task(
            task_id=task_id,
            target_status="REJECTED",
            action_code="REJECT",
            comment=comment,
            operator_user_id=operator_user_id,
            operator_name=operator_name,
        )

    async def cancel_task(
        self,
        task_id: int,
        comment: str | None,
        operator_user_id: int,
        operator_name: str | None = None,
    ) -> None:
        await self._finish_task(
            task_id=task_id,
            target_status="CANCELED",
            action_code="CANCEL",
            comment=comment,
            operator_user_id=operator_user_id,
            operator_name=operator_name,
        )

    async def _finish_task(
        self,
        task_id: int,
        target_status: str,
        action_code: str,
        comment: str | None,
        operator_user_id: int,
        operator_name: str | None = None,
    ) -> None:
        task = await self.task_repo.get_task_by_id(task_id)
        if task is None:
            raise NotFoundError("AuditTask", task_id)
        _ensure_task_actionable(task)
        now = datetime.utcnow()
        from_status = task.audit_status
        updated = await self.task_repo.update_task(
            task_id,
            {
                "audit_status": target_status,
                "audit_remark": comment,
                "current_handler_id": operator_user_id,
                "current_handler_name": operator_name,
                "completed_at": now,
            },
        )
        if updated is None:
            raise NotFoundError("AuditTask", task_id)
        await self.record_repo.create_record(
            {
                "task_id": task_id,
                "action_code": action_code,
                "operator_id": operator_user_id,
                "from_status_code": from_status,
                "to_status_code": target_status,
                "remark": comment,
                "created_at": now,
            }
        )
        bridge_result = None
        if target_status in {"APPROVED", "REJECTED"}:
            await self._sync_target_audit_status(task, target_status, operator_user_id, now)
            bridge_result = await self._sync_vessel_bridge_after_audit(
                task,
                target_status=target_status,
                operator_user_id=operator_user_id,
                audited_at=now,
            )
        await self.db.commit()
        if bridge_result is not None and bridge_result.vessel_id is not None:
            await self._refresh_vessel_bridge_compliance(
                bridge_result.vessel_id,
                operator_user_id=operator_user_id,
            )

    async def _sync_target_audit_status(
        self,
        task,
        target_status: str,
        operator_user_id: int,
        audited_at: datetime,
    ) -> None:
        object_type_code = task.object_type_code or task.biz_type_code or task.biz_code
        model = _AUDIT_TARGET_MODELS.get(object_type_code)
        if model is None:
            return
        target = await self.db.get(model, task.biz_id)
        if target is None:
            return
        if hasattr(target, "verified_status_code"):
            target.verified_status_code = target_status
            if target_status == "APPROVED":
                if hasattr(target, "verified_by"):
                    target.verified_by = operator_user_id
                if hasattr(target, "verified_at"):
                    target.verified_at = audited_at
            if hasattr(target, "revision"):
                target.revision = int(target.revision or 1) + 1
            return
        if not hasattr(target, "audit_status"):
            return
        target.audit_status = target_status
        if hasattr(target, "auditor_id"):
            target.auditor_id = operator_user_id
        if hasattr(target, "audited_at"):
            target.audited_at = audited_at

    async def _sync_vessel_bridge_after_audit(
        self,
        task,
        *,
        target_status: str,
        operator_user_id: int,
        audited_at: datetime,
    ):
        from app.modules.vessel.audit_bridge_service import VesselAuditBridgeService

        return await VesselAuditBridgeService(self.db).sync_after_audit(
            task,
            target_status=target_status,
            operator_user_id=operator_user_id,
            audited_at=audited_at,
        )

    async def _refresh_vessel_bridge_compliance(self, vessel_id: int, *, operator_user_id: int) -> None:
        from app.modules.vessel.audit_bridge_service import VesselAuditBridgeService

        await VesselAuditBridgeService(self.db).refresh_compliance_best_effort(
            vessel_id,
            operator_user_id=operator_user_id,
        )

    async def _vessel_bridge_context(self, task) -> dict[str, Any]:
        from app.modules.vessel.audit_bridge_service import VesselAuditBridgeService

        return await VesselAuditBridgeService(self.db).detail_context(task)

    async def get_pending_count(self, assignee_user_id: int | None = None) -> AuditPendingCountResponse:
        count = await self.task_repo.get_pending_count(assignee_user_id)
        return AuditPendingCountResponse(pending_count=count)


class AuditRecordService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = AuditRecordRepository(db)

    async def list_records(
        self,
        task_id: int,
        page: int,
        page_size: int,
    ) -> PageResponse[AuditRecordResponse]:
        rows, total = await self.repo.list_records(task_id, page=page, page_size=page_size)
        return PageResponse[AuditRecordResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_record_response(item) for item in rows],
        )
