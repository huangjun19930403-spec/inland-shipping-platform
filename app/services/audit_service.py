"""
统一审核业务服务层
职责：
  1. submit_for_audit()   — 业务 Service 提交审核时调用，写 audit_task + audit_record
  2. approve_task()        — 管理员审批通过，更新 task + 业务表 + 写 audit_record
  3. reject_task()         — 管理员驳回，更新 task + 业务表 + 写 audit_record
  4. get_pending_tasks()   — 查询待审核任务列表
  5. list_all_tasks()      — 查询全部任务（带过滤）
  6. list_records()        — 查询历史审核记录
"""
import decimal
import logging
from datetime import datetime, date
from typing import Optional

from app.core.exceptions import NotFoundError, ValidationError, PermissionError
from app.models.audit import AuditRecord, AuditTask
from app.repositories.audit_repository import AuditRepository

logger = logging.getLogger(__name__)


def _sanitize_for_json(data: Optional[dict]) -> Optional[dict]:
    """递归将 dict 中不可 JSON 序列化的类型转换为安全类型"""
    if data is None:
        return None
    result = {}
    for k, v in data.items():
        if isinstance(v, decimal.Decimal):
            result[k] = str(v)
        elif isinstance(v, (datetime, date)):
            result[k] = v.isoformat()
        elif isinstance(v, dict):
            result[k] = _sanitize_for_json(v)
        else:
            result[k] = v
    return result


# 支持审核的 target_type 与对应表名/字段映射
# 格式: target_type -> (table_name, pk_col, has_status_field)
_TARGET_TABLE_MAP = {
    "WATERWAY":            "waterway",
    "REGION":              "region",
    "TRANSPORT_NODE":      "transport_node",
    "NODE_TYPE":           "node_type",
    "VESSEL":              "vessel",
    "VESSEL_TYPE":         "vessel_type_dict",
    "COMMODITY_CATEGORY":  "commodity_category",
    "COMMODITY_TYPE":      "commodity_type",
    "COMMODITY_STANDARD":  "commodity_standard",
    "CARGO_OPPORTUNITY":   "cargo_opportunity",
}

# 审批通过后需要同时将 status 置为 1 的表（启用状态）
_ACTIVATE_ON_APPROVE = {"REGION"}


