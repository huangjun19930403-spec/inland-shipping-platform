"""
系统管理数据访问层
用户、角色相关数据操作
"""
from typing import Optional, Sequence

from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

from app.models.system import SysUser, SysRole, SysUserRole
from app.repositories.base import BaseRepository


class SystemRepository(BaseRepository):
    model_class = SysUser

    # ─────────────────────────────────────────────────
    # SysUser
    # ─────────────────────────────────────────────────

    async def get_user(self, user_id: int) -> Optional[SysUser]:
        result = await self._db.execute(
            select(SysUser)
            .where(SysUser.id == user_id)
            .options(selectinload(SysUser.user_roles).selectinload(SysUserRole.role))
        )
        return result.scalar_one_or_none()

    async def get_user_by_username(self, username: str) -> Optional[SysUser]:
        result = await self._db.execute(
            select(SysUser)
            .where(SysUser.username == username)
            .options(selectinload(SysUser.user_roles).selectinload(SysUserRole.role))
        )
        return result.scalar_one_or_none()

    async def list_users(
        self,
        is_active: Optional[bool] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[SysUser], int]:
        filters = []
        if is_active is not None:
            filters.append(SysUser.is_active == is_active)

        query = select(SysUser).options(
            selectinload(SysUser.user_roles).selectinload(SysUserRole.role)
        )
        if filters:
            query = query.where(and_(*filters))

        from sqlalchemy import func
        total_result = await self._db.execute(
            select(func.count(SysUser.id))
        )
        total = total_result.scalar_one()

        result = await self._db.execute(query.offset(offset).limit(limit))
        return result.scalars().unique().all(), total

    async def create_user(self, user: SysUser) -> SysUser:
        return await self.create(user)

    async def update_user(self, user_id: int, **kwargs) -> Optional[SysUser]:
        user = await self.get_user(user_id)
        if user:
            return await self.update(user, **kwargs)
        return None

    # ─────────────────────────────────────────────────
    # SysRole
    # ─────────────────────────────────────────────────

    async def list_roles(self) -> Sequence[SysRole]:
        result = await self._db.execute(select(SysRole))
        return result.scalars().all()

    async def get_role_by_code(self, code: str) -> Optional[SysRole]:
        result = await self._db.execute(
            select(SysRole).where(SysRole.role_code == code)
        )
        return result.scalar_one_or_none()

    # ─────────────────────────────────────────────────
    # SysUserRole
    # ─────────────────────────────────────────────────

    async def assign_role(self, user_id: int, role_id: int) -> SysUserRole:
        user_role = SysUserRole(user_id=user_id, role_id=role_id)
        return await self.create(user_role)

    async def get_user_roles(self, user_id: int) -> Sequence[SysUserRole]:
        result = await self._db.execute(
            select(SysUserRole)
            .where(SysUserRole.user_id == user_id)
            .options(selectinload(SysUserRole.role))
        )
        return result.scalars().all()
