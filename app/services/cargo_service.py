"""货品和货源服务"""
import uuid
from typing import Optional, List
from datetime import datetime, date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from fastapi import HTTPException

from app.models.cargo import (
    CommodityCategory, CommodityType, CommodityStandard, CommodityAlias,
    CargoRawMessage, CargoAiParseResult, CargoOpportunity,
)
from app.models.address import TransportNode
from app.models.route import ShippingRoute
from app.schemas.cargo import (
    CommodityCategoryCreate, CommodityCategoryUpdate,
    CommodityTypeCreate, CommodityTypeUpdate,
    CommodityStandardCreate, CommodityStandardUpdate,
    CommodityAliasCreate,
    CargoManualInput, CargoRawMessageCreate, CargoConfirmRequest,
)
from app.schemas.common import PageResult
from app.services import audit_service


def _generate_opportunity_no() -> str:
    return f"CO{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"


# ===== CommodityCategory =====

async def get_categories(db: AsyncSession) -> List[CommodityCategory]:
    result = await db.execute(select(CommodityCategory).order_by(CommodityCategory.sort_order))
    return list(result.scalars().all())


async def get_category(db: AsyncSession, category_id: int) -> CommodityCategory:
    result = await db.execute(select(CommodityCategory).where(CommodityCategory.id == category_id))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="货品大类不存在")
    return obj


async def create_category(
    db: AsyncSession, data: CommodityCategoryCreate, submitter_id: int, submitter_name: str
) -> CommodityCategory:
    obj = CommodityCategory(**data.model_dump(), audit_status=0, submitter_id=submitter_id)
    db.add(obj)
    await db.flush()
    await audit_service.create_audit_record(
        db=db,
        target_type="COMMODITY_CATEGORY",
        target_id=obj.id,
        target_name=obj.name,
        action="CREATE",
        before_data=None,
        after_data=data.model_dump(),
        submitter_id=submitter_id,
        submitter_name=submitter_name,
    )
    return obj


async def update_category(
    db: AsyncSession, category_id: int, data: CommodityCategoryUpdate
) -> CommodityCategory:
    obj = await get_category(db, category_id)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(obj, field, value)
    await db.flush()
    return obj


async def delete_category(db: AsyncSession, category_id: int) -> None:
    obj = await get_category(db, category_id)
    await db.delete(obj)
    await db.flush()


# ===== CommodityType =====

async def get_types(
    db: AsyncSession, category_id: Optional[int] = None
) -> List[CommodityType]:
    query = select(CommodityType)
    if category_id:
        query = query.where(CommodityType.category_id == category_id)
    query = query.order_by(CommodityType.sort_order)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_type(db: AsyncSession, type_id: int) -> CommodityType:
    result = await db.execute(select(CommodityType).where(CommodityType.id == type_id))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="货品类型不存在")
    return obj


async def create_type(
    db: AsyncSession, data: CommodityTypeCreate, submitter_id: int, submitter_name: str
) -> CommodityType:
    obj = CommodityType(**data.model_dump(), audit_status=0, submitter_id=submitter_id)
    db.add(obj)
    await db.flush()
    await audit_service.create_audit_record(
        db=db,
        target_type="COMMODITY_TYPE",
        target_id=obj.id,
        target_name=obj.name,
        action="CREATE",
        before_data=None,
        after_data=data.model_dump(),
        submitter_id=submitter_id,
        submitter_name=submitter_name,
    )
    return obj


async def update_type(
    db: AsyncSession, type_id: int, data: CommodityTypeUpdate
) -> CommodityType:
    obj = await get_type(db, type_id)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(obj, field, value)
    await db.flush()
    return obj


async def delete_type(db: AsyncSession, type_id: int) -> None:
    obj = await get_type(db, type_id)
    await db.delete(obj)
    await db.flush()


# ===== CommodityStandard =====

