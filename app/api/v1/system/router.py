"""系统管理路由"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.core.database import get_db
from app.core.security import require_roles, get_password_hash
from app.models.system import SysUser, SysRole, SysUserRole
from app.schemas.system import UserCreate, UserUpdate, UserResponse, RoleResponse, PasswordResetRequest
from app.schemas.common import success

router = APIRouter()


async def _get_user_roles(db: AsyncSession, user_id: int) -> list:
    res = await db.execute(
        select(SysRole.code).join(SysUserRole, SysRole.id == SysUserRole.role_id)
        .where(SysUserRole.user_id == user_id)
    )
    return [row[0] for row in res.fetchall()]


async def _assign_roles(db: AsyncSession, user_id: int, role_ids: list) -> None:
    # Remove existing roles
    existing = await db.execute(select(SysUserRole).where(SysUserRole.user_id == user_id))
    for ur in existing.scalars().all():
        await db.delete(ur)
    # Assign new roles
    for role_id in role_ids:
        db.add(SysUserRole(user_id=user_id, role_id=role_id))
    await db.flush()


@router.get("/users", summary="获取用户列表")
async def list_users(
    status: Optional[int] = None,
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    query = select(SysUser)
    count_query = select(func.count(SysUser.id))
    conditions = []
    if status is not None:
        conditions.append(SysUser.status == status)
    if keyword:
        conditions.append(
            SysUser.username.ilike(f"%{keyword}%") | SysUser.real_name.ilike(f"%{keyword}%")
        )
    if conditions:
        query = query.where(and_(*conditions))
        count_query = count_query.where(and_(*conditions))

    total_res = await db.execute(count_query)
    total = total_res.scalar_one()
    query = query.order_by(SysUser.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    users = result.scalars().all()

    items = []
    for u in users:
        roles = await _get_user_roles(db, u.id)
        item = UserResponse(
            id=u.id, username=u.username, real_name=u.real_name,
            phone=u.phone, email=u.email, department=u.department,
            status=u.status, last_login_at=u.last_login_at,
            created_at=u.created_at, roles=roles,
        )
        items.append(item)

    return success(data={"total": total, "items": items, "page": page, "page_size": page_size})


@router.post("/users", summary="创建用户")
async def create_user(
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    creator, roles = user_roles
    # Check username uniqueness
    res = await db.execute(select(SysUser).where(SysUser.username == data.username))
    if res.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名已存在")

    user = SysUser(
        username=data.username,
        real_name=data.real_name,
        password_hash=get_password_hash(data.password),
        phone=data.phone,
        email=data.email,
        department=data.department,
        status=1,
        created_by=creator.id,
    )
    db.add(user)
    await db.flush()

    if data.role_ids:
        await _assign_roles(db, user.id, data.role_ids)

    await db.commit()
    await db.refresh(user)
    user_roles_list = await _get_user_roles(db, user.id)
    return success(data=UserResponse(
        id=user.id, username=user.username, real_name=user.real_name,
        phone=user.phone, email=user.email, department=user.department,
        status=user.status, last_login_at=user.last_login_at,
        created_at=user.created_at, roles=user_roles_list,
    ))


@router.put("/users/{user_id}", summary="更新用户信息")
async def update_user(
    user_id: int,
    data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    res = await db.execute(select(SysUser).where(SysUser.id == user_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    updates = data.model_dump(exclude_none=True)
    role_ids = updates.pop("role_ids", None)

    for field, value in updates.items():
        setattr(user, field, value)

    if role_ids is not None:
        await _assign_roles(db, user_id, role_ids)

    await db.commit()
    await db.refresh(user)
    user_roles_list = await _get_user_roles(db, user.id)
    return success(data=UserResponse(
        id=user.id, username=user.username, real_name=user.real_name,
        phone=user.phone, email=user.email, department=user.department,
        status=user.status, last_login_at=user.last_login_at,
        created_at=user.created_at, roles=user_roles_list,
    ))


@router.delete("/users/{user_id}", summary="删除用户")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("SUPER_ADMIN")),
):
    res = await db.execute(select(SysUser).where(SysUser.id == user_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    await db.delete(user)
    await db.commit()
    return success(message="删除成功")


@router.post("/users/{user_id}/disable", summary="禁用用户")
async def disable_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    res = await db.execute(select(SysUser).where(SysUser.id == user_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.status = 0
    await db.commit()
    return success(message="已禁用")


@router.post("/users/{user_id}/enable", summary="启用用户")
async def enable_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    res = await db.execute(select(SysUser).where(SysUser.id == user_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.status = 1
    await db.commit()
    return success(message="已启用")


@router.post("/users/{user_id}/reset-password", summary="重置用户密码")
async def reset_password(
    user_id: int,
    data: PasswordResetRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    res = await db.execute(select(SysUser).where(SysUser.id == user_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.password_hash = get_password_hash(data.new_password)
    await db.commit()
    return success(message="密码已重置")


@router.get("/roles", summary="获取角色列表")
async def list_roles(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    result = await db.execute(select(SysRole).where(SysRole.status == 1).order_by(SysRole.sort_order))
    roles = result.scalars().all()
    return success(data=[RoleResponse.model_validate(r) for r in roles])
