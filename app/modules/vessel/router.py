"""Compatibility aggregate for vessel routers.

The full route table is mounted from ``routers`` to keep the public import path
stable while the module is split by domain.
"""

from __future__ import annotations

from app.modules.vessel.routers.all import router

__all__ = ["router"]
