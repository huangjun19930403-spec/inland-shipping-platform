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
        "component_path": "modules/system/pages/DashboardPage",
        "icon": "House",
        "sort_order": 10,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "SYSTEM_ROOT",
        "menu_name": "系统管理",
        "menu_type_code": "MENU",
        "route_path": "/system",
        "component_path": "modules/system/pages",
        "icon": "Setting",
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
        "component_path": "modules/system/pages/UserListPage",
        "icon": "User",
        "sort_order": 1,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "SYSTEM_ROLE",
        "menu_name": "角色管理",
        "menu_type_code": "MENU",
        "parent_code": "SYSTEM_ROOT",
        "route_path": "/system/roles",
        "component_path": "modules/system/pages/RoleListPage",
        "icon": "UserFilled",
        "sort_order": 2,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "SYSTEM_MENU",
        "menu_name": "菜单管理",
        "menu_type_code": "MENU",
        "parent_code": "SYSTEM_ROOT",
        "route_path": "/system/menus",
        "component_path": "modules/system/pages/MenuListPage",
        "icon": "Menu",
        "sort_order": 3,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "SYSTEM_CONFIG",
        "menu_name": "系统配置",
        "menu_type_code": "MENU",
        "parent_code": "SYSTEM_ROOT",
        "route_path": "/system/configs",
        "component_path": "modules/system/pages/SystemConfigPage",
        "icon": "Tools",
        "sort_order": 4,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "DICTIONARY_ROOT",
        "menu_name": "字典管理",
        "menu_type_code": "MENU",
        "route_path": "/dictionary",
        "component_path": "modules/dictionary/pages",
        "icon": "Collection",
        "sort_order": 20,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "DICTIONARY_DICTS",
        "menu_name": "字典",
        "menu_type_code": "MENU",
        "parent_code": "DICTIONARY_ROOT",
        "route_path": "/dictionary/dicts",
        "component_path": "modules/dictionary/pages/DictListPage",
        "icon": "Collection",
        "sort_order": 1,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "DICTIONARY_CODE_SEQUENCES",
        "menu_name": "编码序列",
        "menu_type_code": "MENU",
        "parent_code": "DICTIONARY_ROOT",
        "route_path": "/dictionary/code-sequences",
        "component_path": "modules/dictionary/pages/CodeSequenceListPage",
        "icon": "Tickets",
        "sort_order": 2,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "ADDRESS_ROOT",
        "menu_name": "地址管理",
        "menu_type_code": "MENU",
        "route_path": "/address",
        "component_path": "modules/address/pages",
        "icon": "Location",
        "sort_order": 30,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "ADDRESS_ADMIN_REGIONS",
        "menu_name": "行政区划",
        "menu_type_code": "MENU",
        "parent_code": "ADDRESS_ROOT",
        "route_path": "/address/admin-regions",
        "component_path": "modules/address/pages/AdminRegionPage",
        "icon": "Location",
        "sort_order": 1,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "ADDRESS_REGIONS",
        "menu_name": "业务区域",
        "menu_type_code": "MENU",
        "parent_code": "ADDRESS_ROOT",
        "route_path": "/address/regions",
        "component_path": "modules/address/pages/RegionListPage",
        "icon": "MapLocation",
        "sort_order": 2,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "ADDRESS_NODES",
        "menu_name": "运输节点",
        "menu_type_code": "MENU",
        "parent_code": "ADDRESS_ROOT",
        "route_path": "/address/nodes",
        "component_path": "modules/address/pages/NodeListPage",
        "icon": "Position",
        "sort_order": 3,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "COMMODITY_ROOT",
        "menu_name": "货品管理",
        "menu_type_code": "MENU",
        "route_path": "/commodity",
        "component_path": "modules/commodity/pages",
        "icon": "Box",
        "sort_order": 40,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "COMMODITY_CATEGORIES",
        "menu_name": "分类",
        "menu_type_code": "MENU",
        "parent_code": "COMMODITY_ROOT",
        "route_path": "/commodity/categories",
        "component_path": "modules/commodity/pages/CategoryListPage",
        "icon": "Box",
        "sort_order": 1,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "COMMODITY_TYPES",
        "menu_name": "类型",
        "menu_type_code": "MENU",
        "parent_code": "COMMODITY_ROOT",
        "route_path": "/commodity/types",
        "component_path": "modules/commodity/pages/TypeListPage",
        "icon": "List",
        "sort_order": 2,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "COMMODITY_STANDARDS",
        "menu_name": "标准货品",
        "menu_type_code": "MENU",
        "parent_code": "COMMODITY_ROOT",
        "route_path": "/commodity/standards",
        "component_path": "modules/commodity/pages/StandardListPage",
        "icon": "Files",
        "sort_order": 3,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "SHIP_ROOT",
        "menu_name": "船舶管理",
        "menu_type_code": "MENU",
        "route_path": "/ship",
        "component_path": "modules/ship/pages",
        "icon": "Ship",
        "sort_order": 50,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "SHIP_LIST",
        "menu_name": "船舶列表",
        "menu_type_code": "MENU",
        "parent_code": "SHIP_ROOT",
        "route_path": "/ship/list",
        "component_path": "modules/ship/pages/ShipListPage",
        "icon": "Ship",
        "sort_order": 1,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "SHIP_IMPORT_BATCHES",
        "menu_name": "导入批次",
        "menu_type_code": "MENU",
        "parent_code": "SHIP_ROOT",
        "route_path": "/ship/import/batches",
        "component_path": "modules/ship/pages/ShipImportBatchListPage",
        "icon": "Upload",
        "sort_order": 2,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "FREIGHT_ROOT",
        "menu_name": "正式货源",
        "menu_type_code": "MENU",
        "route_path": "/freight",
        "component_path": "modules/freight/pages",
        "icon": "Promotion",
        "sort_order": 60,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "FREIGHT_LIST",
        "menu_name": "货源列表",
        "menu_type_code": "MENU",
        "parent_code": "FREIGHT_ROOT",
        "route_path": "/freight/list",
        "component_path": "modules/freight/pages/FreightListPage",
        "icon": "Promotion",
        "sort_order": 1,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "FREIGHT_MANUAL_CREATE",
        "menu_name": "手工录入",
        "menu_type_code": "MENU",
        "parent_code": "FREIGHT_ROOT",
        "route_path": "/freight/manual-create",
        "component_path": "modules/freight/pages/FreightCreatePage",
        "icon": "EditPen",
        "sort_order": 2,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "ROUTE_ROOT",
        "menu_name": "航线管理",
        "menu_type_code": "MENU",
        "route_path": "/route",
        "component_path": "modules/route/pages",
        "icon": "Connection",
        "sort_order": 70,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "ROUTE_LIST",
        "menu_name": "航线",
        "menu_type_code": "MENU",
        "parent_code": "ROUTE_ROOT",
        "route_path": "/route/list",
        "component_path": "modules/route/pages/RouteListPage",
        "icon": "Connection",
        "sort_order": 1,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "ANALYSIS_ROOT",
        "menu_name": "数据分析",
        "menu_type_code": "MENU",
        "route_path": "/analysis",
        "component_path": "modules/analysis/pages",
        "icon": "DataAnalysis",
        "sort_order": 80,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "ANALYSIS_CARGO",
        "menu_name": "货源统计",
        "menu_type_code": "MENU",
        "parent_code": "ANALYSIS_ROOT",
        "route_path": "/analysis/cargo",
        "component_path": "modules/analysis/pages/AnalysisCargoPage",
        "icon": "DataLine",
        "sort_order": 1,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "ANALYSIS_SHIPS",
        "menu_name": "船舶统计",
        "menu_type_code": "MENU",
        "parent_code": "ANALYSIS_ROOT",
        "route_path": "/analysis/ships",
        "component_path": "modules/analysis/pages/AnalysisShipPage",
        "icon": "PieChart",
        "sort_order": 2,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "ANALYSIS_JOBS",
        "menu_name": "任务记录",
        "menu_type_code": "MENU",
        "parent_code": "ANALYSIS_ROOT",
        "route_path": "/analysis/jobs",
        "component_path": "modules/analysis/pages/AnalysisJobPage",
        "icon": "List",
        "sort_order": 3,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "AUDIT_ROOT",
        "menu_name": "审核管理",
        "menu_type_code": "MENU",
        "route_path": "/audit",
        "component_path": "modules/audit/pages",
        "icon": "Select",
        "sort_order": 85,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    },
    {
        "menu_code": "AUDIT_TASKS",
        "menu_name": "审核任务",
        "menu_type_code": "MENU",
        "parent_code": "AUDIT_ROOT",
        "route_path": "/audit/tasks",
        "component_path": "modules/audit/pages/AuditTaskListPage",
        "icon": "Select",
        "sort_order": 1,
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
