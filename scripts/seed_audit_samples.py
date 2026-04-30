"""审核中心治理样例数据。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.address import Region, TransportNode
from app.models.audit import AuditRecord, AuditTask, AuditTaskSnapshot
from app.models.commodity import CommodityStandard
from app.models.freight import Freight
from app.models.ship import ShipProfile
from app.models.system import SysUser


OBJECT_SPECS = [
    ("TRANSPORT_NODE", "ADDRESS", TransportNode, "code", "name", "节点名称"),
    ("REGION", "REGION", Region, "code", "name", "区域名称"),
    ("COMMODITY_STANDARD", "COMMODITY", CommodityStandard, "code", "name", "标准货品名称"),
    ("SHIP_PROFILE", "SHIP", ShipProfile, "ais_id", "ship_name", "船名"),
    ("FREIGHT", "FREIGHT", Freight, "freight_no", "cargo_title", "货源标题"),
]

STATUS_FLOW = [
    ("PENDING", None),
    ("APPROVED", "APPROVE"),
    ("REJECTED", "REJECT"),
    ("CANCELED", "CANCEL"),
]
CHANGE_TYPES = ["CREATE", "UPDATE", "DISABLE", "ENABLE"]


def _value(row: Any, field: str) -> Any:
    value = getattr(row, field, None)
    if value is None:
        return None
    return str(value)


def _snapshots(row: Any, object_type: str, field_code: str, field_name: str, idx: int) -> tuple[dict, dict, list[dict], dict]:
    current_code = _value(row, field_code) or f"OBJ-{idx:03d}"
    current_name = _value(row, field_name) or f"审核对象 {idx:03d}"
    before_name = f"{current_name}（待校验）" if idx % 3 == 0 else current_name
    before_status = "PENDING" if idx % 4 else "APPROVED"
    after_status = "APPROVED" if idx % 2 else "PENDING"
    before = {
        "object_code": current_code,
        "object_name": before_name,
        "audit_status": before_status,
        "remark": "本地 seed 样例：变更前快照",
    }
    after = {
        "object_code": current_code,
        "object_name": current_name,
        "audit_status": after_status,
        "remark": "本地 seed 样例：变更后快照",
    }
    diff = [
        {
            "field": "object_name",
            "field_name": "对象名称",
            "before": before["object_name"],
            "after": after["object_name"],
            "change_type": "UPDATE",
        },
        {
            "field": "audit_status",
            "field_name": "审核状态",
            "before": before["audit_status"],
            "after": after["audit_status"],
            "change_type": "UPDATE",
        },
    ]
    summary = {
        "object_type_code": object_type,
        "object_code": current_code,
        "object_name": current_name,
        "main_field": field_name,
        "change_count": len(diff),
    }
    return before, after, diff, summary


async def _load_rows(session, model, limit: int = 10) -> list[Any]:
    rows = (await session.execute(select(model).order_by(model.id.asc()).limit(limit))).scalars().all()
    return list(rows)


async def seed_audit_samples() -> None:
    async with AsyncSessionLocal() as session:
        now = datetime.utcnow()
        admin = await session.scalar(select(SysUser).where(SysUser.username == "admin"))
        submitter_id = int(admin.id) if admin is not None else None
        submitter_name = admin.real_name if admin is not None else "系统管理员"
        handler_id = submitter_id
        handler_name = submitter_name

        candidates: list[tuple[str, str, Any, str, str, str]] = []
        for object_type, module_code, model, code_field, name_field, field_label in OBJECT_SPECS:
            rows = await _load_rows(session, model, limit=10)
            for row in rows:
                candidates.append((object_type, module_code, row, code_field, name_field, field_label))

        for idx, (object_type, module_code, row, code_field, name_field, field_label) in enumerate(candidates[:50], start=1):
            status_code, final_action = STATUS_FLOW[(idx - 1) % len(STATUS_FLOW)]
            change_type = CHANGE_TYPES[(idx - 1) % len(CHANGE_TYPES)]
            task_no = f"AUDIT-SAMPLE-{idx:04d}"
            object_code = _value(row, code_field) or f"OBJ-{idx:03d}"
            object_name = _value(row, name_field) or f"审核对象 {idx:03d}"
            submitted_at = now - timedelta(days=idx % 21, hours=idx % 9)
            completed_at = submitted_at + timedelta(hours=2 + idx % 8) if final_action else None
            before, after, diff, summary = _snapshots(row, object_type, code_field, name_field, idx)

            task = await session.scalar(select(AuditTask).where(AuditTask.task_no == task_no))
            payload = {
                "task_no": task_no,
                "biz_type_code": module_code,
                "biz_id": int(row.id),
                "biz_code": object_code,
                "object_type_code": object_type,
                "object_code": object_code,
                "object_name": object_name,
                "change_type_code": change_type,
                "source_module_code": module_code,
                "submitter_id": submitter_id,
                "submitter_name": submitter_name,
                "current_handler_id": handler_id,
                "current_handler_name": handler_name,
                "audit_status": status_code,
                "audit_remark": "本地审核治理样例",
                "submitted_at": submitted_at,
                "completed_at": completed_at,
            }
            if task is None:
                task = AuditTask(**payload)
                session.add(task)
                await session.flush()
            else:
                for key, value in payload.items():
                    setattr(task, key, value)
                await session.flush()

            snapshot = await session.scalar(
                select(AuditTaskSnapshot).where(AuditTaskSnapshot.task_id == task.id)
            )
            snapshot_payload = {
                "task_id": task.id,
                "before_snapshot_json": before,
                "after_snapshot_json": after,
                "diff_json": diff,
                "summary_json": summary,
                "updated_at": now,
            }
            if snapshot is None:
                session.add(AuditTaskSnapshot(**snapshot_payload, created_at=now))
            else:
                for key, value in snapshot_payload.items():
                    setattr(snapshot, key, value)

            await session.execute(delete(AuditRecord).where(AuditRecord.task_id == task.id))
            session.add(
                AuditRecord(
                    task_id=task.id,
                    action_code="SUBMIT",
                    operator_id=submitter_id,
                    from_status_code=None,
                    to_status_code="PENDING",
                    remark=f"提交{field_label}变更审核",
                    created_at=submitted_at,
                )
            )
            if final_action:
                session.add(
                    AuditRecord(
                        task_id=task.id,
                        action_code=final_action,
                        operator_id=handler_id,
                        from_status_code="PENDING",
                        to_status_code=status_code,
                        remark="样例审核意见：资料已核对" if final_action == "APPROVE" else "样例审核意见：需补充依据",
                        created_at=completed_at or submitted_at,
                    )
                )

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_audit_samples())
