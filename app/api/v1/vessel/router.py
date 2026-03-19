"""船舶路由 — 使用 DI 模式调用 VesselService"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File

from app.core.dependencies import get_vessel_service
from app.core.security import get_current_user_roles, require_roles
from app.schemas.vessel import (
    VesselTypeDictCreate, VesselTypeDictUpdate, VesselTypeDictResponse,
    VesselCreate, VesselUpdate, VesselResponse,
    VesselDynamicUpdate, VesselDynamicResponse,
    VesselNameHistoryResponse, VesselAisHistoryResponse,
    VesselDynamicKafkaMessage,
)
from app.schemas.common import success
from app.services.vessel_service import VesselService
from app.utils.excel_utils import parse_vessel_excel

router = APIRouter()


# ===== VesselTypeDict =====

@router.get("/vessel-type", summary="获取船舶类型列表（全量，用于下拉）")
async def list_vessel_types(
    status: Optional[int] = None,
    service: VesselService = Depends(get_vessel_service),
    _=Depends(get_current_user_roles),
):
    items = await service.list_vessel_types(status=status)
    return success(data=[VesselTypeDictResponse.model_validate(i) for i in items])


@router.get("/vessel-type/list", summary="船舶类型分页查询")
async def list_vessel_types_paginated(
    status: Optional[int] = Query(None),
    keyword: Optional[str] = Query(None, description="名称/编码关键词"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: VesselService = Depends(get_vessel_service),
    _=Depends(get_current_user_roles),
):
    result = await service.list_vessel_types_paginated(
        status=status, keyword=keyword, page=page, page_size=page_size
    )
    return success(data={
        "total": result["total"],
        "items": [VesselTypeDictResponse.model_validate(i) for i in result["items"]],
        "page": result["page"],
        "page_size": result["page_size"],
    })


@router.post("/vessel-type", summary="创建船舶类型（待审核）")
async def create_vessel_type(
    data: VesselTypeDictCreate,
    service: VesselService = Depends(get_vessel_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, _ = user_roles
    obj = await service.create_vessel_type(
        name=data.name, code=data.code, operator_id=user.id,
        **data.model_dump(exclude={"name", "code"}, exclude_none=True)
    )
    return success(data=VesselTypeDictResponse.model_validate(obj))


@router.put("/vessel-type/{type_id}", summary="更新船舶类型")
async def update_vessel_type(
    type_id: int,
    data: VesselTypeDictUpdate,
    service: VesselService = Depends(get_vessel_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, _ = user_roles
    obj = await service.update_vessel_type(
        type_id=type_id, operator_id=user.id,
        **data.model_dump(exclude_none=True)
    )
    return success(data=VesselTypeDictResponse.model_validate(obj))


@router.delete("/vessel-type/{type_id}", summary="删除船舶类型")
async def delete_vessel_type(
    type_id: int,
    service: VesselService = Depends(get_vessel_service),
    user_roles=Depends(require_roles("ADMIN")),
):
    user, _ = user_roles
    await service.delete_vessel_type(type_id=type_id, operator_id=user.id)
    return success(message="删除成功")


# ===== Vessel =====

@router.get("/vessel", summary="获取船舶列表")
async def list_vessels(
    audit_status: Optional[int] = None,
    vessel_type_id: Optional[int] = None,
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    service: VesselService = Depends(get_vessel_service),
    _=Depends(get_current_user_roles),
):
    result = await service.list_vessels(
        audit_status=audit_status, vessel_type_id=vessel_type_id,
        keyword=keyword, page=page, page_size=page_size,
    )
    return success(data={
        "total": result["total"],
        "items": [VesselResponse.model_validate(i) for i in result["items"]],
        "page": result["page"],
        "page_size": result["page_size"],
    })


@router.post("/vessel", summary="录入船舶（待审核）")
async def create_vessel(
    data: VesselCreate,
    service: VesselService = Depends(get_vessel_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR", "COLLECTOR")),
):
    user, _ = user_roles
    obj = await service.register_vessel(
        vessel_name=data.vessel_name,
        vessel_type_id=data.vessel_type_id,
        operator_id=user.id,
        mmsi=getattr(data, "mmsi", None),
        submitter_id=user.id,
        **{k: v for k, v in data.model_dump(exclude_none=True).items()
           if k not in {"vessel_name", "vessel_type_id", "mmsi"}}
    )
    return success(data=VesselResponse.model_validate(obj))


@router.post("/vessel/import", summary="批量导入船舶（Excel .xlsx）")
async def import_vessels(
    file: UploadFile = File(..., description="Excel文件，格式见模板"),
    service: VesselService = Depends(get_vessel_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    """
    通过 Excel 批量录入船舶，每条船记录仍独立进入审核流程。
    Excel 第一行为表头，必填列：vessel_no、vessel_name。
    """
    user, _ = user_roles
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 格式文件")
    content = await file.read()
    try:
        rows = parse_vessel_excel(content)
    except Exception:
        raise HTTPException(status_code=400, detail="Excel 文件损坏或格式不正确")
    if not rows:
        raise HTTPException(status_code=400, detail="Excel 文件为空或格式不正确")
    result = await service.bulk_register_vessels(rows=rows, operator_id=user.id)
    return success(data=result)


@router.get("/vessel/{vessel_id}", summary="获取船舶详情")
async def get_vessel(
    vessel_id: int,
    service: VesselService = Depends(get_vessel_service),
    _=Depends(get_current_user_roles),
):
    obj = await service.get_vessel(vessel_id)
    return success(data=VesselResponse.model_validate(obj))


@router.put("/vessel/{vessel_id}", summary="更新船舶")
async def update_vessel(
    vessel_id: int,
    data: VesselUpdate,
    service: VesselService = Depends(get_vessel_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, _ = user_roles
    obj = await service.update_vessel(
        vessel_id=vessel_id, operator_id=user.id,
        **data.model_dump(exclude_none=True)
    )
    return success(data=VesselResponse.model_validate(obj))


@router.delete("/vessel/{vessel_id}", summary="删除船舶")
async def delete_vessel(
    vessel_id: int,
    service: VesselService = Depends(get_vessel_service),
    user_roles=Depends(require_roles("ADMIN")),
):
    user, _ = user_roles
    await service.delete_vessel(vessel_id=vessel_id, operator_id=user.id)
    return success(message="删除成功")


@router.get("/vessel/{vessel_id}/history", summary="获取船舶历史（船名+AIS）")
async def get_vessel_history(
    vessel_id: int,
    service: VesselService = Depends(get_vessel_service),
    _=Depends(get_current_user_roles),
):
    history = await service.get_vessel_history(vessel_id)
    return success(data={
        "name_history": [VesselNameHistoryResponse.model_validate(i) for i in history["name_history"]],
        "ais_history": [VesselAisHistoryResponse.model_validate(i) for i in history["ais_history"]],
    })


@router.get("/vessel/dynamic/{mmsi}", summary="获取船舶最新动态")
async def get_vessel_dynamic_by_mmsi(
    mmsi: str,
    service: VesselService = Depends(get_vessel_service),
    _=Depends(get_current_user_roles),
):
    obj = await service.get_dynamic_by_mmsi(mmsi)
    if not obj:
        return success(data=None, message="暂无动态信息")
    return success(data=VesselDynamicResponse.model_validate(obj))


@router.put("/vessel/dynamic/{mmsi}", summary="更新船舶动态（无记录自动新增，有记录则更新）")
async def update_vessel_dynamic_by_mmsi(
    mmsi: str,
    data: VesselDynamicUpdate,
    service: VesselService = Depends(get_vessel_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR", "COLLECTOR")),
):
    user, _ = user_roles
    obj = await service.update_dynamic_by_mmsi(
        mmsi=mmsi, operator_id=user.id,
        **data.model_dump(exclude_none=True)
    )
    return success(data=VesselDynamicResponse.model_validate(obj))
