"""系统基础数据初始化脚本。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.system import (
    SysMenu,
    SysPermission,
    SysRole,
    SysRoleMenu,
    SysRolePermission,
    SysUser,
    SysUserRole,
    SystemConfig,
)


ROLE_SUPER_ADMIN = {
    "role_code": "SUPER_ADMIN",
    "role_name": "超级管理员",
    "description": "系统超级管理员角色",
    "status_code": "ACTIVE",
    "sort_order": 1,
}

PERMISSIONS = [
    {
        "permission_code": "SYSTEM:ALL",
        "permission_name": "系统管理全量权限",
        "permission_type_code": "API",
        "resource_path": "/api/v1/system/*",
        "action_code": "ALL",
        "description": "系统管理全量权限",
    },
    {
        "permission_code": "DICTIONARY:ALL",
        "permission_name": "字典管理全量权限",
        "permission_type_code": "API",
        "resource_path": "/api/v1/dictionary/*",
        "action_code": "ALL",
        "description": "字典管理全量权限",
    },
    {
        "permission_code": "MASTER_DATA:ALL",
        "permission_name": "主数据管理全量权限",
        "permission_type_code": "API",
        "resource_path": "/api/v1/address/*",
        "action_code": "ALL",
        "description": "地址/货品/船舶/航线/货源等主数据权限",
    },
]

MENUS = [
    {
        "menu_code": "DASHBOARD",
        "menu_name": "工作台",
        "menu_type_code": "MENU",
        "route_path": "/dashboard",
        "component_path": "views/dashboard/index",
        "icon": "dashboard",
        "sort_order": 10,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "SYSTEM_ROOT",
        "menu_name": "系统管理",
        "menu_type_code": "MENU",
        "route_path": "/system",
        "component_path": "views/system/index",
        "icon": "setting",
        "sort_order": 90,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "SYSTEM_USER",
        "menu_name": "用户管理",
        "menu_type_code": "MENU",
        "parent_code": "SYSTEM_ROOT",
        "route_path": "/system/users",
        "component_path": "views/system/users",
        "icon": "user",
        "sort_order": 91,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "SYSTEM_ROLE",
        "menu_name": "角色管理",
        "menu_type_code": "MENU",
        "parent_code": "SYSTEM_ROOT",
        "route_path": "/system/roles",
        "component_path": "views/system/roles",
        "icon": "team",
        "sort_order": 92,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
]

ADMIN_USER = {
    "username": "admin",
    "password": "Admin@123456",
    "real_name": "系统管理员",
    "mobile_phone": "13800000000",
    "email": "admin@example.com",
    "status_code": "ACTIVE",
}

SYSTEM_CONFIGS = [
    {
        "config_key": "SYSTEM_NAME",
        "config_name": "系统名称",
        "config_value": "Inland Shipping Platform",
        "value_type_code": "STRING",
        "config_group_code": "SYSTEM",
        "description": "系统展示名称",
    },
    {
        "config_key": "DEFAULT_TIMEZONE",
        "config_name": "默认时区",
        "config_value": "Asia/Shanghai",
        "value_type_code": "STRING",
        "config_group_code": "SYSTEM",
        "description": "系统默认时区",
    },
]


async def seed_system_base() -> None:
    async with AsyncSessionLocal() as session:
        now = datetime.now(timezone.utc)

        role = await session.scalar(
            select(SysRole).where(SysRole.role_code == ROLE_SUPER_ADMIN["role_code"])
        )
        if role is None:
            role = SysRole(**ROLE_SUPER_ADMIN)
            session.add(role)
            await session.flush()
        else:
            role.role_name = ROLE_SUPER_ADMIN["role_name"]
            role.description = ROLE_SUPER_ADMIN["description"]
            role.status_code = ROLE_SUPER_ADMIN["status_code"]
            role.sort_order = ROLE_SUPER_ADMIN["sort_order"]

        permission_ids: list[int] = []
        for item in PERMISSIONS:
            permission = await session.scalar(
                select(SysPermission).where(
                    SysPermission.permission_code == item["permission_code"]
                )
            )
            if permission is None:
                permission = SysPermission(**item)
                session.add(permission)
                await session.flush()
            else:
                permission.permission_name = item["permission_name"]
                permission.permission_type_code = item["permission_type_code"]
                permission.resource_path = item["resource_path"]
                permission.action_code = item["action_code"]
                permission.description = item["description"]
            permission_ids.append(int(permission.id))

        menu_id_by_code: dict[str, int] = {}
        for item in MENUS:
            parent_code = item.get("parent_code")
            parent_id = menu_id_by_code.get(parent_code) if parent_code else None
            menu = await session.scalar(
                select(SysMenu).where(SysMenu.menu_code == item["menu_code"])
            )
            payload = {
                "parent_id": parent_id,
                "menu_code": item["menu_code"],
                "menu_name": item["menu_name"],
                "menu_type_code": item["menu_type_code"],
                "route_path": item["route_path"],
                "component_path": item["component_path"],
                "icon": item["icon"],
                "sort_order": item["sort_order"],
                "visible_flag": item["visible_flag"],
                "status_code": item["status_code"],
            }
            if menu is None:
                menu = SysMenu(**payload)
                session.add(menu)
                await session.flush()
            else:
                for key, value in payload.items():
                    setattr(menu, key, value)
            menu_id_by_code[item["menu_code"]] = int(menu.id)

        admin_user = await session.scalar(
            select(SysUser).where(SysUser.username == ADMIN_USER["username"])
        )
        if admin_user is None:
            admin_user = SysUser(
                username=ADMIN_USER["username"],
                password_hash=get_password_hash(ADMIN_USER["password"]),
                real_name=ADMIN_USER["real_name"],
                mobile_phone=ADMIN_USER["mobile_phone"],
                email=ADMIN_USER["email"],
                status_code=ADMIN_USER["status_code"],
                last_login_at=None,
                last_login_ip=None,
            )
            session.add(admin_user)
            await session.flush()
        else:
            admin_user.real_name = ADMIN_USER["real_name"]
            admin_user.mobile_phone = ADMIN_USER["mobile_phone"]
            admin_user.email = ADMIN_USER["email"]
            admin_user.status_code = ADMIN_USER["status_code"]
            admin_user.deleted_at = None

        for permission_id in permission_ids:
            existed = await session.scalar(
                select(SysRolePermission).where(
                    SysRolePermission.role_id == role.id,
                    SysRolePermission.permission_id == permission_id,
                )
            )
            if existed is None:
                session.add(
                    SysRolePermission(
                        role_id=role.id,
                        permission_id=permission_id,
                        created_at=now,
                    )
                )

        for menu_id in menu_id_by_code.values():
            existed = await session.scalar(
                select(SysRoleMenu).where(
                    SysRoleMenu.role_id == role.id,
                    SysRoleMenu.menu_id == menu_id,
                )
            )
            if existed is None:
                session.add(
                    SysRoleMenu(
                        role_id=role.id,
                        menu_id=menu_id,
                        created_at=now,
                    )
                )

        user_role = await session.scalar(
            select(SysUserRole).where(
                SysUserRole.user_id == admin_user.id,
                SysUserRole.role_id == role.id,
            )
        )
        if user_role is None:
            session.add(
                SysUserRole(
                    user_id=admin_user.id,
                    role_id=role.id,
                    created_at=now,
                )
            )

        for config_item in SYSTEM_CONFIGS:
            config = await session.scalar(
                select(SystemConfig).where(
                    SystemConfig.config_key == config_item["config_key"]
                )
            )
            if config is None:
                config = SystemConfig(
                    config_key=config_item["config_key"],
                    config_name=config_item["config_name"],
                    config_value=config_item["config_value"],
                    value_type_code=config_item["value_type_code"],
                    config_group_code=config_item["config_group_code"],
                    description=config_item["description"],
                    updated_by=None,
                    updated_at=now,
                    created_at=now,
                )
                session.add(config)
            else:
                config.config_name = config_item["config_name"]
                config.config_value = config_item["config_value"]
                config.value_type_code = config_item["value_type_code"]
                config.config_group_code = config_item["config_group_code"]
                config.description = config_item["description"]
                config.updated_at = now

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_system_base())
