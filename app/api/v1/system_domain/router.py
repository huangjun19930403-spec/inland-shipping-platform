"""一期系统域 API 聚合入口"""
from fastapi import APIRouter

from app.api.v1.auth.router import router as auth_router
from app.api.v1.system.router import router as user_router
from app.api.v1.audit.router import router as audit_router

router = APIRouter()

router.include_router(auth_router, prefix="/auth", tags=["系统-认证"]) 
router.include_router(user_router, prefix="", tags=["系统-用户权限"]) 
router.include_router(audit_router, prefix="/audit", tags=["系统-审核"]) 
