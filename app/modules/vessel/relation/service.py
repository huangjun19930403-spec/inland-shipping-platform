"""Owner, operator, contact, crew, controller, and affiliation workflows."""

from __future__ import annotations

from app.modules.vessel.ais.methods import VesselAisMixin
from app.modules.vessel.asset.profile_methods import VesselAssetMixin
from app.modules.vessel.compliance.methods import VesselComplianceMixin
from app.modules.vessel.recognition.methods import VesselRecognitionMixin
from app.modules.vessel.relation.methods import VesselRelationMixin
from app.modules.vessel.shared.methods import VesselCoreMixin


class VesselRelationService(
    VesselCoreMixin,
    VesselAssetMixin,
    VesselRelationMixin,
    VesselRecognitionMixin,
    VesselComplianceMixin,
    VesselAisMixin,
):
    """Owner, operator, contact, crew, controller, and affiliation workflows."""


__all__ = ["VesselRelationService"]
