"""
货物业务服务层
职责：货物/商品相关业务逻辑编排
规则：只调用Repository，不直接操作SQLAlchemy Session
"""
import logging
import uuid
from typing import Optional

from app.core.exceptions import NotFoundError, ValidationError
from app.models.cargo import (
    CommodityCategory,
    CommodityType,
    CommodityStandard,
    CommodityAlias,
    CargoRawMessage,
    CargoAiParseResult,
    CargoOpportunity,
)
from app.repositories.cargo_repository import CargoRepository
from app.repositories.address_repository import AddressRepository
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class CargoService:
    """
    货物业务服务

    依赖注入：CargoRepository + AddressRepository + AuditService
    不持有SQLAlchemy Session，通过Repository间接访问数据库
    """

    def __init__(
        self,
        cargo_repo: CargoRepository,
        address_repo: AddressRepository,
        audit_svc: AuditService,
    ) -> None:
        self._cargo = cargo_repo
        self._address = address_repo
        self._audit_svc = audit_svc

    # ─────────────────────────────────────────────────
    # 商品分类
    # ─────────────────────────────────────────────────

    async def list_categories(self):
        return await self._cargo.categories.get_all_with_types()

    async def create_category(
        self, name: str, code: str, description: Optional[str], operator_id: int
    ) -> CommodityCategory:
        category = CommodityCategory(
            name=name,
            code=code,
            description=description,
            submitter_id=operator_id,
            audit_status=0,
        )
        saved = await self._cargo.categories.create(category)
        await self._audit_svc.submit_for_audit(
            target_type="COMMODITY_CATEGORY", target_id=saved.id,
            target_name=name, action="CREATE",
            submitter_id=operator_id,
            after_data={"name": saved.name, "code": saved.code},
        )
        await self._cargo.save()
        logger.info(f"[CargoService] category created id={saved.id}")
        return saved

    # ─────────────────────────────────────────────────
    # 商品类型
    # ─────────────────────────────────────────────────

    async def list_types_by_category(self, category_id: int):
        return await self._cargo.types.get_by_category(category_id)

    async def create_type(
        self, category_id: int, name: str, code: str, operator_id: int
    ) -> CommodityType:
        category = await self._cargo.categories.get_by_id(category_id)
        if not category:
            raise NotFoundError("CommodityCategory", category_id)

        cargo_type = CommodityType(
            category_id=category_id,
            name=name,
            code=code,
            submitter_id=operator_id,
            audit_status=0,
        )
        saved = await self._cargo.types.create(cargo_type)
        await self._audit_svc.submit_for_audit(
            target_type="COMMODITY_TYPE", target_id=saved.id,
            target_name=name, action="CREATE",
            submitter_id=operator_id,
            after_data={"name": saved.name, "category_id": category_id},
        )
        await self._cargo.save()
        return saved

    # ─────────────────────────────────────────────────
    # 商品标准
    # ─────────────────────────────────────────────────

    async def list_standards_by_type(self, type_id: int):
        return await self._cargo.standards.get_by_type(type_id)

    async def list_standards_paginated(
        self,
        type_id: Optional[int] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        offset = (page - 1) * page_size
        items, total = await self._cargo.standards.list_paginated(
            type_id=type_id, keyword=keyword, offset=offset, limit=page_size
        )
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def list_all_standards(self, type_id: Optional[int] = None):
        return await self._cargo.standards.get_all(type_id=type_id)

    async def create_standard(
        self, type_id: int, operator_id: int, **kwargs
    ) -> CommodityStandard:
        cargo_type = await self._cargo.types.get_by_id(type_id)
        if not cargo_type:
            raise NotFoundError("CommodityType", type_id)

        standard = CommodityStandard(
            type_id=type_id,
            submitter_id=operator_id,
            audit_status=0,
            **kwargs,
        )
        saved = await self._cargo.standards.create(standard)
        await self._audit_svc.submit_for_audit(
            target_type="COMMODITY_STANDARD", target_id=saved.id,
            target_name=saved.name, action="CREATE",
            submitter_id=operator_id,
            after_data={"name": saved.name, "type_id": type_id},
        )
        await self._cargo.save()
        return saved

    async def create_commodity_alias(
        self, standard_id: int, operator_id: int, **kwargs
    ) -> CommodityAlias:
        standard = await self._cargo.standards.get_by_id(standard_id)
        if not standard:
            raise NotFoundError("CommodityStandard", standard_id)
        alias = CommodityAlias(commodity_id=standard_id, **kwargs)
        saved = await self._cargo.aliases.create_alias(alias)
        await self._cargo.save()
        return saved

    # ─────────────────────────────────────────────────
    # 货源原始消息
    # ─────────────────────────────────────────────────

    async def submit_cargo_text(
        self, raw_text: str, source_type: Optional[str], operator_id: int,
        group_name: Optional[str] = None, sender_name: Optional[str] = None,
    ) -> CargoRawMessage:
        """提交原始货运文本，创建待解析记录"""
        raw_msg = CargoRawMessage(
            raw_text=raw_text,
            source_type=source_type or "WECHAT_GROUP",
            group_name=group_name,
            sender_name=sender_name,
            collector_id=operator_id,
            status="PENDING",
        )
        saved = await self._cargo.create(raw_msg)
        await self._cargo.save()
        logger.info(f"[CargoService] raw_message submitted id={saved.id}")
        return saved

    async def get_raw_message(self, msg_id: int) -> CargoRawMessage:
        msg = await self._cargo.get_raw_message(msg_id)
        if not msg:
            raise NotFoundError("CargoRawMessage", msg_id)
        return msg

    async def list_raw_messages(
        self,
        status: Optional[str] = None,
        operator_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        offset = (page - 1) * page_size
        items, total = await self._cargo.list_raw_messages(
            status=status, operator_id=operator_id, offset=offset, limit=page_size
        )
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    # ─────────────────────────────────────────────────
    # AI解析结果
    # ─────────────────────────────────────────────────

    async def get_parse_result(self, msg_id: int) -> CargoAiParseResult:
        result = await self._cargo.get_parse_result(msg_id)
        if not result:
            raise NotFoundError("CargoAiParseResult for message", msg_id)
        return result

    async def confirm_parse_result(
        self,
        result_id: int,
        operator_id: int,
        overrides: Optional[dict] = None,
    ) -> CargoOpportunity:
        """确认AI解析结果，创建最终货源机会记录"""
        # 直接查询parseResult（因cargo_repo.update_parse_result已支持）
        parse_result = await self._cargo.update_parse_result(result_id)
        if not parse_result:
            raise NotFoundError("CargoAiParseResult", result_id)

        if parse_result.status != "PENDING_CONFIRM":
            raise ValidationError(
                f"Cannot confirm: status is '{parse_result.status}'"
            )

        # 合并人工修正
        ov = overrides or {}
        origin_node_id = ov.get("origin_node_id") or parse_result.origin_node_id
        dest_node_id = ov.get("dest_node_id") or parse_result.dest_node_id
        commodity_id = ov.get("commodity_id") or parse_result.commodity_id

        opportunity = CargoOpportunity(
            opportunity_no=f"CO-{uuid.uuid4().hex[:12].upper()}",
            raw_message_id=parse_result.raw_message_id,
            origin_node_id=origin_node_id,
            dest_node_id=dest_node_id,
            commodity_id=commodity_id,
            tonnage=parse_result.tonnage,
            loading_date=parse_result.loading_date,
            freight_price=parse_result.freight_price,
            contact_person=parse_result.contact_person,
            contact_phone=parse_result.contact_phone,
            collector_id=operator_id,
            submitter_id=operator_id,
            audit_status=0,
            status="CONFIRMED",
            input_type="AI_PARSE",
        )

        saved_opp = await self._cargo.create_opportunity(opportunity)
        await self._cargo.update_parse_result(result_id, status="CONFIRMED")
        await self._audit_svc.submit_for_audit(
            target_type="CARGO_OPPORTUNITY", target_id=saved_opp.id,
            target_name=f"CargoOpportunity#{saved_opp.id}", action="CREATE",
            submitter_id=operator_id,
            after_data={"from_parse_result_id": result_id},
        )
        await self._cargo.save()
        logger.info(f"[CargoService] opportunity confirmed id={saved_opp.id}")
        return saved_opp

    # ─────────────────────────────────────────────────
    # 货源机会
    # ─────────────────────────────────────────────────

    async def create_manual_opportunity(
        self,
        origin_node_id: Optional[int],
        dest_node_id: Optional[int],
        commodity_id: Optional[int],
        tonnage: Optional[float],
        loading_date: Optional[str],
        freight_price: Optional[float],
        contact_person: Optional[str],
        contact_phone: Optional[str],
        remark: Optional[str],
        operator_id: int,
        price_type: Optional[int] = None,
        price_unit: Optional[str] = None,
        source_type: str = "WECHAT_GROUP",
    ) -> CargoOpportunity:
        """手动录入货源机会（不经过AI解析）"""
        if origin_node_id:
            node = await self._address.get_node(origin_node_id)
            if not node:
                raise NotFoundError("TransportNode (origin)", origin_node_id)

        if dest_node_id:
            node = await self._address.get_node(dest_node_id)
            if not node:
                raise NotFoundError("TransportNode (destination)", dest_node_id)

        opportunity = CargoOpportunity(
            opportunity_no=f"CO-{uuid.uuid4().hex[:12].upper()}",
            origin_node_id=origin_node_id,
            dest_node_id=dest_node_id,
            commodity_id=commodity_id,
            tonnage=tonnage,
            loading_date=loading_date,
            freight_price=freight_price,
            price_type=price_type,
            price_unit=price_unit,
            contact_person=contact_person,
            contact_phone=contact_phone,
            source_type=source_type,
            remark=remark,
            collector_id=operator_id,
            submitter_id=operator_id,
            audit_status=0,
            status="PENDING",
            input_type="MANUAL",
        )
        saved = await self._cargo.create_opportunity(opportunity)
        await self._audit_svc.submit_for_audit(
            target_type="CARGO_OPPORTUNITY", target_id=saved.id,
            target_name=f"CargoOpportunity#{saved.id}", action="CREATE",
            submitter_id=operator_id,
            after_data={"origin_node_id": origin_node_id, "dest_node_id": dest_node_id},
        )
        await self._cargo.save()
        return saved

    async def list_opportunities(
        self,
        status: Optional[str] = None,
        origin_node_id: Optional[int] = None,
        dest_node_id: Optional[int] = None,
        commodity_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        offset = (page - 1) * page_size
        items, total = await self._cargo.list_opportunities(
            status=status,
            origin_node_id=origin_node_id,
            dest_node_id=dest_node_id,
            commodity_id=commodity_id,
            offset=offset,
            limit=page_size,
        )
        return {"items": items, "total": total, "page": page, "page_size": page_size}
