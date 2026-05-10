"""Compatibility re-export for vessel schemas.

The concrete schema definitions live under ``schema_parts`` so future changes
can be moved into domain files without changing existing imports.
"""

from __future__ import annotations

from app.modules.vessel.schema_parts.all import *  # noqa: F401,F403
