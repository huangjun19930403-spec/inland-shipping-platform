"""认证路由"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import (
    verify_password, create_access_token, get_current_user, get_current_user_roles
)
from app.models.system import SysUser, SysUserRole, SysRole
from app.schemas.auth import TokenResponse, UserInfo
from app.schemas.common import success

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """用户登录，返回 JWT Token"""
    result = await db.execute(
        select(SysUser).where(SysUser.username == form_data.username)
    )
    user = result.scalar_one_or_none()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.status != 1:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用")

    # Get roles
    roles_result = await db.execute(
        select(SysRole.code).join(SysUserRole, SysRole.id == SysUserRole.role_id)
        .where(SysUserRole.user_id == user.id)
    )
    roles = [row[0] for row in roles_result.fetchall()]

    access_token = create_access_token(data={"sub": str(user.id)})

    # Update last login
    from datetime import datetime
    user.last_login_at = datetime.utcnow()
    await db.commit()

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=user.id,
        username=user.username,
        real_name=user.real_name,
        roles=roles,
    )


@router.get("/me", response_model=UserInfo)
async def get_me(
    user_roles=Depends(get_current_user_roles),
    db: AsyncSession = Depends(get_db),
):
    """获取当前登录用户信息"""
    user, roles = user_roles
    return UserInfo(
        id=user.id,
        username=user.username,
        real_name=user.real_name,
        phone=user.phone,
        email=user.email,
        department=user.department,
        status=user.status,
        roles=roles,
    )


@router.post("/logout")
async def logout():
    """登出（客户端清除 Token 即可）"""
    return success(message="已登出")
