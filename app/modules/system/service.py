"""system 模块 service。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError, ConflictError, NotFoundError, ValidationError
from app.core.security import create_access_token, get_password_hash, verify_password
from app.modules.system.repository import (
    SysDataScopeRepository,
    SysLoginLogRepository,
    SysMenuRepository,
    SysPermissionRepository,
    SysRoleRepository,
    SysUserRepository,
    SysUserStatusLogRepository,
    SystemConfigRepository,
)
from app.modules.system.schemas import (
    CurrentUserMenuTreeResponse,
    CurrentUserResponse,
    DataScopeResponse,
    LoginResponse,
    LoginLogResponse,
    MenuCreateRequest,
    MenuResponse,
    MenuTreeNodeResponse,
    MenuUpdateRequest,
    PageResponse,
    PermissionResponse,
    RoleCreateRequest,
    RoleDetailResponse,
    RoleResponse,
    RoleUpdateRequest,
    SystemConfigCreateRequest,
    SystemConfigResponse,
    SystemConfigUpdateRequest,
    UserCreateRequest,
    UserDetailResponse,
    UserResponse,
    UserStatusLogResponse,
    UserUpdateRequest,
)


def _to_user_response(row) -> UserResponse:
    return UserResponse(
        id=row.id,
        username=row.username,
        real_name=row.real_name,
        mobile_phone=row.mobile_phone,
        email=row.email,
        status_code=row.status_code,
        last_login_at=row.last_login_at,
        last_login_ip=row.last_login_ip,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_role_response(row) -> RoleResponse:
    return RoleResponse(
        id=row.id,
        role_code=row.role_code,
        role_name=row.role_name,
        description=row.description,
        status_code=row.status_code,
        sort_order=row.sort_order,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_permission_response(row) -> PermissionResponse:
    return PermissionResponse(
        id=row.id,
        permission_code=row.permission_code,
        permission_name=row.permission_name,
        permission_type_code=row.permission_type_code,
        resource_path=row.resource_path,
        action_code=row.action_code,
        description=row.description,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_menu_response(row) -> MenuResponse:
    return MenuResponse(
        id=row.id,
        parent_id=row.parent_id,
        menu_code=row.menu_code,
        menu_name=row.menu_name,
        menu_type_code=row.menu_type_code,
        route_path=row.route_path,
        component_path=row.component_path,
        icon=row.icon,
        sort_order=row.sort_order,
        visible_flag=row.visible_flag,
        status_code=row.status_code,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_data_scope_response(row) -> DataScopeResponse:
    return DataScopeResponse(
        id=row.id,
        scope_code=row.scope_code,
        scope_name=row.scope_name,
        data_scope_type_code=row.data_scope_type_code,
        region_id=row.region_id,
        city_code=row.city_code,
        node_id=row.node_id,
        description=row.description,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _mask_config_value(value: str | None) -> str:
    if not value:
        return "****"
    if len(value) <= 4:
        return "****"
    return f"******{value[-4:]}"


def _to_system_config_response(row) -> SystemConfigResponse:
    sensitive = int(row.sensitive_flag or 0) == 1
    if sensitive:
        config_value = ""
        config_value_masked = _mask_config_value(row.config_value)
    else:
        config_value = row.config_value
        config_value_masked = None

    return SystemConfigResponse(
        id=row.id,
        config_key=row.config_key,
        config_name=row.config_name,
        config_value=config_value,
        config_value_masked=config_value_masked,
        value_type_code=row.value_type_code,
        config_group_code=row.config_group_code,
        config_profile_code=row.config_profile_code,
        sensitive_flag=row.sensitive_flag,
        encrypted_flag=row.encrypted_flag,
        editable_flag=row.editable_flag,
        sort_order=row.sort_order,
        config_status_code=row.config_status_code,
        last_test_status_code=row.last_test_status_code,
        last_test_message=row.last_test_message,
        last_tested_at=row.last_tested_at,
        description=row.description,
        updated_by=row.updated_by,
        updated_at=row.updated_at,
        created_at=row.created_at,
    )


def _to_login_log_response(row) -> LoginLogResponse:
    return LoginLogResponse(
        id=row.id,
        user_id=row.user_id,
        username=row.username,
        login_ip=row.login_ip,
        user_agent=row.user_agent,
        login_result_code=row.login_result_code,
        login_at=row.login_at,
        logout_at=row.logout_at,
        created_at=row.created_at,
    )


def _to_status_log_response(row) -> UserStatusLogResponse:
    return UserStatusLogResponse(
        id=row.id,
        user_id=row.user_id,
        from_status_code=row.from_status_code,
        to_status_code=row.to_status_code,
        reason=row.reason,
        operator_id=row.operator_id,
        created_at=row.created_at,
    )


def _build_menu_tree_response(nodes: list[dict]) -> list[MenuTreeNodeResponse]:
    result: list[MenuTreeNodeResponse] = []
    for row in nodes:
        result.append(
            MenuTreeNodeResponse(
                id=row["id"],
                parent_id=row["parent_id"],
                menu_code=row["menu_code"],
                menu_name=row["menu_name"],
                menu_type_code=row["menu_type_code"],
                route_path=row["route_path"],
                component_path=row["component_path"],
                icon=row["icon"],
                sort_order=row["sort_order"],
                visible_flag=row["visible_flag"],
                status_code=row["status_code"],
                children=_build_menu_tree_response(row.get("children", [])),
            )
        )
    return result


def _build_current_user_menu_tree(nodes: list[dict]) -> list[CurrentUserMenuTreeResponse]:
    result: list[CurrentUserMenuTreeResponse] = []
    for row in nodes:
        result.append(
            CurrentUserMenuTreeResponse(
                id=row["id"],
                menu_code=row["menu_code"],
                menu_name=row["menu_name"],
                menu_type_code=row["menu_type_code"],
                route_path=row["route_path"],
                component_path=row["component_path"],
                icon=row["icon"],
                sort_order=row["sort_order"],
                visible_flag=row["visible_flag"],
                status_code=row["status_code"],
                children=_build_current_user_menu_tree(row.get("children", [])),
            )
        )
    return result


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.user_repo = SysUserRepository(db)
        self.login_log_repo = SysLoginLogRepository(db)

    async def login(
        self,
        username: str,
        password: str,
        client_ip: str | None,
        user_agent: str | None,
    ) -> LoginResponse:
        now = datetime.utcnow()
        user = await self.user_repo.get_user_by_username(username.strip())
        if user is None:
            await self.login_log_repo.create_login_log(
                {
                    "user_id": None,
                    "username": username.strip(),
                    "login_ip": client_ip,
                    "user_agent": user_agent,
                    "login_result_code": "FAILED",
                    "login_at": now,
                    "logout_at": None,
                    "created_at": now,
                }
            )
            await self.db.commit()
            raise AuthenticationError("用户名或密码错误")

        if not verify_password(password, user.password_hash):
            await self.login_log_repo.create_login_log(
                {
                    "user_id": user.id,
                    "username": user.username,
                    "login_ip": client_ip,
                    "user_agent": user_agent,
                    "login_result_code": "FAILED",
                    "login_at": now,
                    "logout_at": None,
                    "created_at": now,
                }
            )
            await self.db.commit()
            raise AuthenticationError("用户名或密码错误")

        status = (user.status_code or "").upper()
        if status in {"DISABLED", "INACTIVE", "LOCKED", "DELETED"}:
            await self.login_log_repo.create_login_log(
                {
                    "user_id": user.id,
                    "username": user.username,
                    "login_ip": client_ip,
                    "user_agent": user_agent,
                    "login_result_code": "REJECTED",
                    "login_at": now,
                    "logout_at": None,
                    "created_at": now,
                }
            )
            await self.db.commit()
            raise AuthenticationError("当前账号状态不可登录")

        await self.user_repo.update_user(
            user.id,
            {"last_login_at": now, "last_login_ip": client_ip},
        )
        await self.login_log_repo.create_login_log(
            {
                "user_id": user.id,
                "username": user.username,
                "login_ip": client_ip,
                "user_agent": user_agent,
                "login_result_code": "SUCCESS",
                "login_at": now,
                "logout_at": None,
                "created_at": now,
            }
        )
        token = create_access_token({"sub": str(user.id), "username": user.username})
        await self.db.commit()
        return LoginResponse(
            access_token=token,
            token_type="bearer",
            expires_in_seconds=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def logout(self, current_user) -> None:
        now = datetime.utcnow()
        updated = await self.login_log_repo.mark_latest_logout(current_user.id, now)
        if not updated:
            await self.login_log_repo.create_login_log(
                {
                    "user_id": current_user.id,
                    "username": current_user.username,
                    "login_ip": current_user.last_login_ip,
                    "user_agent": None,
                    "login_result_code": "LOGOUT",
                    "login_at": now,
                    "logout_at": now,
                    "created_at": now,
                }
            )
        await self.db.commit()

    async def get_current_user_profile(self, current_user) -> CurrentUserResponse:
        roles = await self.user_repo.list_user_roles(current_user.id)
        permissions = await self.user_repo.list_user_permissions(current_user.id)
        return CurrentUserResponse(
            id=current_user.id,
            username=current_user.username,
            real_name=current_user.real_name,
            mobile_phone=current_user.mobile_phone,
            email=current_user.email,
            status_code=current_user.status_code,
            role_codes=[item.role_code for item in roles],
            permission_codes=[item.permission_code for item in permissions],
        )

    async def get_current_user_menu_tree(self, current_user) -> list[CurrentUserMenuTreeResponse]:
        menus = await self.user_repo.list_user_menus(current_user.id)
        node_map: dict[int, dict] = {}
        roots: list[dict] = []
        for menu in menus:
            node_map[menu.id] = {
                "id": menu.id,
                "parent_id": menu.parent_id,
                "menu_code": menu.menu_code,
                "menu_name": menu.menu_name,
                "menu_type_code": menu.menu_type_code,
                "route_path": menu.route_path,
                "component_path": menu.component_path,
                "icon": menu.icon,
                "sort_order": menu.sort_order,
                "visible_flag": menu.visible_flag,
                "status_code": menu.status_code,
                "children": [],
            }
        for menu in menus:
            current = node_map[menu.id]
            if menu.parent_id and menu.parent_id in node_map:
                node_map[menu.parent_id]["children"].append(current)
            else:
                roots.append(current)
        roots.sort(key=lambda x: (x["sort_order"], x["id"]))
        return _build_current_user_menu_tree(roots)

    async def change_my_password(self, current_user, old_password: str, new_password: str) -> None:
        if not verify_password(old_password, current_user.password_hash):
            raise ValidationError("原密码不正确")
        await self.user_repo.update_user_password(
            current_user.id,
            get_password_hash(new_password),
        )
        await self.db.commit()


class UserService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.user_repo = SysUserRepository(db)
        self.status_log_repo = SysUserStatusLogRepository(db)

    async def list_users(
        self,
        keyword: str | None,
        status_code: str | None,
        role_id: int | None,
        page: int,
        page_size: int,
    ) -> PageResponse[UserResponse]:
        items, total = await self.user_repo.list_users(keyword, status_code, role_id, page, page_size)
        return PageResponse[UserResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_user_response(item) for item in items],
        )

    async def create_user(self, payload: UserCreateRequest) -> UserResponse:
        if await self.user_repo.get_user_by_username(payload.username.strip()):
            raise ConflictError(f"username already exists: {payload.username}")
        if payload.mobile_phone and await self.user_repo.get_user_by_mobile(payload.mobile_phone):
            raise ConflictError(f"mobile already exists: {payload.mobile_phone}")
        entity = await self.user_repo.create_user(
            {
                "username": payload.username.strip(),
                "password_hash": get_password_hash(payload.password),
                "real_name": payload.real_name.strip(),
                "mobile_phone": payload.mobile_phone,
                "email": payload.email,
                "status_code": payload.status_code,
            }
        )
        await self.user_repo.replace_user_roles(entity.id, payload.role_ids)
        await self.db.commit()
        return _to_user_response(entity)

    async def update_user(self, user_id: int, payload: UserUpdateRequest) -> UserResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        entity = await self.user_repo.update_user(user_id, updates)
        if entity is None:
            raise NotFoundError("SysUser", user_id)
        await self.db.commit()
        return _to_user_response(entity)

    async def get_user_detail(self, user_id: int) -> UserDetailResponse:
        user = await self.user_repo.get_user_by_id(user_id)
        if user is None:
            raise NotFoundError("SysUser", user_id)
        roles = await self.user_repo.list_user_roles(user_id)
        permissions = await self.user_repo.list_user_permissions(user_id)
        return UserDetailResponse(
            user=_to_user_response(user),
            role_ids=[item.id for item in roles],
            role_codes=[item.role_code for item in roles],
            permission_codes=[item.permission_code for item in permissions],
        )

    async def reset_user_password(self, user_id: int, new_password: str) -> None:
        ok = await self.user_repo.update_user_password(user_id, get_password_hash(new_password))
        if not ok:
            raise NotFoundError("SysUser", user_id)
        await self.db.commit()

    async def change_user_status(
        self,
        user_id: int,
        new_status: str,
        operator: int | None,
        reason: str | None,
    ) -> None:
        user = await self.user_repo.get_user_by_id(user_id)
        if user is None:
            raise NotFoundError("SysUser", user_id)
        from_status = user.status_code
        ok = await self.user_repo.update_user_status(user_id, new_status)
        if not ok:
            raise NotFoundError("SysUser", user_id)
        await self.status_log_repo.create_status_log(
            {
                "user_id": user_id,
                "from_status_code": from_status,
                "to_status_code": new_status,
                "reason": reason,
                "operator_id": operator,
                "created_at": datetime.utcnow(),
            }
        )
        await self.db.commit()

    async def replace_user_roles(self, user_id: int, role_ids: list[int]) -> None:
        user = await self.user_repo.get_user_by_id(user_id)
        if user is None:
            raise NotFoundError("SysUser", user_id)
        await self.user_repo.replace_user_roles(user_id, role_ids)
        await self.db.commit()

    async def list_user_status_logs(
        self, user_id: int, page: int, page_size: int
    ) -> PageResponse[UserStatusLogResponse]:
        user = await self.user_repo.get_user_by_id(user_id)
        if user is None:
            raise NotFoundError("SysUser", user_id)
        rows, total = await self.status_log_repo.list_status_logs(user_id, page, page_size)
        return PageResponse[UserStatusLogResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_status_log_response(item) for item in rows],
        )


class RoleService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = SysRoleRepository(db)

    async def list_roles(
        self, keyword: str | None, status_code: str | None, page: int, page_size: int
    ) -> PageResponse[RoleResponse]:
        items, total = await self.repo.list_roles(keyword, status_code, page, page_size)
        return PageResponse[RoleResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_role_response(item) for item in items],
        )

    async def create_role(self, payload: RoleCreateRequest) -> RoleResponse:
        if await self.repo.get_role_by_code(payload.role_code.strip()):
            raise ConflictError(f"role_code already exists: {payload.role_code}")
        entity = await self.repo.create_role(payload.model_dump())
        await self.db.commit()
        return _to_role_response(entity)

    async def update_role(self, role_id: int, payload: RoleUpdateRequest) -> RoleResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        entity = await self.repo.update_role(role_id, updates)
        if entity is None:
            raise NotFoundError("SysRole", role_id)
        await self.db.commit()
        return _to_role_response(entity)

    async def get_role_detail(self, role_id: int) -> RoleDetailResponse:
        role = await self.repo.get_role_by_id(role_id)
        if role is None:
            raise NotFoundError("SysRole", role_id)
        return RoleDetailResponse(
            role=_to_role_response(role),
            permission_ids=await self.repo.list_role_permissions(role_id),
            menu_ids=await self.repo.list_role_menus(role_id),
            data_scope_ids=await self.repo.list_role_data_scopes(role_id),
        )

    async def replace_role_permissions(self, role_id: int, permission_ids: list[int]) -> None:
        if await self.repo.get_role_by_id(role_id) is None:
            raise NotFoundError("SysRole", role_id)
        await self.repo.replace_role_permissions(role_id, permission_ids)
        await self.db.commit()

    async def replace_role_menus(self, role_id: int, menu_ids: list[int]) -> None:
        if await self.repo.get_role_by_id(role_id) is None:
            raise NotFoundError("SysRole", role_id)
        await self.repo.replace_role_menus(role_id, menu_ids)
        await self.db.commit()

    async def replace_role_data_scopes(self, role_id: int, data_scope_ids: list[int]) -> None:
        if await self.repo.get_role_by_id(role_id) is None:
            raise NotFoundError("SysRole", role_id)
        await self.repo.replace_role_data_scopes(role_id, data_scope_ids)
        await self.db.commit()


class PermissionService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = SysPermissionRepository(db)

    async def list_permissions(
        self,
        keyword: str | None,
        module_code: str | None,
        status_code: str | None,
        page: int,
        page_size: int,
    ) -> PageResponse[PermissionResponse]:
        items, total = await self.repo.list_permissions(
            keyword, module_code, status_code, page, page_size
        )
        return PageResponse[PermissionResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_permission_response(item) for item in items],
        )

    async def list_all_permissions(self) -> list[PermissionResponse]:
        rows = await self.repo.list_all_permissions()
        return [_to_permission_response(item) for item in rows]


class MenuService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = SysMenuRepository(db)

    async def list_menus(
        self,
        keyword: str | None,
        status_code: str | None,
        page: int,
        page_size: int,
    ) -> PageResponse[MenuResponse]:
        items, total = await self.repo.list_menus(keyword, status_code, page, page_size)
        return PageResponse[MenuResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_menu_response(item) for item in items],
        )

    async def list_menu_tree(self) -> list[MenuTreeNodeResponse]:
        return _build_menu_tree_response(await self.repo.build_menu_tree())

    async def create_menu(self, payload: MenuCreateRequest) -> MenuResponse:
        if await self.repo.get_menu_by_code(payload.menu_code.strip()):
            raise ConflictError(f"menu_code already exists: {payload.menu_code}")
        row = await self.repo.create_menu(payload.model_dump())
        await self.db.commit()
        return _to_menu_response(row)

    async def update_menu(self, menu_id: int, payload: MenuUpdateRequest) -> MenuResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        row = await self.repo.update_menu(menu_id, updates)
        if row is None:
            raise NotFoundError("SysMenu", menu_id)
        await self.db.commit()
        return _to_menu_response(row)


class DataScopeService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = SysDataScopeRepository(db)

    async def list_data_scopes(
        self,
        keyword: str | None,
        status_code: str | None,
        page: int,
        page_size: int,
    ) -> PageResponse[DataScopeResponse]:
        items, total = await self.repo.list_data_scopes(keyword, status_code, page, page_size)
        return PageResponse[DataScopeResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_data_scope_response(item) for item in items],
        )

    async def list_all_data_scopes(self) -> list[DataScopeResponse]:
        rows = await self.repo.list_all_data_scopes()
        return [_to_data_scope_response(item) for item in rows]


class SystemConfigService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = SystemConfigRepository(db)

    async def list_configs(
        self,
        keyword: str | None,
        group_code: str | None,
        profile_code: str | None,
        status_code: str | None,
        page: int,
        page_size: int,
    ) -> PageResponse[SystemConfigResponse]:
        items, total = await self.repo.list_configs(
            keyword,
            group_code,
            profile_code,
            status_code,
            page,
            page_size,
        )
        return PageResponse[SystemConfigResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_system_config_response(item) for item in items],
        )

    async def get_config_detail(self, config_key: str) -> SystemConfigResponse:
        row = await self.repo.get_config_by_key(config_key)
        if row is None:
            raise NotFoundError("SystemConfig", config_key)
        return _to_system_config_response(row)

    async def create_config(
        self,
        payload: SystemConfigCreateRequest,
        operator_id: int | None = None,
    ) -> SystemConfigResponse:
        if await self.repo.get_config_by_key(payload.config_key.strip()):
            raise ConflictError(f"config_key already exists: {payload.config_key}")
        now = datetime.utcnow()
        profile_code = (payload.config_profile_code or "DEFAULT").strip() or "DEFAULT"
        status_code = (payload.config_status_code or "ACTIVE").strip() or "ACTIVE"
        payload_data = payload.model_dump()
        row = await self.repo.create_config(
            {
                **payload_data,
                "config_key": payload.config_key.strip(),
                "config_profile_code": profile_code,
                "sensitive_flag": payload.sensitive_flag,
                "encrypted_flag": 0,
                "editable_flag": payload.editable_flag,
                "sort_order": payload.sort_order,
                "config_status_code": status_code,
                "last_test_status_code": None,
                "last_test_message": None,
                "last_tested_at": None,
                "updated_by": operator_id,
                "updated_at": now,
                "created_at": now,
            }
        )
        await self.db.commit()
        return _to_system_config_response(row)

    async def update_config(
        self,
        config_key: str,
        payload: SystemConfigUpdateRequest,
        operator_id: int | None = None,
    ) -> SystemConfigResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        if "config_profile_code" in updates:
            updates["config_profile_code"] = updates["config_profile_code"].strip()
            if not updates["config_profile_code"]:
                raise ValidationError("config_profile_code cannot be empty")
        if "config_status_code" in updates:
            updates["config_status_code"] = updates["config_status_code"].strip()
            if not updates["config_status_code"]:
                raise ValidationError("config_status_code cannot be empty")
        updates["updated_by"] = operator_id
        updates["updated_at"] = datetime.utcnow()
        row = await self.repo.update_config(config_key, updates)
        if row is None:
            raise NotFoundError("SystemConfig", config_key)
        await self.db.commit()
        return _to_system_config_response(row)


class LoginLogService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = SysLoginLogRepository(db)

    async def list_login_logs(
        self,
        keyword: str | None,
        login_result: str | None,
        page: int,
        page_size: int,
    ) -> PageResponse[LoginLogResponse]:
        rows, total = await self.repo.list_login_logs(keyword, login_result, page, page_size)
        return PageResponse[LoginLogResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_login_log_response(item) for item in rows],
        )
