"""一期数据接入域 API 聚合入口"""
from datetime import datetime

from fastapi import APIRouter
from fastapi import Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_vessel_service
from app.core.security import require_roles
from app.models.cargo import TmsCargoRaw
from app.repositories.cargo_repository import CargoRepository
from app.schemas.common import success
from app.services.vessel_service import VesselService
from app.utils.excel_utils import parse_vessel_excel
from app.api.v1.freight.router import router as freight_router

router = APIRouter()

# 微信文本接入、AI解析确认、手工录入等货源接入链路
router.include_router(freight_router, prefix="/cargo", tags=["数据接入-货源"]) 


def _parse_dt(value):
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


@router.post("/cargo/tms/raw", summary="TMS货源原始数据接入")
async def ingest_tms_raw(
    body: dict,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR", "COLLECTOR")),
):
    tms_message_id = str(body.get("tms_message_id") or "").strip()
    payload = body.get("raw_payload")
    if not tms_message_id or payload is None:
        raise HTTPException(status_code=400, detail="tms_message_id 和 raw_payload 必填")
    repo = CargoRepository(db)
    existing = await repo.get_tms_raw_by_msg_id(tms_message_id)
    if existing:
        return success(data={"id": existing.id, "message": "重复消息已忽略"})

    saved = await repo.create_tms_raw(
        TmsCargoRaw(
            tms_message_id=tms_message_id,
            raw_payload=payload,
            tms_origin_name=body.get("tms_origin_name"),
            tms_origin_lng=body.get("tms_origin_lng"),
            tms_origin_lat=body.get("tms_origin_lat"),
            tms_origin_region=body.get("tms_origin_region"),
            tms_dest_name=body.get("tms_dest_name"),
            tms_dest_lng=body.get("tms_dest_lng"),
            tms_dest_lat=body.get("tms_dest_lat"),
            tms_dest_region=body.get("tms_dest_region"),
            process_status="PENDING",
        )
    )
    await repo.save()
    return success(data={"id": saved.id, "tms_message_id": tms_message_id})


@router.post("/vessel/dynamic/{mmsi}", summary="AIS/监控船舶动态接入")
async def ingest_vessel_dynamic(
    mmsi: str,
    body: dict,
    service: VesselService = Depends(get_vessel_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR", "COLLECTOR")),
):
    user, _ = user_roles
    dynamic = await service.update_dynamic_by_mmsi(
        mmsi=mmsi,
        operator_id=user.id,
        data_source=body.get("data_source", "AIS"),
        reported_at=_parse_dt(body.get("reported_at")),
        current_longitude=body.get("current_longitude"),
        current_latitude=body.get("current_latitude"),
        current_city_code=body.get("current_city_code"),
        current_region_id=body.get("current_region_id"),
        position_match_type=body.get("position_match_type", "UNKNOWN"),
        position_match_distance_m=body.get("position_match_distance_m"),
        vessel_status=body.get("vessel_status", "UNDERWAY"),
        speed=body.get("speed"),
        heading=body.get("heading"),
        current_node_id=body.get("current_node_id"),
        dest_node_id=body.get("dest_node_id"),
        eta=_parse_dt(body.get("eta")),
        cargo_info=body.get("cargo_info"),
        remark=body.get("remark"),
    )
    return success(data={"id": dynamic.id, "mmsi": dynamic.mmsi})


@router.post("/excel/vessel", summary="Excel批量船舶接入")
async def ingest_vessel_excel(
    file: UploadFile = File(...),
    service: VesselService = Depends(get_vessel_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR", "COLLECTOR")),
):
    user, _ = user_roles
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 格式文件")
    content = await file.read()
    try:
        rows = parse_vessel_excel(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = await service.bulk_register_vessels(rows=rows, operator_id=user.id)
    return success(data=result)