async def get_standards(
    db: AsyncSession,
    type_id: Optional[int] = None,
    audit_status: Optional[int] = None,
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    query = select(CommodityStandard)
    count_query = select(func.count(CommodityStandard.id))
    conditions = []
    if type_id:
        conditions.append(CommodityStandard.type_id == type_id)
    if audit_status is not None:
        conditions.append(CommodityStandard.audit_status == audit_status)
    if keyword:
        conditions.append(CommodityStandard.name.ilike(f"%{keyword}%"))
    if conditions:
        query = query.where(and_(*conditions))
        count_query = count_query.where(and_(*conditions))

    total_res = await db.execute(count_query)
    total = total_res.scalar_one()
    query = query.order_by(CommodityStandard.sort_order).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return PageResult(total=total, items=list(result.scalars().all()), page=page, page_size=page_size)


async def get_standard(db: AsyncSession, standard_id: int) -> CommodityStandard:
    result = await db.execute(select(CommodityStandard).where(CommodityStandard.id == standard_id))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="标准货品不存在")
    return obj


async def create_standard(
    db: AsyncSession, data: CommodityStandardCreate, submitter_id: int, submitter_name: str
) -> CommodityStandard:
    obj = CommodityStandard(**data.model_dump(), audit_status=0, submitter_id=submitter_id)
    db.add(obj)
    await db.flush()
    await audit_service.create_audit_record(
        db=db,
        target_type="COMMODITY_STANDARD",
        target_id=obj.id,
        target_name=obj.name,
        action="CREATE",
        before_data=None,
        after_data=data.model_dump(),
        submitter_id=submitter_id,
        submitter_name=submitter_name,
    )
    return obj


async def update_standard(
    db: AsyncSession, standard_id: int, data: CommodityStandardUpdate
) -> CommodityStandard:
    obj = await get_standard(db, standard_id)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(obj, field, value)
    await db.flush()
    return obj


async def delete_standard(db: AsyncSession, standard_id: int) -> None:
    obj = await get_standard(db, standard_id)
    await db.delete(obj)
    await db.flush()


async def approve_commodity(
    db: AsyncSession, standard_id: int, auditor_id: int, auditor_name: str, remark: str = ""
) -> CommodityStandard:
    from app.models.audit import AuditRecord
    res = await db.execute(
        select(AuditRecord).where(
            and_(
                AuditRecord.target_type == "COMMODITY_STANDARD",
                AuditRecord.target_id == standard_id,
                AuditRecord.audit_result == "PENDING",
            )
        ).order_by(AuditRecord.id.desc())
    )
    record = res.scalar_one_or_none()
    if not record:
        obj = await get_standard(db, standard_id)
        obj.audit_status = 1
        obj.auditor_id = auditor_id
        await db.flush()
        return obj
    await audit_service.approve(db, record.id, auditor_id, auditor_name, remark)
    return await get_standard(db, standard_id)


async def reject_commodity(
    db: AsyncSession, standard_id: int, auditor_id: int, auditor_name: str, remark: str
) -> CommodityStandard:
    from app.models.audit import AuditRecord
    res = await db.execute(
        select(AuditRecord).where(
            and_(
                AuditRecord.target_type == "COMMODITY_STANDARD",
                AuditRecord.target_id == standard_id,
                AuditRecord.audit_result == "PENDING",
            )
        ).order_by(AuditRecord.id.desc())
    )
    record = res.scalar_one_or_none()
    if not record:
        obj = await get_standard(db, standard_id)
        obj.audit_status = 2
        obj.audit_remark = remark
        obj.auditor_id = auditor_id
        await db.flush()
        return obj
    await audit_service.reject(db, record.id, auditor_id, auditor_name, remark)
    return await get_standard(db, standard_id)


# ===== CommodityAlias =====

async def add_commodity_alias(db: AsyncSession, data: CommodityAliasCreate) -> CommodityAlias:
    alias = CommodityAlias(**data.model_dump())
    db.add(alias)
    await db.flush()
    return alias


async def delete_commodity_alias(db: AsyncSession, alias_id: int) -> None:
    result = await db.execute(select(CommodityAlias).where(CommodityAlias.id == alias_id))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="别名不存在")
    await db.delete(obj)
    await db.flush()


# ===== CargoOpportunity =====

