"""
通用Repository基类
提供CRUD基础能力，所有业务Repository继承此类
"""
from typing import Any, Generic, Optional, Sequence, Type, TypeVar

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


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
        """按主键查询"""
        result = await self._db.execute(
            select(self.model_class).where(self.model_class.id == pk)
        )
        return result.scalar_one_or_none()

    async def get_all(
        self,
        offset: int = 0,
        limit: int = 20,
    ) -> Sequence[ModelT]:
        """分页查询全部记录"""
        result = await self._db.execute(
            select(self.model_class).offset(offset).limit(limit)
        )
        return result.scalars().all()

    async def count(self) -> int:
        """统计总数"""
        result = await self._db.execute(
            select(func.count()).select_from(self.model_class)
        )
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
        """删除记录"""
        await self._db.delete(instance)
        await self._db.flush()

    async def save(self) -> None:
        """提交当前事务"""
        await self._db.commit()

    async def rollback(self) -> None:
        """回滚当前事务"""
        await self._db.rollback()
