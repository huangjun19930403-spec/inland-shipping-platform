"""system 模块 repository。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system import (
    SysDataScope,
    SysLoginLog,
    SysMenu,
    SysPermission,
    SysRole,
    SysRoleDataScope,
    SysRoleMenu,
    SysRolePermission,
    SysUser,
    SysUserRole,
    SysUserStatusLog,
    SystemConfig,
)


class SysUserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_user_by_id(self, user_id: int) -> SysUser | None:
        return await self.db.scalar(
            select(SysUser).where(SysUser.id == user_id, SysUser.deleted_at.is_(None))
        )

    async def get_user_by_username(self, username: str) -> SysUser | None:
        return await self.db.scalar(
            select(SysUser).where(SysUser.username == username, SysUser.deleted_at.is_(None))
        )

    async def get_user_by_mobile(self, mobile: str) -> SysUser | None:
        return await self.db.scalar(
            select(SysUser).where(SysUser.mobile_phone == mobile, SysUser.deleted_at.is_(None))
        )

    async def list_users(
        self,
        keyword: str | None,
        status: str | None,
        role_id: int | None,
        page: int,
        page_size: int,
    ) -> tuple[list[SysUser], int]:
        stmt = select(SysUser).where(SysUser.deleted_at.is_(None))
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    SysUser.username.ilike(like_value),
                    SysUser.real_name.ilike(like_value),
                    SysUser.mobile_phone.ilike(like_value),
                    SysUser.email.ilike(like_value),
                )
            )
        if status:
            stmt = stmt.where(SysUser.status_code == status)
        if role_id is not None:
            stmt = stmt.join(SysUserRole, SysUserRole.user_id == SysUser.id).where(SysUserRole.role_id == role_id)
        stmt = stmt.distinct()
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        items = (
            await self.db.execute(
                stmt.order_by(SysUser.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).scalars().all()
        return list(items), total

    async def create_user(self, data: dict[str, Any]) -> SysUser:
        entity = SysUser(**data)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def update_user(self, user_id: int, data: dict[str, Any]) -> SysUser | None:
        entity = await self.get_user_by_id(user_id)
        if entity is None:
            return None
        for key, value in data.items():
            setattr(entity, key, value)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def update_user_password(self, user_id: int, password_hash: str) -> bool:
        entity = await self.get_user_by_id(user_id)
        if entity is None:
            return False
        entity.password_hash = password_hash
        await self.db.flush()
        return True

    async def update_user_status(self, user_id: int, status: str) -> bool:
        entity = await self.get_user_by_id(user_id)
        if entity is None:
            return False
        entity.status_code = status
        await self.db.flush()
        return True

    async def replace_user_roles(self, user_id: int, role_ids: list[int]) -> None:
        await self.db.execute(delete(SysUserRole).where(SysUserRole.user_id == user_id))
        now = datetime.utcnow()
        for role_id in role_ids:
            self.db.add(SysUserRole(user_id=user_id, role_id=role_id, created_at=now))
        await self.db.flush()

    async def list_user_roles(self, user_id: int) -> list[SysRole]:
        return list(
            (
                await self.db.execute(
                    select(SysRole)
                    .join(SysUserRole, SysUserRole.role_id == SysRole.id)
                    .where(SysUserRole.user_id == user_id)
                    .order_by(SysRole.sort_order.asc(), SysRole.id.asc())
                )
            )
            .scalars()
            .all()
        )

    async def list_user_permissions(self, user_id: int) -> list[SysPermission]:
        stmt = (
            select(SysPermission)
            .join(SysRolePermission, SysRolePermission.permission_id == SysPermission.id)
            .join(SysUserRole, SysUserRole.role_id == SysRolePermission.role_id)
            .where(SysUserRole.user_id == user_id)
            .distinct()
            .order_by(SysPermission.id.asc())
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def list_user_menus(self, user_id: int) -> list[SysMenu]:
        stmt = (
            select(SysMenu)
            .join(SysRoleMenu, SysRoleMenu.menu_id == SysMenu.id)
            .join(SysUserRole, SysUserRole.role_id == SysRoleMenu.role_id)
            .where(SysUserRole.user_id == user_id)
            .distinct()
            .order_by(SysMenu.sort_order.asc(), SysMenu.id.asc())
        )
        return list((await self.db.execute(stmt)).scalars().all())


class SysRoleRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_role_by_id(self, role_id: int) -> SysRole | None:
        return await self.db.scalar(select(SysRole).where(SysRole.id == role_id))

    async def get_role_by_code(self, role_code: str) -> SysRole | None:
        return await self.db.scalar(select(SysRole).where(SysRole.role_code == role_code))

    async def list_roles(
        self, keyword: str | None, status: str | None, page: int, page_size: int
    ) -> tuple[list[SysRole], int]:
        stmt = select(SysRole)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(SysRole.role_code.ilike(like_value), SysRole.role_name.ilike(like_value))
            )
        if status:
            stmt = stmt.where(SysRole.status_code == status)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        items = (
            await self.db.execute(
                stmt.order_by(SysRole.sort_order.asc(), SysRole.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(items), total

    async def create_role(self, data: dict[str, Any]) -> SysRole:
        entity = SysRole(**data)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def update_role(self, role_id: int, data: dict[str, Any]) -> SysRole | None:
        entity = await self.get_role_by_id(role_id)
        if entity is None:
            return None
        for key, value in data.items():
            setattr(entity, key, value)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def replace_role_permissions(self, role_id: int, permission_ids: list[int]) -> None:
        await self.db.execute(delete(SysRolePermission).where(SysRolePermission.role_id == role_id))
        now = datetime.utcnow()
        for permission_id in permission_ids:
            self.db.add(
                SysRolePermission(role_id=role_id, permission_id=permission_id, created_at=now)
            )
        await self.db.flush()

    async def replace_role_menus(self, role_id: int, menu_ids: list[int]) -> None:
        await self.db.execute(delete(SysRoleMenu).where(SysRoleMenu.role_id == role_id))
        now = datetime.utcnow()
        for menu_id in menu_ids:
            self.db.add(SysRoleMenu(role_id=role_id, menu_id=menu_id, created_at=now))
        await self.db.flush()

    async def replace_role_data_scopes(self, role_id: int, data_scope_ids: list[int]) -> None:
        await self.db.execute(delete(SysRoleDataScope).where(SysRoleDataScope.role_id == role_id))
        now = datetime.utcnow()
        for scope_id in data_scope_ids:
            self.db.add(
                SysRoleDataScope(role_id=role_id, data_scope_id=scope_id, created_at=now)
            )
        await self.db.flush()

    async def list_role_permissions(self, role_id: int) -> list[int]:
        rows = (
            await self.db.execute(
                select(SysRolePermission.permission_id).where(SysRolePermission.role_id == role_id)
            )
        ).all()
        return [int(row[0]) for row in rows]

    async def list_role_menus(self, role_id: int) -> list[int]:
        rows = (
            await self.db.execute(select(SysRoleMenu.menu_id).where(SysRoleMenu.role_id == role_id))
        ).all()
        return [int(row[0]) for row in rows]

    async def list_role_data_scopes(self, role_id: int) -> list[int]:
        rows = (
            await self.db.execute(
                select(SysRoleDataScope.data_scope_id).where(SysRoleDataScope.role_id == role_id)
            )
        ).all()
        return [int(row[0]) for row in rows]


class SysPermissionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_permission_by_id(self, permission_id: int) -> SysPermission | None:
        return await self.db.scalar(select(SysPermission).where(SysPermission.id == permission_id))

    async def list_permissions(
        self,
        keyword: str | None,
        module_code: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[SysPermission], int]:
        stmt = select(SysPermission)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    SysPermission.permission_code.ilike(like_value),
                    SysPermission.permission_name.ilike(like_value),
                )
            )
        if module_code:
            stmt = stmt.where(SysPermission.permission_code.like(f"{module_code}%"))
        _ = status
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        items = (
            await self.db.execute(
                stmt.order_by(SysPermission.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(items), total

    async def list_all_permissions(self) -> list[SysPermission]:
        return list((await self.db.execute(select(SysPermission).order_by(SysPermission.id.asc()))).scalars().all())


class SysMenuRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_menu_by_id(self, menu_id: int) -> SysMenu | None:
        return await self.db.scalar(select(SysMenu).where(SysMenu.id == menu_id))

    async def get_menu_by_code(self, menu_code: str) -> SysMenu | None:
        return await self.db.scalar(select(SysMenu).where(SysMenu.menu_code == menu_code))

    async def list_menus(
        self,
        keyword: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[SysMenu], int]:
        stmt = select(SysMenu)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(SysMenu.menu_code.ilike(like_value), SysMenu.menu_name.ilike(like_value))
            )
        if status:
            stmt = stmt.where(SysMenu.status_code == status)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        items = (
            await self.db.execute(
                stmt.order_by(SysMenu.sort_order.asc(), SysMenu.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(items), total

    async def list_all_menus(self) -> list[SysMenu]:
        return list(
            (
                await self.db.execute(
                    select(SysMenu).order_by(SysMenu.sort_order.asc(), SysMenu.id.asc())
                )
            )
            .scalars()
            .all()
        )

    async def create_menu(self, data: dict[str, Any]) -> SysMenu:
        entity = SysMenu(**data)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def update_menu(self, menu_id: int, data: dict[str, Any]) -> SysMenu | None:
        entity = await self.get_menu_by_id(menu_id)
        if entity is None:
            return None
        for key, value in data.items():
            setattr(entity, key, value)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def build_menu_tree(self) -> list[dict[str, Any]]:
        menus = await self.list_all_menus()
        node_map: dict[int, dict[str, Any]] = {}
        roots: list[dict[str, Any]] = []

        for item in menus:
            node_map[item.id] = {
                "id": item.id,
                "parent_id": item.parent_id,
                "menu_code": item.menu_code,
                "menu_name": item.menu_name,
                "menu_type_code": item.menu_type_code,
                "route_path": item.route_path,
                "component_path": item.component_path,
                "icon": item.icon,
                "sort_order": item.sort_order,
                "visible_flag": item.visible_flag,
                "status_code": item.status_code,
                "children": [],
            }

        for item in menus:
            node = node_map[item.id]
            parent_id = item.parent_id
            if parent_id and parent_id in node_map:
                node_map[parent_id]["children"].append(node)
            else:
                roots.append(node)

        def _sort_tree(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
            nodes.sort(key=lambda x: (x["sort_order"], x["id"]))
            for row in nodes:
                row["children"] = _sort_tree(row["children"])
            return nodes

        return _sort_tree(roots)


class SysDataScopeRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_data_scope_by_id(self, scope_id: int) -> SysDataScope | None:
        return await self.db.scalar(select(SysDataScope).where(SysDataScope.id == scope_id))

    async def list_data_scopes(
        self,
        keyword: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[SysDataScope], int]:
        stmt = select(SysDataScope)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    SysDataScope.scope_code.ilike(like_value),
                    SysDataScope.scope_name.ilike(like_value),
                )
            )
        _ = status
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        items = (
            await self.db.execute(
                stmt.order_by(SysDataScope.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(items), total

    async def list_all_data_scopes(self) -> list[SysDataScope]:
        return list(
            (
                await self.db.execute(select(SysDataScope).order_by(SysDataScope.id.asc()))
            )
            .scalars()
            .all()
        )


class SystemConfigRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_config_by_key(self, config_key: str) -> SystemConfig | None:
        return await self.db.scalar(select(SystemConfig).where(SystemConfig.config_key == config_key))

    async def get_config_for_runtime(
        self,
        config_key: str,
        profile_code: str | None = None,
    ) -> SystemConfig | None:
        stmt = select(SystemConfig).where(
            SystemConfig.config_key == config_key,
            SystemConfig.config_status_code == "ACTIVE",
        )
        if profile_code:
            stmt = stmt.where(SystemConfig.config_profile_code == profile_code)
        stmt = stmt.order_by(
            SystemConfig.config_profile_code.asc(),
            SystemConfig.sort_order.asc(),
            SystemConfig.id.asc(),
        ).limit(1)
        return (await self.db.execute(stmt)).scalars().first()

    async def list_configs_by_group_for_runtime(
        self,
        group_code: str,
        profile_code: str | None = None,
        include_inactive: bool = False,
    ) -> list[SystemConfig]:
        stmt = select(SystemConfig).where(SystemConfig.config_group_code == group_code)
        if not include_inactive:
            stmt = stmt.where(SystemConfig.config_status_code == "ACTIVE")
        if profile_code:
            stmt = stmt.where(SystemConfig.config_profile_code == profile_code)
        stmt = stmt.order_by(
            SystemConfig.config_profile_code.asc(),
            SystemConfig.sort_order.asc(),
            SystemConfig.config_key.asc(),
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def list_configs(
        self,
        keyword: str | None,
        group_code: str | None,
        profile_code: str | None,
        status_code: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[SystemConfig], int]:
        stmt = select(SystemConfig)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    SystemConfig.config_key.ilike(like_value),
                    SystemConfig.config_name.ilike(like_value),
                )
            )
        if group_code:
            stmt = stmt.where(SystemConfig.config_group_code == group_code)
        if profile_code:
            stmt = stmt.where(SystemConfig.config_profile_code == profile_code)
        if status_code:
            stmt = stmt.where(SystemConfig.config_status_code == status_code)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        items = (
            await self.db.execute(
                stmt.order_by(
                    SystemConfig.config_group_code.asc(),
                    SystemConfig.config_profile_code.asc(),
                    SystemConfig.sort_order.asc(),
                    SystemConfig.config_key.asc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(items), total

    async def create_config(self, data: dict[str, Any]) -> SystemConfig:
        entity = SystemConfig(**data)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def update_config(self, config_key: str, data: dict[str, Any]) -> SystemConfig | None:
        entity = await self.get_config_by_key(config_key)
        if entity is None:
            return None
        for key, value in data.items():
            setattr(entity, key, value)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity


class SysLoginLogRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_login_log(self, data: dict[str, Any]) -> SysLoginLog:
        entity = SysLoginLog(**data)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def list_login_logs(
        self,
        keyword: str | None,
        login_result: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[SysLoginLog], int]:
        stmt = select(SysLoginLog)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    SysLoginLog.username.ilike(like_value),
                    SysLoginLog.login_ip.ilike(like_value),
                    SysLoginLog.user_agent.ilike(like_value),
                )
            )
        if login_result:
            stmt = stmt.where(SysLoginLog.login_result_code == login_result)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        items = (
            await self.db.execute(
                stmt.order_by(SysLoginLog.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).scalars().all()
        return list(items), total

    async def mark_latest_logout(self, user_id: int, logout_at: datetime) -> bool:
        row = await self.db.scalar(
            select(SysLoginLog)
            .where(
                SysLoginLog.user_id == user_id,
                SysLoginLog.login_result_code == "SUCCESS",
                SysLoginLog.logout_at.is_(None),
            )
            .order_by(SysLoginLog.id.desc())
        )
        if row is None:
            return False
        row.logout_at = logout_at
        await self.db.flush()
        return True


class SysUserStatusLogRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_status_log(self, data: dict[str, Any]) -> SysUserStatusLog:
        entity = SysUserStatusLog(**data)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def list_status_logs(
        self,
        user_id: int,
        page: int,
        page_size: int,
    ) -> tuple[list[SysUserStatusLog], int]:
        stmt = select(SysUserStatusLog).where(SysUserStatusLog.user_id == user_id)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        items = (
            await self.db.execute(
                stmt.order_by(SysUserStatusLog.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(items), total
