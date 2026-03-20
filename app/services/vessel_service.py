"""
船舶业务服务层
职责：船舶档案、动态数据、历史记录相关业务逻辑
规则：通过Repository访问数据，不直接操作SQLAlchemy Session
"""
import asyncio
import logging
from datetime import datetime
from math import cos, radians, sqrt
from typing import Optional

from app.core.exceptions import NotFoundError, ConflictError
from app.models.vessel import Vessel, VesselTypeDict, VesselNameHistory, VesselAisHistory, VesselDynamic
from app.repositories.address_repository import AddressRepository
from app.repositories.vessel_repository import VesselRepository
from app.services.audit_service import AuditService
from app.utils.region_helpers import point_in_polygon

logger = logging.getLogger(__name__)


def _schedule_static_stat_refresh_task() -> None:
    """在后台 asyncio Task 中触发静态船舶统计刷新（DWT + 船龄分布）"""
    async def _run() -> None:
        try:
            from app.tasks.stat_tasks import refresh_vessel_static_stats
            await refresh_vessel_static_stats()
        except Exception as exc:
            logger.warning("静态船舶统计刷新失败: %s", exc)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run())
    except RuntimeError:
        # 非 async 上下文（理论上不会发生），降级为同步忽略
        logger.warning("无法调度静态船舶统计刷新：没有运行中的事件循环")


