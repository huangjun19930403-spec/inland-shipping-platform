"""system 模块 schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResponse(BaseModel, Generic[T]):
    total: int
    page: int
    page_size: int
    items: list[T]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int


class CurrentUserResponse(BaseModel):
    id: int
    username: str
    real_name: str
    mobile_phone: str | None
    email: str | None
    status_code: str
    role_codes: list[str]
    permission_codes: list[str]


class ChangeMyPasswordRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class CurrentUserMenuTreeResponse(BaseModel):
    id: int
    menu_code: str
    menu_name: str
    menu_type_code: str
    route_path: str | None
    component_path: str | None
    icon: str | None
    sort_order: int
    visible_flag: int
    status_code: str
    children: list["CurrentUserMenuTreeResponse"] = Field(default_factory=list)


class UserListQuery(BaseModel):
    keyword: str | None = None
    status_code: str | None = None
    role_id: int | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    real_name: str = Field(min_length=1, max_length=64)
    mobile_phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=128)
    status_code: str = Field(default="ACTIVE", min_length=1, max_length=64)
    role_ids: list[int] = Field(default_factory=list)


class UserUpdateRequest(BaseModel):
    real_name: str | None = Field(default=None, min_length=1, max_length=64)
    mobile_phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=128)


class UserResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class UserStatusChangeRequest(BaseModel):
    status_code: str = Field(min_length=1, max_length=64)
    reason: str | None = Field(default=None, max_length=512)


class UserRoleReplaceRequest(BaseModel):
    role_ids: list[int] = Field(default_factory=list)


class UserResponse(BaseModel):
    id: int
    username: str
    real_name: str
    mobile_phone: str | None
    email: str | None
    status_code: str
    last_login_at: datetime | None
    last_login_ip: str | None
    created_at: datetime
    updated_at: datetime


class UserDetailResponse(BaseModel):
    user: UserResponse
    role_ids: list[int]
    role_codes: list[str]
    permission_codes: list[str]


class UserStatusLogResponse(BaseModel):
    id: int
    user_id: int
    from_status_code: str | None
    to_status_code: str
    reason: str | None
    operator_id: int | None
    created_at: datetime


class RoleListQuery(BaseModel):
    keyword: str | None = None
    status_code: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class RoleCreateRequest(BaseModel):
    role_code: str = Field(min_length=1, max_length=64)
    role_name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    status_code: str = Field(default="ACTIVE", min_length=1, max_length=64)
    sort_order: int = 0


class RoleUpdateRequest(BaseModel):
    role_name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    status_code: str | None = Field(default=None, min_length=1, max_length=64)
    sort_order: int | None = None


class RolePermissionReplaceRequest(BaseModel):
    permission_ids: list[int] = Field(default_factory=list)


class RoleMenuReplaceRequest(BaseModel):
    menu_ids: list[int] = Field(default_factory=list)


class RoleDataScopeReplaceRequest(BaseModel):
    data_scope_ids: list[int] = Field(default_factory=list)


class RoleResponse(BaseModel):
    id: int
    role_code: str
    role_name: str
    description: str | None
    status_code: str
    sort_order: int
    created_at: datetime
    updated_at: datetime


class RoleDetailResponse(BaseModel):
    role: RoleResponse
    permission_ids: list[int]
    menu_ids: list[int]
    data_scope_ids: list[int]


class PermissionListQuery(BaseModel):
    keyword: str | None = None
    module_code: str | None = None
    status_code: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class PermissionResponse(BaseModel):
    id: int
    permission_code: str
    permission_name: str
    permission_type_code: str
    resource_path: str | None
    action_code: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime


class MenuListQuery(BaseModel):
    keyword: str | None = None
    status_code: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=500)


class MenuCreateRequest(BaseModel):
    parent_id: int | None = None
    menu_code: str = Field(min_length=1, max_length=64)
    menu_name: str = Field(min_length=1, max_length=128)
    menu_type_code: str = Field(min_length=1, max_length=64)
    route_path: str | None = Field(default=None, max_length=256)
    component_path: str | None = Field(default=None, max_length=256)
    icon: str | None = Field(default=None, max_length=64)
    sort_order: int = 0
    visible_flag: int = Field(default=1, ge=0, le=1)
    status_code: str = Field(default="ACTIVE", min_length=1, max_length=64)


class MenuUpdateRequest(BaseModel):
    parent_id: int | None = None
    menu_name: str | None = Field(default=None, min_length=1, max_length=128)
    menu_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    route_path: str | None = Field(default=None, max_length=256)
    component_path: str | None = Field(default=None, max_length=256)
    icon: str | None = Field(default=None, max_length=64)
    sort_order: int | None = None
    visible_flag: int | None = Field(default=None, ge=0, le=1)
    status_code: str | None = Field(default=None, min_length=1, max_length=64)


class MenuResponse(BaseModel):
    id: int
    parent_id: int | None
    menu_code: str
    menu_name: str
    menu_type_code: str
    route_path: str | None
    component_path: str | None
    icon: str | None
    sort_order: int
    visible_flag: int
    status_code: str
    created_at: datetime
    updated_at: datetime


class MenuTreeNodeResponse(BaseModel):
    id: int
    parent_id: int | None
    menu_code: str
    menu_name: str
    menu_type_code: str
    route_path: str | None
    component_path: str | None
    icon: str | None
    sort_order: int
    visible_flag: int
    status_code: str
    children: list["MenuTreeNodeResponse"] = Field(default_factory=list)


class DataScopeListQuery(BaseModel):
    keyword: str | None = None
    status_code: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class DataScopeResponse(BaseModel):
    id: int
    scope_code: str
    scope_name: str
    data_scope_type_code: str
    region_id: int | None
    city_code: str | None
    node_id: int | None
    description: str | None
    created_at: datetime
    updated_at: datetime


class SystemConfigListQuery(BaseModel):
    keyword: str | None = None
    group_code: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class SystemConfigCreateRequest(BaseModel):
    config_key: str = Field(min_length=1, max_length=128)
    config_name: str = Field(min_length=1, max_length=128)
    config_value: str
    value_type_code: str = Field(min_length=1, max_length=64)
    config_group_code: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=512)


class SystemConfigUpdateRequest(BaseModel):
    config_name: str | None = Field(default=None, min_length=1, max_length=128)
    config_value: str | None = None
    value_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    config_group_code: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=512)


class SystemConfigResponse(BaseModel):
    id: int
    config_key: str
    config_name: str
    config_value: str
    value_type_code: str
    config_group_code: str
    description: str | None
    updated_by: int | None
    updated_at: datetime
    created_at: datetime


class LoginLogListQuery(BaseModel):
    keyword: str | None = None
    login_result: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class LoginLogResponse(BaseModel):
    id: int
    user_id: int | None
    username: str
    login_ip: str | None
    user_agent: str | None
    login_result_code: str
    login_at: datetime
    logout_at: datetime | None
    created_at: datetime


CurrentUserMenuTreeResponse.model_rebuild()
MenuTreeNodeResponse.model_rebuild()
