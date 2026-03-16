"""
船舶业务服务层
职责：船舶档案、动态数据、历史记录相关业务逻辑
规则：通过Repository访问数据，不直接操作SQLAlchemy Session
"""
import json
import logging
from typing import Optional

from app.core.exceptions import NotFoundError, ConflictError
from app.models.vessel import Vessel, VesselTypeDict, VesselNameHistory, VesselDynamic
from app.models.audit import AuditRecord
from app.repositories.vessel_repository import VesselRepository
from app.repositories.audit_repository import AuditRepository

logger = logging.getLogger(__name__)


class VesselService:
    """船舶业务服务"""

    def __init__(self, vessel_repo: VesselRepository, audit_repo: AuditRepository) -> None:
        self._vessel = vessel_repo
        self._audit = audit_repo

    # ─────────────────────────────────────────────────
    # 船型字典
    # ─────────────────────────────────────────────────

    async def list_vessel_types(self, status: Optional[int] = None):
        return await self._vessel.list_vessel_types(status=status)

    async def get_vessel_type(self, type_id: int) -> VesselTypeDict:
        vt = await self._vessel.get_vessel_type(type_id)
        if not vt:
            raise NotFoundError("VesselTypeDict", type_id)
        return vt

    async def create_vessel_type(
        self, name: str, code: str, operator_id: int, **kwargs
    ) -> VesselTypeDict:
        vt = VesselTypeDict(name=name, code=code, submitter_id=operator_id, audit_status=0, **kwargs)
        saved = await self._vessel.create_vessel_type(vt)
        await self._record_audit(operator_id, "CREATE", "VESSEL_TYPE", saved.id,
                                 after_data={"name": name, "code": code})
        await self._vessel.save()
        return saved

    async def update_vessel_type(self, type_id: int, operator_id: int, **kwargs) -> VesselTypeDict:
        vt = await self.get_vessel_type(type_id)
        before = {"name": vt.name}
        updated = await self._vessel.update_vessel_type(type_id, **kwargs)
        await self._record_audit(operator_id, "UPDATE", "VESSEL_TYPE", type_id,
                                 before_data=before, after_data=kwargs)
        await self._vessel.save()
        return updated

    async def delete_vessel_type(self, type_id: int, operator_id: int) -> None:
        await self.get_vessel_type(type_id)
        await self._vessel.delete_vessel_type(type_id)
        await self._record_audit(operator_id, "DELETE", "VESSEL_TYPE", type_id)
        await self._vessel.save()

    async def approve_vessel_type(
        self, type_id: int, auditor_id: int, remark: str = ""
    ) -> VesselTypeDict:
        await self.get_vessel_type(type_id)
        updated = await self._vessel.update_vessel_type(type_id, audit_status=1)
        await self._record_audit(auditor_id, "APPROVE", "VESSEL_TYPE", type_id,
                                 after_data={"audit_status": 1, "remark": remark})
        await self._vessel.save()
        return updated

    async def reject_vessel_type(
        self, type_id: int, auditor_id: int, remark: str
    ) -> VesselTypeDict:
        await self.get_vessel_type(type_id)
        updated = await self._vessel.update_vessel_type(type_id, audit_status=2)
        await self._record_audit(auditor_id, "REJECT", "VESSEL_TYPE", type_id,
                                 after_data={"audit_status": 2, "remark": remark})
        await self._vessel.save()
        return updated

    # ─────────────────────────────────────────────────
    # 船舶档案
    # ─────────────────────────────────────────────────

    async def list_vessels(
        self,
        audit_status: Optional[int] = None,
        vessel_type_id: Optional[int] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        offset = (page - 1) * page_size
        items, total = await self._vessel.list_vessels(
            vessel_type_id=vessel_type_id,
            audit_status=audit_status,
            keyword=keyword,
            offset=offset,
            limit=page_size,
        )
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def get_vessel(self, vessel_id: int) -> Vessel:
        vessel = await self._vessel.get_vessel(vessel_id)
        if not vessel:
            raise NotFoundError("Vessel", vessel_id)
        return vessel

    async def register_vessel(
        self,
        vessel_name: str,
        vessel_type_id: int,
        operator_id: int,
        mmsi: Optional[str] = None,
        submitter_id: Optional[int] = None,
        **kwargs,
    ) -> Vessel:
        if mmsi:
            existing = await self._vessel.get_vessel_by_mmsi(mmsi)
            if existing:
                raise ConflictError(f"MMSI '{mmsi}' already registered")
        vessel = Vessel(
            vessel_name=vessel_name, mmsi=mmsi,
            vessel_type_id=vessel_type_id,
            submitter_id=submitter_id or operator_id,
            audit_status=0,
            **kwargs,
        )
        saved = await self._vessel.create_vessel(vessel)
        await self._record_audit(operator_id, "CREATE", "VESSEL", saved.id,
                                 after_data={"vessel_name": vessel_name, "mmsi": mmsi})
        await self._vessel.save()
        return saved

    async def update_vessel(self, vessel_id: int, operator_id: int, **kwargs) -> Vessel:
        vessel = await self.get_vessel(vessel_id)
        before = {"vessel_name": vessel.vessel_name, "mmsi": vessel.mmsi}
        # 船名变更记录历史
        new_name = kwargs.get("vessel_name")
        if new_name and new_name != vessel.vessel_name:
            history = VesselNameHistory(
                vessel_id=vessel_id, old_name=vessel.vessel_name,
                new_name=new_name, changed_by=operator_id,
            )
            await self._vessel.create_name_history(history)
        updated = await self._vessel.update_vessel(vessel_id, **kwargs)
        await self._record_audit(operator_id, "UPDATE", "VESSEL", vessel_id,
                                 before_data=before, after_data=kwargs)
        await self._vessel.save()
        return updated

    async def delete_vessel(self, vessel_id: int, operator_id: int) -> None:
        vessel = await self.get_vessel(vessel_id)
        await self._vessel.delete_vessel(vessel_id)
        await self._record_audit(operator_id, "DELETE", "VESSEL", vessel_id,
                                 before_data={"vessel_name": vessel.vessel_name})
        await self._vessel.save()

    async def approve_vessel(self, vessel_id: int, auditor_id: int, remark: str = "") -> Vessel:
        await self.get_vessel(vessel_id)
        updated = await self._vessel.update_vessel(vessel_id, audit_status=1)
        await self._record_audit(auditor_id, "APPROVE", "VESSEL", vessel_id,
                                 after_data={"audit_status": 1, "remark": remark})
        await self._vessel.save()
        return updated

    async def reject_vessel(self, vessel_id: int, auditor_id: int, remark: str) -> Vessel:
        await self.get_vessel(vessel_id)
        updated = await self._vessel.update_vessel(vessel_id, audit_status=2)
        await self._record_audit(auditor_id, "REJECT", "VESSEL", vessel_id,
                                 after_data={"audit_status": 2, "remark": remark})
        await self._vessel.save()
        return updated

    # ─────────────────────────────────────────────────
    # 船舶动态
    # ─────────────────────────────────────────────────

    async def get_dynamic(self, vessel_id: int) -> Optional[VesselDynamic]:
        await self.get_vessel(vessel_id)
        return await self._vessel.get_dynamic(vessel_id)

    async def update_dynamic(self, vessel_id: int, operator_id: int, **kwargs) -> VesselDynamic:
        await self.get_vessel(vessel_id)
        dynamic = await self._vessel.upsert_dynamic(vessel_id, **kwargs)
        await self._vessel.save()
        return dynamic

    # ─────────────────────────────────────────────────
    # 历史记录
    # ─────────────────────────────────────────────────

    async def get_vessel_history(self, vessel_id: int) -> dict:
        await self.get_vessel(vessel_id)
        name_history = await self._vessel.list_name_history(vessel_id)
        ais_history = await self._vessel.list_ais_history(vessel_id)
        return {"name_history": name_history, "ais_history": ais_history}

    async def get_name_history(self, vessel_id: int):
        await self.get_vessel(vessel_id)
        return await self._vessel.list_name_history(vessel_id)

    # ─────────────────────────────────────────────────
    # 内部辅助
    # ─────────────────────────────────────────────────

    async def _record_audit(
        self,
        operator_id: int,
        action: str,
        target_type: str,
        target_id: int,
        before_data: Optional[dict] = None,
        after_data: Optional[dict] = None,
    ) -> None:
        record = AuditRecord(
            operator_id=operator_id, action=action,
            target_type=target_type, target_id=target_id,
            audit_status="APPROVED",
            before_data=json.dumps(before_data, ensure_ascii=False) if before_data else None,
            after_data=json.dumps(after_data, ensure_ascii=False) if after_data else None,
        )
        await self._audit.create_record(record)
