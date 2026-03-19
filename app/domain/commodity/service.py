"""
货品标准化业务服务层
职责：货品分类、货品类型、标准货品、货品别名
规则：只调用Repository，不直接操作SQLAlchemy Session
"""
import logging
from typing import Optional

from app.core.exceptions import NotFoundError
from app.models.cargo import (
    CommodityAlias,
    CommodityCategory,
    CommodityStandard,
    CommodityType,
)
from app.repositories.cargo_repository import CargoRepository
from app.domain.audit.service import AuditService

logger = logging.getLogger(__name__)


class CommodityService:
    """货品标准化服务"""

    def __init__(self, cargo_repo: CargoRepository, audit_svc: AuditService) -> None:
        self._cargo = cargo_repo
        self._audit_svc = audit_svc

    # ─────────────────────────────────────────────────
    # 商品分类
    # ─────────────────────────────────────────────────

    async def list_categories(self):
        return await self._cargo.categories.get_all_with_types()

    async def create_category(
        self,
        name: str,
        code: str,
        description: Optional[str],
        operator_id: int,
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
            target_type="COMMODITY_CATEGORY",
            target_id=saved.id,
            target_name=name,
            action="CREATE",
            submitter_id=operator_id,
            after_data={"name": saved.name, "code": saved.code},
        )
        await self._cargo.save()
        logger.info("[CommodityService] category created id=%s", saved.id)
        return saved

    # ─────────────────────────────────────────────────
    # 商品类型
    # ─────────────────────────────────────────────────

    async def list_types_by_category(self, category_id: int):
        return await self._cargo.types.get_by_category(category_id)

    async def create_type(
        self,
        category_id: int,
        name: str,
        code: str,
        operator_id: int,
    ) -> CommodityType:
        category = await self._cargo.categories.get_by_id(category_id)
        if not category:
            raise NotFoundError("CommodityCategory", category_id)

        commodity_type = CommodityType(
            category_id=category_id,
            name=name,
            code=code,
            submitter_id=operator_id,
            audit_status=0,
        )
        saved = await self._cargo.types.create(commodity_type)
        await self._audit_svc.submit_for_audit(
            target_type="COMMODITY_TYPE",
            target_id=saved.id,
            target_name=name,
            action="CREATE",
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
            type_id=type_id,
            keyword=keyword,
            offset=offset,
            limit=page_size,
        )
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def list_all_standards(self, type_id: Optional[int] = None):
        return await self._cargo.standards.get_all(type_id=type_id)

    async def create_standard(
        self,
        type_id: int,
        operator_id: int,
        **kwargs,
    ) -> CommodityStandard:
        commodity_type = await self._cargo.types.get_by_id(type_id)
        if not commodity_type:
            raise NotFoundError("CommodityType", type_id)

        standard = CommodityStandard(
            type_id=type_id,
            submitter_id=operator_id,
            audit_status=0,
            **kwargs,
        )
        saved = await self._cargo.standards.create(standard)
        await self._audit_svc.submit_for_audit(
            target_type="COMMODITY_STANDARD",
            target_id=saved.id,
            target_name=saved.name,
            action="CREATE",
            submitter_id=operator_id,
            after_data={"name": saved.name, "type_id": type_id},
        )
        await self._cargo.save()
        return saved

    async def create_commodity_alias(
        self,
        standard_id: int,
        operator_id: int,
        **kwargs,
    ) -> CommodityAlias:
        standard = await self._cargo.standards.get_by_id(standard_id)
        if not standard:
            raise NotFoundError("CommodityStandard", standard_id)

        alias = CommodityAlias(commodity_id=standard_id, **kwargs)
        saved = await self._cargo.aliases.create_alias(alias)
        await self._cargo.save()
        return saved
