from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.core.database import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")



def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="认证失败，请重新登录",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    from app.models.system import SysUser
    result = await db.execute(select(SysUser).where(SysUser.id == int(user_id)))
    user = result.scalar_one_or_none()
    if user is None or user.status != 1:
        raise credentials_exception
    return user


async def get_current_user_roles(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的所有角色编码"""
    from app.models.system import SysUserRole, SysRole
    result = await db.execute(
        select(SysRole.code).join(
            SysUserRole, SysRole.id == SysUserRole.role_id
        ).where(SysUserRole.user_id == current_user.id)
    )
    roles = [row[0] for row in result.fetchall()]
    return current_user, roles


def require_roles(*allowed_roles):
    """装饰器：要求用户具有指定角色之一"""
    async def role_checker(user_roles=Depends(get_current_user_roles)):
        user, roles = user_roles
        if "SUPER_ADMIN" in roles:
            return user, roles
        for role in allowed_roles:
            if role in roles:
                return user, roles
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="权限不足",
        )
    return role_checker
