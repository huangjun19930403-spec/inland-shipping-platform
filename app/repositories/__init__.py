"""Repository层 — 数据访问层"""
from app.repositories.base import BaseRepository
from app.repositories.cargo_repository import CargoRepository
from app.repositories.address_repository import AddressRepository
from app.repositories.vessel_repository import VesselRepository
from app.repositories.route_repository import RouteRepository
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.audit_repository import AuditRepository
from app.repositories.system_repository import SystemRepository

__all__ = [
    "BaseRepository",
    "CargoRepository",
    "AddressRepository",
    "VesselRepository",
    "RouteRepository",
    "AnalysisRepository",
    "AuditRepository",
    "SystemRepository",
]
