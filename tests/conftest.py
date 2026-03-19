"""测试全局配置。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_engine(tmp_path) -> AsyncGenerator:
    # 确保所有 ORM 模型在 create_all 前被加载到统一 Base.metadata
    from app.models import (  # noqa: F401
        address,
        cargo,
        vessel,
        route,
        analysis,
        system,
        audit,
        ai,
    )

    db_path = tmp_path / "phase6_test.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def session_factory(db_engine):
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def db_session(session_factory) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def fake_user():
    return SimpleNamespace(id=1, username="phase6_tester", real_name="Phase6 Tester", status=1)


@pytest_asyncio.fixture
async def client(session_factory, fake_user) -> AsyncGenerator[AsyncClient, None]:
    """提供带依赖覆盖的 ASGI 客户端（不走真实端口绑定）。"""
    from app.core.database import get_db as security_db_dep
    from app.core.dependencies import get_db as domain_db_dep
    from app.core.security import get_current_user_roles
    from main import app

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    async def _override_user_roles():
        return fake_user, ["SUPER_ADMIN", "ADMIN", "OPERATOR", "COLLECTOR"]

    app.dependency_overrides[domain_db_dep] = _override_get_db
    app.dependency_overrides[security_db_dep] = _override_get_db
    app.dependency_overrides[get_current_user_roles] = _override_user_roles

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