async def _resolve_region_and_route(
    db: AsyncSession, origin_node_id: int, dest_node_id: int
) -> tuple:
    """Resolve origin_region_id, dest_region_id, route_id from nodes"""
    origin_res = await db.execute(select(TransportNode).where(TransportNode.id == origin_node_id))
    origin_node = origin_res.scalar_one_or_none()
    dest_res = await db.execute(select(TransportNode).where(TransportNode.id == dest_node_id))
    dest_node = dest_res.scalar_one_or_none()

    origin_region_id = origin_node.region_id if origin_node else None
    dest_region_id = dest_node.region_id if dest_node else None

    route_id = None
    if origin_region_id and dest_region_id:
        route_res = await db.execute(
            select(ShippingRoute).where(
                and_(
                    ShippingRoute.origin_region_id == origin_region_id,
                    ShippingRoute.dest_region_id == dest_region_id,
                    ShippingRoute.status == 1,
                )
            )
        )
        route = route_res.scalar_one_or_none()
        if route:
            route_id = route.id

    return origin_region_id, dest_region_id, route_id


async def create_cargo_manual(
    db: AsyncSession, data: CargoManualInput, collector_id: int
) -> CargoOpportunity:
    """手动录入货源 - 直接进入 CONFIRMED 状态"""
    origin_region_id, dest_region_id, route_id = await _resolve_region_and_route(
        db, data.origin_node_id, data.dest_node_id
    )
    cargo = CargoOpportunity(
        opportunity_no=_generate_opportunity_no(),
        origin_node_id=data.origin_node_id,
        dest_node_id=data.dest_node_id,
        commodity_id=data.commodity_id,
        tonnage=data.tonnage,
        origin_region_id=origin_region_id,
        dest_region_id=dest_region_id,
        route_id=route_id,
        loading_date=data.loading_date,
        freight_price=data.freight_price,
        price_type=data.price_type,
        price_unit=data.price_unit,
        contact_person=data.contact_person,
        contact_phone=data.contact_phone,
        source_type=data.source_type,
        remark=data.remark,
        status="CONFIRMED",
        input_type="MANUAL",
        collector_id=collector_id,
    )
    db.add(cargo)
    await db.flush()
    return cargo


async def create_cargo_text(
    db: AsyncSession,
    data: CargoRawMessageCreate,
    collector_id: int,
) -> CargoRawMessage:
    """粘贴文本创建原始货源记录，触发 AI 解析"""
    raw_msg = CargoRawMessage(
        raw_text=data.raw_text,
        source_type=data.source_type,
        group_name=data.group_name,
        sender_name=data.sender_name,
        collector_id=collector_id,
        status="PENDING",
        message_time=datetime.utcnow(),
    )
    db.add(raw_msg)
    await db.flush()

    # Trigger async AI parse (actual AI call handled separately)
    # Mark as parsing
    raw_msg.status = "PARSING"
    await db.flush()

    return raw_msg


async def confirm_cargo_ai(
    db: AsyncSession,
    parse_result_id: int,
    confirm_data: CargoConfirmRequest,
    user_id: int,
) -> CargoOpportunity:
    """确认 AI 解析结果，创建正式货源记录"""
    res = await db.execute(select(CargoAiParseResult).where(CargoAiParseResult.id == parse_result_id))
    parse_result = res.scalar_one_or_none()
    if not parse_result:
        raise HTTPException(status_code=404, detail="解析结果不存在")
    if parse_result.parse_status != "PENDING_CONFIRM":
        raise HTTPException(status_code=400, detail="该解析结果已处理")

    # Override with confirmed data
    origin_node_id = confirm_data.origin_node_id or parse_result.origin_node_id
    dest_node_id = confirm_data.dest_node_id or parse_result.dest_node_id
    commodity_id = confirm_data.commodity_id or parse_result.commodity_id
    tonnage = confirm_data.tonnage or parse_result.tonnage

    if not all([origin_node_id, dest_node_id, commodity_id, tonnage]):
        raise HTTPException(status_code=400, detail="必填字段缺失：起点、终点、货品、吨位")

    origin_region_id, dest_region_id, route_id = await _resolve_region_and_route(
        db, origin_node_id, dest_node_id
    )

    cargo = CargoOpportunity(
        opportunity_no=_generate_opportunity_no(),
        origin_node_id=origin_node_id,
        dest_node_id=dest_node_id,
        commodity_id=commodity_id,
        tonnage=tonnage,
        origin_region_id=origin_region_id,
        dest_region_id=dest_region_id,
        route_id=route_id,
        loading_date=confirm_data.loading_date or parse_result.loading_date,
        freight_price=confirm_data.freight_price or parse_result.freight_price,
        price_type=confirm_data.price_type or parse_result.price_type,
        contact_person=confirm_data.contact_person or parse_result.contact_person,
        contact_phone=confirm_data.contact_phone or parse_result.contact_phone,
        remark=confirm_data.remark,
        raw_message_id=parse_result.raw_message_id,
        parse_result_id=parse_result.id,
        status="CONFIRMED",
        input_type="AI_PARSE",
        collector_id=user_id,
    )
    db.add(cargo)

    # Update parse result status
    parse_result.parse_status = "CONFIRMED"
    parse_result.confirmed_by = user_id
    parse_result.confirmed_at = datetime.utcnow()

    await db.flush()
    return cargo


