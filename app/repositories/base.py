"""
通用Repository基类
提供CRUD基础能力，所有业务Repository继承此类
软删支持：若模型含 deleted_at 列，delete() 标记时间戳而非物理删除，查询自动过滤已删除记录
"""
from datetime import datetime
from typing import Any, Generic, Optional, Sequence, Type, TypeVar

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


def _has_soft_delete(obj) -> bool:
    """判断模型类或实例是否支持软删（含 deleted_at 列）"""
    return hasattr(obj, "deleted_at")


class BaseRepository(Generic[ModelT]):
    """
    通用数据访问基类

    子类只需声明 model_class，即可获得标准CRUD能力。
    复杂查询在子类中扩展实现。
    """

    model_class: Type[ModelT]

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ─────────────────────────────────────────────────
    # 基础CRUD
    # ─────────────────────────────────────────────────

    async def get_by_id(self, pk: int) -> Optional[ModelT]:
        """按主键查询（软删模型自动过滤已删除）"""
        q = select(self.model_class).where(self.model_class.id == pk)
        if _has_soft_delete(self.model_class):
            q = q.where(self.model_class.deleted_at.is_(None))
        result = await self._db.execute(q)
        return result.scalar_one_or_none()

    async def get_all(
        self,
        offset: int = 0,
        limit: int = 20,
    ) -> Sequence[ModelT]:
        """分页查询全部记录（软删模型自动过滤已删除）"""
        q = select(self.model_class)
        if _has_soft_delete(self.model_class):
            q = q.where(self.model_class.deleted_at.is_(None))
        result = await self._db.execute(q.offset(offset).limit(limit))
        return result.scalars().all()

    async def count(self) -> int:
        """统计总数（软删模型自动过滤已删除）"""
        if _has_soft_delete(self.model_class):
            q = select(func.count()).select_from(self.model_class).where(
                self.model_class.deleted_at.is_(None)
            )
        else:
            q = select(func.count()).select_from(self.model_class)
        result = await self._db.execute(q)
        return result.scalar_one()

    async def create(self, instance: ModelT) -> ModelT:
        """插入新记录"""
        self._db.add(instance)
        await self._db.flush()
        await self._db.refresh(instance)
        return instance

    async def update(self, instance: ModelT, **kwargs: Any) -> ModelT:
        """更新记录字段"""
        for field, value in kwargs.items():
            setattr(instance, field, value)
        await self._db.flush()
        await self._db.refresh(instance)
        return instance

    async def delete(self, instance: ModelT) -> None:
        """删除记录（软删优先：若含 deleted_at 则标记时间戳，否则物理删除）"""
        if _has_soft_delete(instance):
            instance.deleted_at = datetime.now()
            if hasattr(instance, "is_deleted"):
                instance.is_deleted = 1
            await self._db.flush()
        else:
            await self._db.delete(instance)
            await self._db.flush()

    async def save(self) -> None:
        """提交当前事务"""
        await self._db.commit()

    async def rollback(self) -> None:
        """回滚当前事务"""
        await self._db.rollback()
