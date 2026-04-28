"""system 模块 router（承载 auth + system 管理）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.modules.system.schemas import (
    ChangeMyPasswordRequest,
    CurrentUserMenuTreeResponse,
    CurrentUserResponse,
    DataScopeListQuery,
    DataScopeResponse,
    LoginLogListQuery,
    LoginLogResponse,
    LoginRequest,
    LoginResponse,
    MenuCreateRequest,
    MenuListQuery,
    MenuResponse,
    MenuTreeNodeResponse,
    PageResponse,
    PermissionListQuery,
    PermissionResponse,
    RoleCreateRequest,
    RoleDataScopeReplaceRequest,
    RoleDetailResponse,
    RoleListQuery,
    RoleMenuReplaceRequest,
    RolePermissionReplaceRequest,
    RoleResponse,
    RoleUpdateRequest,
    SystemConfigCreateRequest,
    SystemConfigListQuery,
    SystemConfigResponse,
    SystemConfigUpdateRequest,
    UserCreateRequest,
    UserDetailResponse,
    UserListQuery,
    UserResetPasswordRequest,
    UserResponse,
    UserRoleReplaceRequest,
    UserStatusChangeRequest,
    UserStatusLogResponse,
    UserUpdateRequest,
)
from app.modules.system.service import (
    AuthService,
    DataScopeService,
    LoginLogService,
    MenuService,
    PermissionService,
    RoleService,
    SystemConfigService,
    UserService,
)

router = APIRouter()
auth_router = APIRouter(prefix="/auth", tags=["auth"])
system_router = APIRouter(prefix="/system", tags=["system"])


@auth_router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    service = AuthService(db)
    return await service.login(
        username=body.username,
        password=body.password,
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


@auth_router.post("/logout")
async def logout(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AuthService(db)
    await service.logout(current_user)
    return {"ok": True}


@auth_router.get("/me", response_model=CurrentUserResponse)
async def get_me(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AuthService(db)
    return await service.get_current_user_profile(current_user)


@auth_router.get("/me/menus", response_model=list[CurrentUserMenuTreeResponse])
async def get_my_menus(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AuthService(db)
    return await service.get_current_user_menu_tree(current_user)


@auth_router.put("/me/password")
async def change_my_password(
    body: ChangeMyPasswordRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AuthService(db)
    await service.change_my_password(current_user, body.old_password, body.new_password)
    return {"ok": True}


@system_router.get("/users", response_model=PageResponse[UserResponse])
async def list_users(
    query: UserListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = UserService(db)
    return await service.list_users(query.keyword, query.status_code, query.role_id, query.page, query.page_size)


@system_router.get("/users/{user_id}", response_model=UserDetailResponse)
async def get_user_detail(
    user_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = UserService(db)
    return await service.get_user_detail(user_id)


@system_router.post("/users", response_model=UserResponse)
async def create_user(
    body: UserCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = UserService(db)
    return await service.create_user(body)


@system_router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    body: UserUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = UserService(db)
    return await service.update_user(user_id, body)


@system_router.put("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    body: UserResetPasswordRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = UserService(db)
    await service.reset_user_password(user_id, body.new_password)
    return {"ok": True}


@system_router.put("/users/{user_id}/status")
async def change_user_status(
    user_id: int,
    body: UserStatusChangeRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = UserService(db)
    await service.change_user_status(
        user_id=user_id,
        new_status=body.status_code,
        operator=current_user.id,
        reason=body.reason,
    )
    return {"ok": True}


@system_router.put("/users/{user_id}/roles")
async def replace_user_roles(
    user_id: int,
    body: UserRoleReplaceRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = UserService(db)
    await service.replace_user_roles(user_id, body.role_ids)
    return {"ok": True}


@system_router.get("/users/{user_id}/status-logs", response_model=PageResponse[UserStatusLogResponse])
async def list_user_status_logs(
    user_id: int,
    page: int = 1,
    page_size: int = 20,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = UserService(db)
    return await service.list_user_status_logs(user_id, page, page_size)


@system_router.get("/roles", response_model=PageResponse[RoleResponse])
async def list_roles(
    query: RoleListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = RoleService(db)
    return await service.list_roles(query.keyword, query.status_code, query.page, query.page_size)


@system_router.get("/roles/{role_id}", response_model=RoleDetailResponse)
async def get_role_detail(
    role_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = RoleService(db)
    return await service.get_role_detail(role_id)


@system_router.post("/roles", response_model=RoleResponse)
async def create_role(
    body: RoleCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = RoleService(db)
    return await service.create_role(body)


@system_router.put("/roles/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: int,
    body: RoleUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = RoleService(db)
    return await service.update_role(role_id, body)


@system_router.put("/roles/{role_id}/permissions")
async def replace_role_permissions(
    role_id: int,
    body: RolePermissionReplaceRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = RoleService(db)
    await service.replace_role_permissions(role_id, body.permission_ids)
    return {"ok": True}


@system_router.put("/roles/{role_id}/menus")
async def replace_role_menus(
    role_id: int,
    body: RoleMenuReplaceRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = RoleService(db)
    await service.replace_role_menus(role_id, body.menu_ids)
    return {"ok": True}


@system_router.put("/roles/{role_id}/data-scopes")
async def replace_role_data_scopes(
    role_id: int,
    body: RoleDataScopeReplaceRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = RoleService(db)
    await service.replace_role_data_scopes(role_id, body.data_scope_ids)
    return {"ok": True}


@system_router.get("/permissions", response_model=PageResponse[PermissionResponse])
async def list_permissions(
    query: PermissionListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = PermissionService(db)
    return await service.list_permissions(
        query.keyword, query.module_code, query.status_code, query.page, query.page_size
    )


@system_router.get("/permissions/all", response_model=list[PermissionResponse])
async def list_all_permissions(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = PermissionService(db)
    return await service.list_all_permissions()


@system_router.get("/menus", response_model=PageResponse[MenuResponse])
async def list_menus(
    query: MenuListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = MenuService(db)
    return await service.list_menus(query.keyword, query.status_code, query.page, query.page_size)


@system_router.get("/menus/tree", response_model=list[MenuTreeNodeResponse])
async def list_menu_tree(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = MenuService(db)
    return await service.list_menu_tree()


@system_router.post("/menus", response_model=MenuResponse)
async def create_menu(
    body: MenuCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = MenuService(db)
    return await service.create_menu(body)


@system_router.put("/menus/{menu_id}", response_model=MenuResponse)
async def update_menu(
    menu_id: int,
    body: MenuUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = MenuService(db)
    return await service.update_menu(menu_id, body)


@system_router.get("/data-scopes", response_model=PageResponse[DataScopeResponse])
async def list_data_scopes(
    query: DataScopeListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = DataScopeService(db)
    return await service.list_data_scopes(query.keyword, query.status_code, query.page, query.page_size)


@system_router.get("/data-scopes/all", response_model=list[DataScopeResponse])
async def list_all_data_scopes(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = DataScopeService(db)
    return await service.list_all_data_scopes()


@system_router.get("/configs", response_model=PageResponse[SystemConfigResponse])
async def list_configs(
    query: SystemConfigListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = SystemConfigService(db)
    return await service.list_configs(
        query.keyword,
        query.group_code,
        query.profile_code,
        query.status_code,
        query.page,
        query.page_size,
    )


@system_router.get("/configs/{config_key}", response_model=SystemConfigResponse)
async def get_config_detail(
    config_key: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = SystemConfigService(db)
    return await service.get_config_detail(config_key)


@system_router.post("/configs", response_model=SystemConfigResponse)
async def create_config(
    body: SystemConfigCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = SystemConfigService(db)
    return await service.create_config(body, operator_id=current_user.id)


@system_router.put("/configs/{config_key}", response_model=SystemConfigResponse)
async def update_config(
    config_key: str,
    body: SystemConfigUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = SystemConfigService(db)
    return await service.update_config(config_key, body, operator_id=current_user.id)


@system_router.get("/login-logs", response_model=PageResponse[LoginLogResponse])
async def list_login_logs(
    query: LoginLogListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = LoginLogService(db)
    return await service.list_login_logs(query.keyword, query.login_result, query.page, query.page_size)


router.include_router(auth_router)
router.include_router(system_router)