async def discard_cargo_ai(
    db: AsyncSession, parse_result_id: int, reason: Optional[str], user_id: int
) -> CargoAiParseResult:
    res = await db.execute(select(CargoAiParseResult).where(CargoAiParseResult.id == parse_result_id))
    parse_result = res.scalar_one_or_none()
    if not parse_result:
        raise HTTPException(status_code=404, detail="解析结果不存在")
    if parse_result.parse_status != "PENDING_CONFIRM":
        raise HTTPException(status_code=400, detail="该解析结果已处理")
    parse_result.parse_status = "DISCARDED"
    parse_result.discard_reason = reason
    parse_result.confirmed_by = user_id
    parse_result.confirmed_at = datetime.utcnow()
    await db.flush()
    return parse_result


async def get_cargo_opportunities(
    db: AsyncSession,
    status: Optional[str] = None,
    origin_region_id: Optional[int] = None,
    dest_region_id: Optional[int] = None,
    commodity_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    query = select(CargoOpportunity)
    count_query = select(func.count(CargoOpportunity.id))
    conditions = []
    if status:
        conditions.append(CargoOpportunity.status == status)
    if origin_region_id:
        conditions.append(CargoOpportunity.origin_region_id == origin_region_id)
    if dest_region_id:
        conditions.append(CargoOpportunity.dest_region_id == dest_region_id)
    if commodity_id:
        conditions.append(CargoOpportunity.commodity_id == commodity_id)
    if start_date:
        conditions.append(CargoOpportunity.loading_date >= start_date)
    if end_date:
        conditions.append(CargoOpportunity.loading_date <= end_date)
    if conditions:
        query = query.where(and_(*conditions))
        count_query = count_query.where(and_(*conditions))

    total_res = await db.execute(count_query)
    total = total_res.scalar_one()
    query = query.order_by(CargoOpportunity.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return PageResult(total=total, items=list(result.scalars().all()), page=page, page_size=page_size)


async def get_cargo_opportunity(db: AsyncSession, cargo_id: int) -> CargoOpportunity:
    result = await db.execute(select(CargoOpportunity).where(CargoOpportunity.id == cargo_id))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="货源不存在")
    return obj


async def cancel_cargo(db: AsyncSession, cargo_id: int) -> CargoOpportunity:
    cargo = await get_cargo_opportunity(db, cargo_id)
    cargo.status = "CANCELLED"
    await db.flush()
    return cargo


async def get_ai_parse_results(
    db: AsyncSession,
    parse_status: Optional[str] = "PENDING_CONFIRM",
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    query = select(CargoAiParseResult)
    count_query = select(func.count(CargoAiParseResult.id))
    if parse_status:
        query = query.where(CargoAiParseResult.parse_status == parse_status)
        count_query = count_query.where(CargoAiParseResult.parse_status == parse_status)

    total_res = await db.execute(count_query)
    total = total_res.scalar_one()
    query = query.order_by(CargoAiParseResult.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return PageResult(total=total, items=list(result.scalars().all()), page=page, page_size=page_size)


async def get_parse_result(db: AsyncSession, parse_result_id: int) -> CargoAiParseResult:
    result = await db.execute(select(CargoAiParseResult).where(CargoAiParseResult.id == parse_result_id))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="解析结果不存在")
    return obj


async def get_raw_message(db: AsyncSession, raw_message_id: int) -> CargoRawMessage:
    result = await db.execute(select(CargoRawMessage).where(CargoRawMessage.id == raw_message_id))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="原始消息不存在")
    return obj
