"""Compatibility aggregate for legacy VesselService imports.

New route code should import the domain services from app.modules.vessel.<domain>.service.
"""

from __future__ import annotations

from app.modules.vessel.shared import base as _base
from app.modules.vessel.shared.aggregate import VesselDomainService

globals().update({name: getattr(_base, name) for name in dir(_base) if not name.startswith("__")})


class VesselService(VesselDomainService):
    """Backward-compatible aggregate over the split vessel domain services."""


__all__ = ["VesselService"]
