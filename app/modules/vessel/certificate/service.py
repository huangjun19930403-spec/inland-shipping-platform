"""Vessel certificate, crew certificate, and attachment workflows."""

from __future__ import annotations

from app.modules.vessel.ais.methods import VesselAisMixin
from app.modules.vessel.asset.profile_methods import VesselAssetMixin
from app.modules.vessel.certificate.methods import VesselCertificateMixin
from app.modules.vessel.compliance.methods import VesselComplianceMixin
from app.modules.vessel.recognition.methods import VesselRecognitionMixin
from app.modules.vessel.relation.methods import VesselRelationMixin
from app.modules.vessel.shared.methods import VesselCoreMixin


class VesselCertificateService(
    VesselCoreMixin,
    VesselAssetMixin,
    VesselCertificateMixin,
    VesselRelationMixin,
    VesselRecognitionMixin,
    VesselComplianceMixin,
    VesselAisMixin,
):
    """Vessel certificate, crew certificate, and attachment workflows."""


__all__ = ["VesselCertificateService"]
