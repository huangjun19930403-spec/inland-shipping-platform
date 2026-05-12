"""认证基础能力（system/auth 使用）。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import PermissionError
from app.models.system import SysPermission, SysRole, SysRolePermission, SysUser, SysUserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
SAFE_HTTP_METHODS = {"GET", "HEAD", "OPTIONS"}


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not plain_password or not hashed_password:
        return False
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    payload = data.copy()
    expire_at = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload.update({"exp": expire_at})
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def _is_user_enabled(status_code: str | None) -> bool:
    value = (status_code or "").upper()
    return value not in {"DISABLED", "INACTIVE", "LOCKED", "DELETED"}


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> SysUser:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="认证失败，请重新登录",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        subject = payload.get("sub")
        if not subject:
            raise credentials_exception
        user_id = int(subject)
    except (JWTError, ValueError, TypeError):
        raise credentials_exception

    user = await db.scalar(
        select(SysUser).where(SysUser.id == user_id, SysUser.deleted_at.is_(None))
    )
    if user is None or not _is_user_enabled(user.status_code):
        raise credentials_exception
    return user


def _permission_module(code: str) -> str:
    return code.split(":", 1)[0].strip().upper()


def _permission_matches(granted: str, required: str) -> bool:
    granted_value = granted.strip().upper()
    required_value = required.strip().upper()
    if not granted_value or not required_value:
        return False
    if granted_value == required_value:
        return True
    if granted_value == "SYSTEM:ALL":
        return True
    granted_module = _permission_module(granted_value)
    required_module = _permission_module(required_value)
    granted_action = granted_value.split(":", 1)[1] if ":" in granted_value else ""
    required_action = required_value.split(":", 1)[1] if ":" in required_value else ""
    if granted_value == f"{required_module}:ALL":
        return True
    if granted_module == required_module and granted_action == "MANAGE":
        return True
    if (
        granted_module == required_module
        and granted_action == "WRITE"
        and required_action == "READ"
    ):
        return True
    if (
        granted_module == required_module
        and granted_action == "EXPORT"
        and required_action == "READ"
    ):
        return True
    if (
        granted_module == required_module
        and granted_action == "AUDIT"
        and required_action == "READ"
    ):
        return True
    if granted_value == "MASTER_DATA:ALL" and required_module in {
        "ADDRESS",
        "COMMODITY",
        "DICTIONARY",
        "ROUTE",
        "VESSEL",
    }:
        return True
    if granted_value == "FREIGHT:ALL" and required_module == "STORAGE":
        return True
    if granted_value == "MASTER_DATA:ALL" and required_module == "STORAGE":
        return True
    if granted_value == "MASTER_DATA:READ" and required_action == "READ" and required_module in {
        "ADDRESS",
        "COMMODITY",
        "DICTIONARY",
        "ROUTE",
        "VESSEL",
        "STORAGE",
    }:
        return True
    if (
        granted_value == "MASTER_DATA:WRITE"
        and required_action in {"READ", "WRITE"}
        and required_module
        in {
            "ADDRESS",
            "COMMODITY",
            "DICTIONARY",
            "ROUTE",
            "VESSEL",
            "STORAGE",
        }
    ):
        return True
    if granted_value == "ANALYSIS:READ" and required_value.startswith("ANALYSIS:"):
        return required_value in {"ANALYSIS:READ", "ANALYSIS:EXPORT"}
    return False


async def list_current_user_permission_codes(db: AsyncSession, user_id: int) -> list[str]:
    stmt = (
        select(SysPermission.permission_code)
        .join(SysRolePermission, SysRolePermission.permission_id == SysPermission.id)
        .join(SysRole, SysRole.id == SysRolePermission.role_id)
        .join(SysUserRole, SysUserRole.role_id == SysRole.id)
        .where(
            SysUserRole.user_id == user_id,
            SysRole.status_code == "ACTIVE",
        )
        .distinct()
    )
    return [str(row[0]) for row in (await db.execute(stmt)).all()]


async def list_current_user_role_codes(db: AsyncSession, user_id: int) -> list[str]:
    stmt = (
        select(SysRole.role_code)
        .join(SysUserRole, SysUserRole.role_id == SysRole.id)
        .where(
            SysUserRole.user_id == user_id,
            SysRole.status_code == "ACTIVE",
        )
        .distinct()
    )
    return [str(row[0]) for row in (await db.execute(stmt)).all()]


def require_permission(*required_codes: str) -> Callable[..., SysUser]:
    async def _dependency(
        request: Request,
        current_user: SysUser = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> SysUser:
        required = [code.strip().upper() for code in required_codes if code.strip()]
        if not required:
            return current_user
        if request.method.upper() not in SAFE_HTTP_METHODS:
            required = [
                f"{_permission_module(code)}:WRITE" if code.endswith(":READ") else code
                for code in required
            ]

        role_codes = await list_current_user_role_codes(db, current_user.id)
        if "SUPER_ADMIN" in {code.upper() for code in role_codes}:
            return current_user

        permission_codes = await list_current_user_permission_codes(db, current_user.id)
        if any(
            _permission_matches(granted, required_code)
            for required_code in required
            for granted in permission_codes
        ):
            return current_user
        raise PermissionError("当前账号没有访问该功能的权限")

    return _dependency
