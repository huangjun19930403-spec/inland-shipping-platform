"""
FastAPI依赖注入中心
集中管理所有可注入依赖，避免依赖关系散落各处
"""
from typing import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.repositories.ai_repository import AiRepository
from app.repositories.cargo_repository import CargoRepository
from app.repositories.address_repository import AddressRepository
from app.repositories.vessel_repository import VesselRepository
from app.repositories.route_repository import RouteRepository
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.audit_repository import AuditRepository
from app.services.cargo_service import CargoService
from app.services.address_service import AddressService
from app.services.vessel_service import VesselService
from app.services.route_service import RouteService
from app.services.analysis_service import AnalysisService
from app.services.audit_service import AuditService


# ─────────────────────────────────────────────────
# 数据库Session依赖
# ─────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """提供异步数据库Session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# ─────────────────────────────────────────────────
# Repository依赖
# ─────────────────────────────────────────────────

async def get_cargo_repo(
    db: AsyncSession = Depends(get_db),
) -> CargoRepository:
    return CargoRepository(db)


async def get_address_repo(
    db: AsyncSession = Depends(get_db),
) -> AddressRepository:
    return AddressRepository(db)


async def get_vessel_repo(
    db: AsyncSession = Depends(get_db),
) -> VesselRepository:
    return VesselRepository(db)


async def get_route_repo(
    db: AsyncSession = Depends(get_db),
) -> RouteRepository:
    return RouteRepository(db)


async def get_analysis_repo(
    db: AsyncSession = Depends(get_db),
) -> AnalysisRepository:
    return AnalysisRepository(db)


async def get_audit_repo(
    db: AsyncSession = Depends(get_db),
) -> AuditRepository:
    return AuditRepository(db)


# ─────────────────────────────────────────────────
# Service依赖
# ─────────────────────────────────────────────────

async def get_audit_service(
    audit_repo: AuditRepository = Depends(get_audit_repo),
) -> AuditService:
    return AuditService(audit_repo=audit_repo)


async def get_ai_repo(
    db: AsyncSession = Depends(get_db),
) -> AiRepository:
    return AiRepository(db)


async def get_cargo_service(
    db: AsyncSession = Depends(get_db),
) -> CargoService:
    # 显式共享同一 Session，确保业务写入与审核写入在同一事务内提交
    return CargoService(
        cargo_repo=CargoRepository(db),
        address_repo=AddressRepository(db),
        audit_svc=AuditService(audit_repo=AuditRepository(db)),
        ai_repo=AiRepository(db),
    )


async def get_address_service(
    db: AsyncSession = Depends(get_db),
) -> AddressService:
    # 显式共享同一 Session，确保业务写入与审核写入在同一事务内提交
    return AddressService(
        address_repo=AddressRepository(db),
        audit_svc=AuditService(audit_repo=AuditRepository(db)),
    )


async def get_vessel_service(
    db: AsyncSession = Depends(get_db),
) -> VesselService:
    # 显式共享同一 Session，确保业务写入与审核写入在同一事务内提交
    return VesselService(
        vessel_repo=VesselRepository(db),
        audit_svc=AuditService(audit_repo=AuditRepository(db)),
    )


async def get_route_service(
    route_repo: RouteRepository = Depends(get_route_repo),
) -> RouteService:
    return RouteService(route_repo=route_repo)


async def get_analysis_service(
    analysis_repo: AnalysisRepository = Depends(get_analysis_repo),
) -> AnalysisService:
    """AnalysisService 只依赖 AnalysisRepository（只读统计表）"""
    return AnalysisService(analysis_repo=analysis_repo)