class AuditService:
    """统一审核业务服务"""

    def __init__(self, audit_repo: AuditRepository) -> None:
        self._audit = audit_repo

    # ─────────────────────────────────────────────────
    # 提交审核（业务 Service 调用此方法）
    # ─────────────────────────────────────────────────

    async def submit_for_audit(
        self,
        target_type: str,
        target_id: int,
        target_name: str,
        action: str,
        submitter_id: int,
        before_data: Optional[dict] = None,
        after_data: Optional[dict] = None,
    ) -> AuditTask:
        """
        提交审核工单。
        若该对象已有 pending 任务，先将旧任务更新为最新提交内容（upsert 语义）。
        同时写一条 audit_record 作为历史日志。
        """
        before_data = _sanitize_for_json(before_data)
        after_data = _sanitize_for_json(after_data)
        # 1. upsert audit_task
        existing = await self._audit.get_pending_task_by_target(target_type, target_id)
        if existing:
            # 更新已有 pending 任务（重新提交）
            existing.action = action
            existing.target_name = target_name
            existing.submitter_id = submitter_id
            existing.submit_time = datetime.now()
            existing.remark = None
            await self._audit._db.flush()
            await self._audit._db.refresh(existing)
            task = existing
        else:
            task = AuditTask(
                target_type=target_type,
                target_id=target_id,
                target_name=target_name,
                action=action,
                status="pending",
                submitter_id=submitter_id,
            )
            task = await self._audit.create_task(task)

        # 2. 写 audit_record 历史日志
        record = AuditRecord(
            target_type=target_type,
            target_id=target_id,
            target_name=target_name,
            action=action,
            audit_result="PENDING",
            submitter_id=submitter_id,
            before_data=before_data,
            after_data=after_data,
        )
        await self._audit.create_record(record)

        logger.info(
            "[AuditService] submitted task_id=%s target=%s/%s action=%s",
            task.id, target_type, target_id, action,
        )
        return task

    # ─────────────────────────────────────────────────
    # 审批通过（基于 task_id）
    # ─────────────────────────────────────────────────

    async def approve_task(
        self,
        task_id: int,
        auditor_id: int,
        auditor_role: str,
        remark: Optional[str] = None,
    ) -> dict:
        task = await self._audit.get_task(task_id)
        if not task:
            raise NotFoundError("AuditTask", task_id)
        if task.status != "pending":
            raise ValidationError(f"任务状态为 '{task.status}'，只有 pending 任务可以审批")
        if auditor_role not in ("SUPER_ADMIN", "ADMIN"):
            raise PermissionError("只有 ADMIN 或 SUPER_ADMIN 可以审批")
        if auditor_role != "SUPER_ADMIN" and task.submitter_id == auditor_id:
            raise PermissionError("不能审批自己提交的数据")

        # 1. 更新 audit_task
        await self._audit.approve_task(task_id, auditor_id, remark)

        # 2. 更新业务表 audit_status = 1, audited_at = now()
        await self._update_business_audit_status(
            task.target_type, task.target_id,
            audit_status=1, audited_at=datetime.now(), auditor_id=auditor_id,
        )

        # 3. 特殊业务：REGION 审批通过同时启用 status=1
        if task.target_type in _ACTIVATE_ON_APPROVE:
            await self._update_business_status(task.target_type, task.target_id, status=1)

        # 4. 写 audit_record 历史日志
        record = AuditRecord(
            target_type=task.target_type,
            target_id=task.target_id,
            target_name=task.target_name,
            action="APPROVE",
            audit_result="APPROVED",
            audit_remark=remark,
            submitter_id=task.submitter_id,
            auditor_id=auditor_id,
            audited_at=datetime.now(),
        )
        await self._audit.create_record(record)
        await self._audit.save()

        logger.info(
            "[AuditService] approved task_id=%s target=%s/%s by auditor=%s",
            task_id, task.target_type, task.target_id, auditor_id,
        )
        return {"task_id": task_id, "status": "approved", "target_type": task.target_type,
                "target_id": task.target_id}

    # ─────────────────────────────────────────────────
    # 驳回（基于 task_id）
    # ─────────────────────────────────────────────────

    async def reject_task(
        self,
        task_id: int,
        auditor_id: int,
        auditor_role: str,
        remark: str,
    ) -> dict:
        task = await self._audit.get_task(task_id)
        if not task:
            raise NotFoundError("AuditTask", task_id)
        if task.status != "pending":
            raise ValidationError(f"任务状态为 '{task.status}'，只有 pending 任务可以驳回")
        if auditor_role not in ("SUPER_ADMIN", "ADMIN"):
            raise PermissionError("只有 ADMIN 或 SUPER_ADMIN 可以驳回")

        # 1. 更新 audit_task
        await self._audit.reject_task(task_id, auditor_id, remark)

        # 2. 更新业务表 audit_status = 2, audited_at = now()
        await self._update_business_audit_status(
            task.target_type, task.target_id,
            audit_status=2, audited_at=datetime.now(), auditor_id=auditor_id,
        )

        # 3. 写 audit_record 历史日志
        record = AuditRecord(
            target_type=task.target_type,
            target_id=task.target_id,
            target_name=task.target_name,
            action="REJECT",
            audit_result="REJECTED",
            audit_remark=remark,
            submitter_id=task.submitter_id,
            auditor_id=auditor_id,
            audited_at=datetime.now(),
        )
        await self._audit.create_record(record)
        await self._audit.save()

        logger.info(
            "[AuditService] rejected task_id=%s target=%s/%s by auditor=%s reason=%s",
            task_id, task.target_type, task.target_id, auditor_id, remark,
        )
        return {"task_id": task_id, "status": "rejected", "target_type": task.target_type,
                "target_id": task.target_id}

    # ─────────────────────────────────────────────────
    # 查询任务列表
    # ─────────────────────────────────────────────────

    async def get_pending_tasks(
        self,
        target_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        offset = (page - 1) * page_size
        items, total = await self._audit.list_tasks(
            status="pending",
            target_type=target_type,
            offset=offset,
            limit=page_size,
        )
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def list_all_tasks(
        self,
        status: Optional[str] = None,
        target_type: Optional[str] = None,
        submitter_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        offset = (page - 1) * page_size
        items, total = await self._audit.list_tasks(
            status=status,
            target_type=target_type,
            submitter_id=submitter_id,
            offset=offset,
            limit=page_size,
        )
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def list_records(
        self,
        status: Optional[str] = None,
        target_type: Optional[str] = None,
        submitter_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        offset = (page - 1) * page_size
        items, total = await self._audit.list_records(
            status=status,
            target_type=target_type,
            submitter_id=submitter_id,
            offset=offset,
            limit=page_size,
        )
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def get_stats(self) -> dict:
        """各类型待审核任务数量统计"""
        counts = await self._audit.count_pending_by_type()
        counts["TOTAL"] = sum(counts.values())
        return counts

    # ─────────────────────────────────────────────────
    # 内部辅助：更新业务表审核字段
    # ─────────────────────────────────────────────────

    async def _update_business_audit_status(
        self,
        target_type: str,
        target_id: int,
        audit_status: int,
        audited_at: datetime,
        auditor_id: Optional[int] = None,
    ) -> None:
        """通过 raw SQL UPDATE 更新对应业务表的审核字段，避免引入所有 Repository 的循环依赖"""
        table_name = _TARGET_TABLE_MAP.get(target_type)
        if not table_name:
            logger.warning("[AuditService] 未知 target_type=%s，跳过业务表更新", target_type)
            return

        from sqlalchemy import text
        if auditor_id is not None:
            sql = text(
                f"UPDATE {table_name} "
                f"SET audit_status = :audit_status, audited_at = :audited_at, auditor_id = :auditor_id "
                f"WHERE id = :target_id"
            )
            await self._audit._db.execute(sql, {
                "audit_status": audit_status,
                "audited_at": audited_at,
                "auditor_id": auditor_id,
                "target_id": target_id,
            })
        else:
            sql = text(
                f"UPDATE {table_name} "
                f"SET audit_status = :audit_status, audited_at = :audited_at "
                f"WHERE id = :target_id"
            )
            await self._audit._db.execute(sql, {
                "audit_status": audit_status,
                "audited_at": audited_at,
                "target_id": target_id,
            })

    async def _update_business_status(
        self, target_type: str, target_id: int, status: int
    ) -> None:
        """更新业务表的 status 字段（用于 REGION 审批通过后自动启用）"""
        table_name = _TARGET_TABLE_MAP.get(target_type)
        if not table_name:
            return
        from sqlalchemy import text
        sql = text(f"UPDATE {table_name} SET status = :status WHERE id = :target_id")
        await self._audit._db.execute(sql, {"status": status, "target_id": target_id})

    # ─────────────────────────────────────────────────
    # 工具方法：供业务 Service 写审核记录日志
    # ─────────────────────────────────────────────────

    async def record_operation(
        self,
        target_type: str,
        target_id: int,
        target_name: str,
        action: str,
        operator_id: int,
        audit_result: str = "APPROVED",
        before_data: Optional[dict] = None,
        after_data: Optional[dict] = None,
        remark: Optional[str] = None,
    ) -> AuditRecord:
        """
        写一条审核记录日志（不创建 audit_task）。
        用于：DELETE、TOGGLE_STATUS 等不需要走审批流的操作记录。
        """
        before_data = _sanitize_for_json(before_data)
        after_data = _sanitize_for_json(after_data)
        record = AuditRecord(
            target_type=target_type,
            target_id=target_id,
            target_name=target_name,
            action=action,
            audit_result=audit_result,
            audit_remark=remark,
            submitter_id=operator_id,
            before_data=before_data,
            after_data=after_data,
        )
        return await self._audit.create_record(record)
