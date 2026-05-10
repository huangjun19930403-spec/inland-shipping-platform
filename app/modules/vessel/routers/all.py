"""Compatibility aggregate for vessel domain routers."""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.vessel.routers.quality import router as quality_router
from app.modules.vessel.routers.governance import router as governance_router
from app.modules.vessel.routers.compliance import router as compliance_router
from app.modules.vessel.routers.recognition import router as recognition_router
from app.modules.vessel.routers.ais import router as ais_router
from app.modules.vessel.routers.candidate import router as candidate_router
from app.modules.vessel.routers.asset import router as asset_router
from app.modules.vessel.routers.relation import router as relation_router

router = APIRouter()

for domain_router in (
    quality_router,
    governance_router,
    compliance_router,
    recognition_router,
    ais_router,
    candidate_router,
    asset_router,
    relation_router,
):
    router.routes.extend(domain_router.routes)
