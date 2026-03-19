"""一期数据接入域 - 船舶动态与批量接入入口"""
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.core.dependencies import get_vessel_service
from app.core.security import require_roles
from app.schemas.common import success
from app.domain.vessel.service import VesselService
from app.utils.excel_utils import parse_vessel_excel

router = APIRouter()


def _parse_dt(value):
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


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
