"""
货物业务服务层
职责：货物/商品相关业务逻辑编排
规则：只调用Repository，不直接操作SQLAlchemy Session
"""
import json
import logging
from typing import Optional

from app.core.exceptions import NotFoundError, ValidationError
from app.models.cargo import (
    CommodityCategory,
    CommodityType,
    CommodityStandard,
    CargoRawMessage,
    CargoAiParseResult,
    CargoOpportunity,
)
from app.models.audit import AuditRecord
from app.repositories.cargo_repository import CargoRepository
from app.repositories.address_repository import AddressRepository
from app.repositories.audit_repository import AuditRepository

logger = logging.getLogger(__name__)


class CargoService:
    """
    货物业务服务

    依赖注入：CargoRepository + AddressRepository + AuditRepository
    不持有SQLAlchemy Session，通过Repository间接访问数据库
    """

    def __init__(
        self,
        cargo_repo: CargoRepository,
        address_repo: AddressRepository,
        audit_repo: AuditRepository,
    ) -> None:
        self._cargo = cargo_repo
        self._address = address_repo
        self._audit = audit_repo

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
        )
        saved = await self._cargo.categories.create(category)
        await self._record_audit(
            operator_id=operator_id,
            action="CREATE",
            target_type="COMMODITY_CATEGORY",
            target_id=saved.id,
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
        )
        saved = await self._cargo.types.create(cargo_type)
        await self._record_audit(
            operator_id=operator_id,
            action="CREATE",
            target_type="COMMODITY_TYPE",
            target_id=saved.id,
            after_data={"name": saved.name, "category_id": category_id},
        )
        await self._cargo.save()
        return saved

    # ─────────────────────────────────────────────────
    # 商品标准
    # ─────────────────────────────────────────────────

    async def list_standards_by_type(self, type_id: int):
        return await self._cargo.standards.get_by_type(type_id)

    async def create_standard(
        self, type_id: int, name: str, description: Optional[str], operator_id: int
    ) -> CommodityStandard:
        cargo_type = await self._cargo.types.get_by_id(type_id)
        if not cargo_type:
            raise NotFoundError("CommodityType", type_id)

        standard = CommodityStandard(
            commodity_type_id=type_id,
            name=name,
            description=description,
        )
        saved = await self._cargo.standards.create(standard)
        await self._record_audit(
            operator_id=operator_id,
            action="CREATE",
            target_type="COMMODITY_STANDARD",
            target_id=saved.id,
            after_data={"name": saved.name, "type_id": type_id},
        )
        await self._cargo.save()
        return saved

    # ─────────────────────────────────────────────────
    # 货源原始消息
    # ─────────────────────────────────────────────────

    async def submit_cargo_text(
        self, raw_text: str, source: Optional[str], operator_id: int
    ) -> CargoRawMessage:
        """提交原始货运文本，创建待解析记录"""
        raw_msg = CargoRawMessage(
            raw_text=raw_text,
            source=source,
            operator_id=operator_id,
            parse_status="PENDING",
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
        from sqlalchemy import select
        from app.models.cargo import CargoAiParseResult as ParseModel

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
        commodity_id = ov.get("commodity_standard_id") or parse_result.commodity_standard_id

        opportunity = CargoOpportunity(
            raw_message_id=parse_result.raw_message_id,
            origin_node_id=origin_node_id,
            dest_node_id=dest_node_id,
            commodity_standard_id=commodity_id,
            tonnage=parse_result.tonnage,
            loading_date=parse_result.loading_date,
            freight_price=parse_result.freight_price,
            contact=parse_result.contact,
            remarks=parse_result.remarks,
            operator_id=operator_id,
            status="ACTIVE",
        )

        saved_opp = await self._cargo.create_opportunity(opportunity)
        await self._cargo.update_parse_result(result_id, status="CONFIRMED")

        await self._record_audit(
            operator_id=operator_id,
            action="CONFIRM",
            target_type="CARGO_OPPORTUNITY",
            target_id=saved_opp.id,
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
        commodity_standard_id: Optional[int],
        tonnage: Optional[float],
        loading_date: Optional[str],
        freight_price: Optional[float],
        contact: Optional[str],
        remarks: Optional[str],
        operator_id: int,
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
            origin_node_id=origin_node_id,
            dest_node_id=dest_node_id,
            commodity_standard_id=commodity_standard_id,
            tonnage=tonnage,
            loading_date=loading_date,
            freight_price=freight_price,
            contact=contact,
            remarks=remarks,
            operator_id=operator_id,
            status="PENDING",
        )
        saved = await self._cargo.create_opportunity(opportunity)
        await self._record_audit(
            operator_id=operator_id,
            action="CREATE",
            target_type="CARGO_OPPORTUNITY",
            target_id=saved.id,
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
            operator_id=operator_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            audit_status="APPROVED",
            before_data=json.dumps(before_data, ensure_ascii=False) if before_data else None,
            after_data=json.dumps(after_data, ensure_ascii=False) if after_data else None,
        )
        await self._audit.create_record(record)
