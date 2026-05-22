"""OCR recognition queues, field diffs, and adoption workflows."""

from __future__ import annotations

from app.modules.vessel.ais.methods import VesselAisMixin
from app.modules.vessel.asset.profile_methods import VesselAssetMixin
from app.modules.vessel.certificate.methods import VesselCertificateMixin
from app.modules.vessel.compliance.methods import VesselComplianceMixin
from app.modules.vessel.quality.methods import VesselQualityMixin
from app.modules.vessel.recognition.methods import VesselRecognitionMixin
from app.modules.vessel.relation.methods import VesselRelationMixin
from app.modules.vessel.shared.methods import VesselCoreMixin


class VesselRecognitionService(
    VesselCoreMixin,
    VesselAssetMixin,
    VesselCertificateMixin,
    VesselRelationMixin,
    VesselRecognitionMixin,
    VesselQualityMixin,
    VesselComplianceMixin,
    VesselAisMixin,
):
    """OCR recognition queues, field diffs, and adoption workflows."""


__all__ = ["VesselRecognitionService"]
