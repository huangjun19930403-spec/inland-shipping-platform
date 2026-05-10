"""Relation-domain service boundary for vessel routes."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.vessel.service import VesselService


class VesselRelationService:
    """Explicit facade for subject relations, evidence, conclusions, and transfers."""

    def __init__(self, db: AsyncSession):
        self._facade = VesselService(db)


def _delegate(name: str) -> Callable[..., Awaitable[Any]]:
    async def method(self: VesselRelationService, *args: Any, **kwargs: Any) -> Any:
        return await getattr(self._facade, name)(*args, **kwargs)

    method.__name__ = name
    return method


for _method_name in (
    "list_controller_evidence",
    "create_controller_evidence",
    "update_controller_evidence",
    "void_controller_evidence",
    "list_affiliation_evidence",
    "create_affiliation_evidence",
    "update_affiliation_evidence",
    "void_affiliation_evidence",
    "list_relation_conclusions",
    "rebuild_relation_conclusion_candidates",
    "confirm_controller_conclusion",
    "confirm_affiliation_conclusion",
    "void_controller_conclusion",
    "void_affiliation_conclusion",
    "upload_relation_evidence_attachment",
    "void_relation_evidence_attachment",
    "resolve_relation_conclusion_conflict",
    "list_owners",
    "create_owner",
    "update_owner",
    "end_owner",
    "void_owner",
    "set_primary_owner",
    "replace_owners",
    "upload_owner_document",
    "list_operators",
    "create_operator",
    "update_operator",
    "end_operator",
    "void_operator",
    "set_primary_operator",
    "replace_operators",
    "list_contacts",
    "create_contact",
    "update_contact",
    "end_contact",
    "void_contact",
    "set_primary_contact",
    "replace_contacts",
    "list_crew",
    "create_crew",
    "update_crew",
    "end_crew",
    "void_crew",
    "replace_crew",
    "void_owner_document",
    "owner_transfer",
    "get_change_events",
):
    setattr(VesselRelationService, _method_name, _delegate(_method_name))
