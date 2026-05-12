from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class SysUser(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "sys_user"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    real_name: Mapped[str] = mapped_column(String(64), nullable=False)
    mobile_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status_code: Mapped[str] = mapped_column(String(64), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


class SysRole(Base, TimestampMixin):
    __tablename__ = "sys_role"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    role_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    role_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status_code: Mapped[str] = mapped_column(String(64), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class SysUserRole(Base):
    __tablename__ = "sys_user_role"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uk_sys_user_role"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=False, index=True
    )
    role_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_role.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class SysPermission(Base, TimestampMixin):
    __tablename__ = "sys_permission"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    permission_code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    permission_name: Mapped[str] = mapped_column(String(128), nullable=False)
    permission_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    action_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)


class SysRolePermission(Base):
    __tablename__ = "sys_role_permission"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uk_sys_role_permission"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    role_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_role.id"), nullable=False, index=True
    )
    permission_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_permission.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class SysMenu(Base, TimestampMixin):
    __tablename__ = "sys_menu"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_menu.id"), nullable=True
    )
    menu_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    menu_name: Mapped[str] = mapped_column(String(128), nullable=False)
    menu_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    route_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    component_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    permission_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    visible_flag: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status_code: Mapped[str] = mapped_column(String(64), nullable=False)


class SysRoleMenu(Base):
    __tablename__ = "sys_role_menu"
    __table_args__ = (UniqueConstraint("role_id", "menu_id", name="uk_sys_role_menu"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    role_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_role.id"), nullable=False, index=True
    )
    menu_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_menu.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class SysDataScope(Base, TimestampMixin):
    __tablename__ = "sys_data_scope"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scope_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    scope_name: Mapped[str] = mapped_column(String(128), nullable=False)
    data_scope_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    region_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("region.id"), nullable=True)
    city_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    node_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)


class SysRoleDataScope(Base):
    __tablename__ = "sys_role_data_scope"
    __table_args__ = (
        UniqueConstraint("role_id", "data_scope_id", name="uk_sys_role_data_scope"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    role_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_role.id"), nullable=False, index=True
    )
    data_scope_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_data_scope.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class SysUserStatusLog(Base):
    __tablename__ = "sys_user_status_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=False, index=True
    )
    from_status_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_status_code: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    operator_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class SysLoginLog(Base):
    __tablename__ = "sys_login_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_user.id"), nullable=True, index=True
    )
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    login_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    login_result_code: Mapped[str] = mapped_column(String(64), nullable=False)
    login_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    logout_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class SystemConfig(Base):
    __tablename__ = "system_config"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    config_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    config_name: Mapped[str] = mapped_column(String(128), nullable=False)
    config_value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    config_group_code: Mapped[str] = mapped_column(String(64), nullable=False)
    config_profile_code: Mapped[str] = mapped_column(String(64), nullable=False, default="DEFAULT")
    sensitive_flag: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    encrypted_flag: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    editable_flag: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    config_status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="ACTIVE")
    last_test_status_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_test_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
