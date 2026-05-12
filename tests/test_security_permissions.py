from __future__ import annotations

from datetime import datetime

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import BigInteger
from starlette.requests import Request

import app.models  # noqa: F401
from app.core.exceptions import PermissionError
from app.core.security import create_access_token, get_current_user, require_permission
from app.models.base import Base
from app.models.system import SysMenu, SysRoleMenu, SysPermission, SysRole, SysRolePermission, SysUser, SysUserRole
from app.modules.system.service import AuthService


@compiles(BigInteger, "sqlite")
def _compile_bigint_sqlite(element, compiler, **kw) -> str:
    _ = element, compiler, kw
    return "INTEGER"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


def _request(method: str) -> Request:
    return Request({"type": "http", "method": method, "path": "/api/v1/freight/test", "headers": []})


async def _create_user_with_permissions(
    session: AsyncSession,
    *,
    username: str,
    role_code: str,
    permission_codes: list[str],
    user_status: str = "ACTIVE",
    role_status: str = "ACTIVE",
) -> SysUser:
    user = SysUser(
        username=username,
        password_hash="not-used",
        real_name=username,
        mobile_phone=None,
        email=None,
        status_code=user_status,
        last_login_at=None,
        last_login_ip=None,
    )
    role = SysRole(
        role_code=role_code,
        role_name=role_code,
        description=None,
        status_code=role_status,
        sort_order=0,
    )
    session.add_all([user, role])
    await session.flush()
    session.add(SysUserRole(user_id=user.id, role_id=role.id, created_at=datetime.utcnow()))
    for permission_code in permission_codes:
        permission = SysPermission(
            permission_code=permission_code,
            permission_name=permission_code,
            permission_type_code="API",
            resource_path="/api/v1/*",
            action_code=permission_code.split(":")[-1],
            description=None,
        )
        session.add(permission)
        await session.flush()
        session.add(SysRolePermission(role_id=role.id, permission_id=permission.id, created_at=datetime.utcnow()))
    await session.commit()
    return user


@pytest.mark.asyncio
async def test_read_permission_allows_safe_methods(session: AsyncSession) -> None:
    user = await _create_user_with_permissions(
        session,
        username="freight-reader",
        role_code="FREIGHT_READER",
        permission_codes=["FREIGHT:READ"],
    )

    dependency = require_permission("FREIGHT:READ")

    assert await dependency(_request("GET"), current_user=user, db=session) is user


@pytest.mark.asyncio
async def test_read_permission_does_not_allow_write_methods(session: AsyncSession) -> None:
    user = await _create_user_with_permissions(
        session,
        username="readonly-writer",
        role_code="FREIGHT_READONLY",
        permission_codes=["FREIGHT:READ"],
    )

    dependency = require_permission("FREIGHT:READ")

    with pytest.raises(PermissionError, match="没有访问"):
        await dependency(_request("POST"), current_user=user, db=session)


@pytest.mark.asyncio
async def test_all_permission_allows_write_methods(session: AsyncSession) -> None:
    user = await _create_user_with_permissions(
        session,
        username="freight-admin",
        role_code="FREIGHT_ADMIN",
        permission_codes=["FREIGHT:ALL"],
    )

    dependency = require_permission("FREIGHT:READ")

    assert await dependency(_request("DELETE"), current_user=user, db=session) is user


@pytest.mark.asyncio
async def test_write_permission_allows_read_methods(session: AsyncSession) -> None:
    user = await _create_user_with_permissions(
        session,
        username="freight-writer",
        role_code="FREIGHT_WRITER",
        permission_codes=["FREIGHT:WRITE"],
    )

    dependency = require_permission("FREIGHT:READ")

    assert await dependency(_request("GET"), current_user=user, db=session) is user


@pytest.mark.asyncio
async def test_master_data_read_allows_master_read_only(session: AsyncSession) -> None:
    user = await _create_user_with_permissions(
        session,
        username="master-reader",
        role_code="MASTER_READER",
        permission_codes=["MASTER_DATA:READ"],
    )

    dependency = require_permission("ADDRESS:READ")

    assert await dependency(_request("GET"), current_user=user, db=session) is user
    with pytest.raises(PermissionError, match="没有访问"):
        await dependency(_request("POST"), current_user=user, db=session)


@pytest.mark.asyncio
async def test_super_admin_role_bypasses_permission_codes(session: AsyncSession) -> None:
    user = await _create_user_with_permissions(
        session,
        username="root",
        role_code="SUPER_ADMIN",
        permission_codes=[],
    )

    dependency = require_permission("SYSTEM:WRITE")

    assert await dependency(_request("PATCH"), current_user=user, db=session) is user


@pytest.mark.asyncio
async def test_current_user_menus_are_filtered_by_permission_code(session: AsyncSession) -> None:
    user = await _create_user_with_permissions(
        session,
        username="freight-menu-reader",
        role_code="FREIGHT_MENU_READER",
        permission_codes=["FREIGHT:READ"],
    )
    role = await session.scalar(select(SysRole).where(SysRole.role_code == "FREIGHT_MENU_READER"))
    assert role is not None
    read_menu = SysMenu(
        parent_id=None,
        menu_code="FREIGHT_LIST",
        menu_name="运输机会",
        menu_type_code="MENU",
        route_path="/freight/list",
        component_path=None,
        permission_code="FREIGHT:READ",
        icon=None,
        sort_order=1,
        visible_flag=1,
        status_code="ACTIVE",
    )
    write_menu = SysMenu(
        parent_id=None,
        menu_code="FREIGHT_CREATE",
        menu_name="手工录入",
        menu_type_code="MENU",
        route_path="/freight/manual-create",
        component_path=None,
        permission_code="FREIGHT:WRITE",
        icon=None,
        sort_order=2,
        visible_flag=1,
        status_code="ACTIVE",
    )
    session.add_all([read_menu, write_menu])
    await session.flush()
    session.add_all(
        [
            SysRoleMenu(role_id=role.id, menu_id=read_menu.id, created_at=datetime.utcnow()),
            SysRoleMenu(role_id=role.id, menu_id=write_menu.id, created_at=datetime.utcnow()),
        ]
    )
    await session.commit()

    tree = await AuthService(session).get_current_user_menu_tree(user)

    assert [item.menu_code for item in tree] == ["FREIGHT_LIST"]


@pytest.mark.asyncio
async def test_disabled_user_token_is_rejected(session: AsyncSession) -> None:
    user = await _create_user_with_permissions(
        session,
        username="disabled-user",
        role_code="OPS",
        permission_codes=["FREIGHT:READ"],
        user_status="DISABLED",
    )
    token = create_access_token({"sub": str(user.id)})

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(token=token, db=session)

    assert exc_info.value.status_code == 401
