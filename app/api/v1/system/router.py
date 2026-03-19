"""一期系统域主入口（Phase 2 cutover）"""
from fastapi import APIRouter

from app.api.v1.system.auth import router as auth_router
from app.api.v1.system.user import router as user_router
from app.api.v1.system.audit import router as audit_router

router = APIRouter()

router.include_router(auth_router, prefix="/auth", tags=["系统-认证"])
router.include_router(user_router, prefix="", tags=["系统-用户权限"])
router.include_router(audit_router, prefix="/audit", tags=["系统-审核"])