class VesselService:
    """船舶业务服务"""

    def __init__(
        self,
        vessel_repo: VesselRepository,
        audit_svc: AuditService,
        address_repo: Optional[AddressRepository] = None,
    ) -> None:
        self._vessel = vessel_repo
        self._audit_svc = audit_svc
        self._address = address_repo

    @staticmethod
    def _schedule_static_stat_refresh() -> None:
        """调度后台 Task 刷新 DWT / 船龄分布快照（fire-and-forget）"""
        _schedule_static_stat_refresh_task()

    @staticmethod
    def _distance_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
        """近似平面距离（米），用于城市质心粗匹配。"""
        mean_lat = radians((lat1 + lat2) / 2.0)
        kx = 111320 * cos(mean_lat)
        ky = 110540
        return sqrt(((lon1 - lon2) * kx) ** 2 + ((lat1 - lat2) * ky) ** 2)

    async def _enrich_dynamic_kwargs(self, kwargs: dict) -> dict:
        """补齐一期动态分析字段，保证写入结构与统计逻辑一致。"""
        if self._address is None:
            kwargs.setdefault("reported_at", datetime.now())
            kwargs.setdefault("data_source", "MANUAL")
            return kwargs

        node_id = kwargs.get("current_node_id")
        lon = kwargs.get("current_longitude")
        lat = kwargs.get("current_latitude")

        if node_id:
            node = await self._address.get_node(node_id)
            if node:
                if not kwargs.get("current_city_code") and node.city_code:
                    kwargs["current_city_code"] = node.city_code
                if not kwargs.get("current_region_id"):
                    rid = await self._address.get_node_primary_region_id(node.id)
                    if rid:
                        kwargs["current_region_id"] = rid
                kwargs.setdefault("position_match_type", "NODE")
                kwargs.setdefault("position_match_distance_m", 0)

        if lon is not None and lat is not None:
            lon_f = float(lon)
            lat_f = float(lat)

            if not kwargs.get("current_city_code"):
                city_rows = await self._address.list_city_centroids()
                nearest = None
                min_dist = None
                for row in city_rows:
                    if row.longitude is None or row.latitude is None:
                        continue
                    dist = self._distance_m(
                        lon_f,
                        lat_f,
                        float(row.longitude),
                        float(row.latitude),
                    )
                    if min_dist is None or dist < min_dist:
                        min_dist = dist
                        nearest = row
                if nearest:
                    kwargs["current_city_code"] = nearest.code
                    kwargs.setdefault("position_match_type", "CITY_CENTROID")
                    kwargs.setdefault("position_match_distance_m", round(min_dist or 0, 2))

            if not kwargs.get("current_region_id") and kwargs.get("current_city_code"):
                rid = await self._address.get_primary_region_by_city_code(kwargs["current_city_code"])
                if rid:
                    kwargs["current_region_id"] = rid
                    kwargs.setdefault("position_match_type", "CITY_REGION_RELATION")

            if not kwargs.get("current_region_id"):
                regions = await self._address.list_regions_with_boundaries()
                for region in regions:
                    if region.boundary_coordinates and point_in_polygon(
                        lon_f,
                        lat_f,
                        region.boundary_coordinates,
                    ):
                        kwargs["current_region_id"] = region.id
                        kwargs.setdefault("position_match_type", "REGION_POLYGON")
                        kwargs.setdefault("position_match_distance_m", 0)
                        break

        kwargs.setdefault("reported_at", datetime.now())
        kwargs.setdefault("data_source", "MANUAL")
        return kwargs

    # ─────────────────────────────────────────────────
    # 船型字典
    # ─────────────────────────────────────────────────

    async def list_vessel_types(self, status: Optional[int] = None):
        return await self._vessel.list_vessel_types(status=status)

    async def list_vessel_types_paginated(
        self,
        status: Optional[int] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        offset = (page - 1) * page_size
        items, total = await self._vessel.list_vessel_types_paginated(
            status=status, keyword=keyword, offset=offset, limit=page_size
        )
        return {"items": items, "total": total, "page": page, "page_size": page_size}

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
        await self._audit_svc.submit_for_audit(
            target_type="VESSEL_TYPE", target_id=saved.id,
            target_name=name, action="CREATE",
            submitter_id=operator_id,
            after_data={"name": name, "code": code},
        )
        await self._vessel.save()
        return saved

    async def update_vessel_type(self, type_id: int, operator_id: int, **kwargs) -> VesselTypeDict:
        vt = await self.get_vessel_type(type_id)
        before = {"name": vt.name}
        updated = await self._vessel.update_vessel_type(type_id, **kwargs)
        await self._audit_svc.submit_for_audit(
            target_type="VESSEL_TYPE", target_id=type_id,
            target_name=vt.name, action="UPDATE",
            submitter_id=operator_id,
            before_data=before, after_data=kwargs,
        )
        await self._vessel.save()
        return updated

    async def delete_vessel_type(self, type_id: int, operator_id: int) -> None:
        vt = await self.get_vessel_type(type_id)
        await self._vessel.delete_vessel_type(type_id)
        await self._audit_svc.record_operation(
            target_type="VESSEL_TYPE", target_id=type_id,
            target_name=vt.name, action="DELETE", operator_id=operator_id,
            before_data={"name": vt.name},
        )
        await self._vessel.save()


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
        await self._audit_svc.submit_for_audit(
            target_type="VESSEL", target_id=saved.id,
            target_name=vessel_name, action="CREATE",
            submitter_id=operator_id,
            after_data={"vessel_name": vessel_name, "mmsi": mmsi},
        )
        await self._vessel.save()
        # 静态档案变更 → 异步刷新 DWT / 船龄分布快照
        self._schedule_static_stat_refresh()
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
        # MMSI 变更记录历史
        new_mmsi = kwargs.get("mmsi")
        if new_mmsi and vessel.mmsi and new_mmsi != vessel.mmsi:
            ais_history = VesselAisHistory(
                vessel_id=vessel_id, old_mmsi=vessel.mmsi,
                new_mmsi=new_mmsi, changed_by=operator_id,
            )
            await self._vessel.create_ais_history(ais_history)
        updated = await self._vessel.update_vessel(vessel_id, **kwargs)
        await self._audit_svc.submit_for_audit(
            target_type="VESSEL", target_id=vessel_id,
            target_name=vessel.vessel_name, action="UPDATE",
            submitter_id=operator_id,
            before_data=before, after_data=kwargs,
        )
        await self._vessel.save()
        # 静态档案变更 → 异步刷新 DWT / 船龄分布快照
        self._schedule_static_stat_refresh()
        return updated

    async def delete_vessel(self, vessel_id: int, operator_id: int) -> None:
        vessel = await self.get_vessel(vessel_id)
        await self._vessel.delete_vessel(vessel_id)
        await self._audit_svc.record_operation(
            target_type="VESSEL", target_id=vessel_id,
            target_name=vessel.vessel_name, action="DELETE", operator_id=operator_id,
            before_data={"vessel_name": vessel.vessel_name},
        )
        await self._vessel.save()
        # 静态档案变更 → 异步刷新 DWT / 船龄分布快照
        self._schedule_static_stat_refresh()

    async def bulk_register_vessels(
        self,
        rows: list[dict],
        operator_id: int,
    ) -> dict:
        """批量录入船舶，每条船仍需独立审核"""
        success_list = []
        failed_list = []
        for idx, row in enumerate(rows, start=2):  # Excel 第1行是表头，数据从第2行起
            vessel_name = str(row.get("vessel_name") or "").strip()
            vessel_no = str(row.get("vessel_no") or "").strip()
            try:
                if not vessel_name:
                    raise ValueError("vessel_name 不能为空")
                if not vessel_no:
                    raise ValueError("vessel_no 不能为空")
                mmsi = str(row["mmsi"]).strip() if row.get("mmsi") else None
                vessel_type_id = int(row["vessel_type_id"]) if row.get("vessel_type_id") else None
                extra = {
                    k: v for k, v in row.items()
                    if k not in {"vessel_name", "vessel_no", "mmsi", "vessel_type_id"}
                    and v is not None and str(v).strip() != ""
                }
                saved = await self.register_vessel(
                    vessel_name=vessel_name,
                    vessel_type_id=vessel_type_id,
                    operator_id=operator_id,
                    mmsi=mmsi,
                    vessel_no=vessel_no,
                    **extra,
                )
                success_list.append({"row": idx, "vessel_id": saved.id, "vessel_name": vessel_name})
            except Exception as e:
                failed_list.append({"row": idx, "vessel_name": vessel_name, "error": str(e)})
        result = {
            "total": len(rows),
            "success_count": len(success_list),
            "failed_count": len(failed_list),
            "success_list": success_list,
            "failed_list": failed_list,
        }
        if success_list:
            # 批量导入完成后统一触发一次静态统计刷新
            self._schedule_static_stat_refresh()
        return result

    # ─────────────────────────────────────────────────
    # 船舶动态
    # ─────────────────────────────────────────────────

    async def get_dynamic(self, vessel_id: int) -> Optional[VesselDynamic]:
        await self.get_vessel(vessel_id)
        return await self._vessel.get_dynamic(vessel_id)

    async def get_dynamic_by_mmsi(self, mmsi: str) -> Optional[VesselDynamic]:
        return await self._vessel.get_dynamic_by_mmsi(mmsi)

    async def update_dynamic(self, vessel_id: int, operator_id: int, **kwargs) -> VesselDynamic:
        await self.get_vessel(vessel_id)
        kwargs = await self._enrich_dynamic_kwargs(kwargs)
        dynamic = await self._vessel.upsert_dynamic(vessel_id, **kwargs)
        await self._vessel.save()
        return dynamic

    async def update_dynamic_by_mmsi(
        self, mmsi: str, operator_id: Optional[int] = None, **kwargs
    ) -> VesselDynamic:
        """以 MMSI 为键更新船舶动态（REST 接口和 Kafka 消费者共用）"""
        vessel = await self._vessel.get_vessel_by_mmsi(mmsi)
        vessel_id = vessel.id if vessel else None
        kwargs = await self._enrich_dynamic_kwargs(kwargs)
        kwargs["updated_by"] = operator_id
        dynamic = await self._vessel.upsert_dynamic_by_mmsi(mmsi, vessel_id, **kwargs)
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
