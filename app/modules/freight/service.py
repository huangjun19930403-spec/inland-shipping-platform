"""Compatibility facade for freight domain services.

New production code should import from the explicit domain modules:
`batch_service`, `tms_service`, `candidate_service`, `normalization_service`,
`freight_profile_service`, `opportunity_service`, or `parser_pipeline`.
This module remains for older tests, scripts, and third-party imports.
"""

from __future__ import annotations

import sys
from types import ModuleType

from app.modules.freight import legacy_service as _legacy

globals().update({name: getattr(_legacy, name) for name in dir(_legacy) if not name.startswith("__")})

__all__ = [name for name in globals() if not name.startswith("__")]


class _FreightServiceFacade(ModuleType):
    def __getattr__(self, name: str):
        return getattr(_legacy, name)

    def __setattr__(self, name: str, value) -> None:
        if not name.startswith("__"):
            setattr(_legacy, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _FreightServiceFacade
