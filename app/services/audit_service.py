"""
审核业务服务层
职责：统一审核流程、审批/驳回逻辑编排
规则：通过Repository访问数据，不直接操作SQLAlchemy Session
"""
import logging
from typing import Optional

from app.core.exceptions import NotFoundError, ValidationError, PermissionError
from app.repositories.audit_repository import AuditRepository
from app.repositories.cargo_repository import CargoRepository
from app.repositories.address_repository import AddressRepository

logger = logging.getLogger(__name__)


class AuditService:
    """审核业务服务"""

    def __init__(
        self,
        audit_repo: AuditRepository,
        cargo_repo: CargoRepository,
        address_repo: AddressRepository,
    ) -> None:
        self._audit = audit_repo
        self._cargo = cargo_repo
        self._address = address_repo

    # ─────────────────────────────────────────────────
    # 审核列表
    # ─────────────────────────────────────────────────

    async def list_pending(
        self,
        target_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        offset = (page - 1) * page_size
        items, total = await self._audit.list_records(
            status="PENDING",
            target_type=target_type,
            offset=offset,
            limit=page_size,
        )
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def list_all(
        self,
        status: Optional[str] = None,
        target_type: Optional[str] = None,
        operator_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        offset = (page - 1) * page_size
        items, total = await self._audit.list_records(
            status=status,
            target_type=target_type,
            operator_id=operator_id,
            offset=offset,
            limit=page_size,
        )
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    # ─────────────────────────────────────────────────
    # 审批操作
    # ─────────────────────────────────────────────────

    async def approve(
        self,
        record_id: int,
        auditor_id: int,
        auditor_role: str,
        comment: Optional[str] = None,
    ) -> dict:
        """审批通过"""
        record = await self._audit.get_record(record_id)
        if not record:
            raise NotFoundError("AuditRecord", record_id)

        if record.audit_status != "PENDING":
            raise ValidationError(
                f"Record status is '{record.audit_status}', expected PENDING"
            )

        # 权限检查：SUPER_ADMIN可自审，ADMIN审其他
        if auditor_role not in ("SUPER_ADMIN", "ADMIN"):
            raise PermissionError("Only ADMIN or SUPER_ADMIN can approve records")

        if auditor_role != "SUPER_ADMIN" and record.operator_id == auditor_id:
            raise PermissionError("Cannot approve your own submissions")

        approved = await self._audit.approve_record(
            record_id=record_id,
            auditor_id=auditor_id,
            comment=comment,
        )

        # 触发审批后业务动作
        await self._post_approve_action(approved)
        await self._audit.save()

        logger.info(
            f"[AuditService] approved record_id={record_id} by auditor={auditor_id}"
        )
        return {"record_id": record_id, "status": "APPROVED"}

    async def reject(
        self,
        record_id: int,
        auditor_id: int,
        auditor_role: str,
        reason: str,
    ) -> dict:
        """驳回"""
        record = await self._audit.get_record(record_id)
        if not record:
            raise NotFoundError("AuditRecord", record_id)

        if record.audit_status != "PENDING":
            raise ValidationError(
                f"Record status is '{record.audit_status}', expected PENDING"
            )

        if auditor_role not in ("SUPER_ADMIN", "ADMIN"):
            raise PermissionError("Only ADMIN or SUPER_ADMIN can reject records")

        rejected = await self._audit.reject_record(
            record_id=record_id,
            auditor_id=auditor_id,
            reason=reason,
        )

        # 触发驳回后业务动作
        await self._post_reject_action(rejected)
        await self._audit.save()

        logger.info(
            f"[AuditService] rejected record_id={record_id} reason={reason}"
        )
        return {"record_id": record_id, "status": "REJECTED", "reason": reason}

    # ─────────────────────────────────────────────────
    # 审批后动作（内部方法）
    # ─────────────────────────────────────────────────

    async def _post_approve_action(self, record) -> None:
        """审批通过后的业务联动"""
        target_type = record.target_type
        target_id = record.target_id

        if target_type == "CARGO_OPPORTUNITY":
            await self._cargo.update_parse_result(
                target_id  # 更新关联货源状态
            )
        elif target_type == "TRANSPORT_NODE":
            pass  # 节点审批通过后可触发地图更新等

    async def _post_reject_action(self, record) -> None:
        """驳回后的业务联动"""
        pass  # 可扩展：发送通知、更新状态等

    async def get_pending_stats(self) -> dict:
        """各类型待审核数量统计"""
        target_types = [
            "TRANSPORT_NODE", "VESSEL", "COMMODITY_STANDARD",
            "COMMODITY_CATEGORY", "COMMODITY_TYPE", "WATERWAY",
        ]
        counts = await self._audit.count_pending_by_types(target_types)
        counts["TOTAL"] = sum(counts.values())
        return counts
