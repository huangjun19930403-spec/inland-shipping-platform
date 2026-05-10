"""Aggregate base for vessel domain services."""

from __future__ import annotations

from app.modules.vessel.shared.methods import VesselCoreMixin
from app.modules.vessel.asset.methods import VesselAssetMixin
from app.modules.vessel.certificate.methods import VesselCertificateMixin
from app.modules.vessel.relation.methods import VesselRelationMixin
from app.modules.vessel.recognition.methods import VesselRecognitionMixin
from app.modules.vessel.quality.methods import VesselQualityMixin
from app.modules.vessel.compliance.methods import VesselComplianceMixin
from app.modules.vessel.ais.methods import VesselAisMixin
from app.modules.vessel.profile_card.methods import VesselProfileCardMixin


class VesselDomainService(
    VesselCoreMixin,
    VesselAssetMixin,
    VesselCertificateMixin,
    VesselRelationMixin,
    VesselRecognitionMixin,
    VesselQualityMixin,
    VesselComplianceMixin,
    VesselAisMixin,
    VesselProfileCardMixin,
):
    """Composed service implementation shared by domain entrypoints."""


__all__ = ["VesselDomainService"]
