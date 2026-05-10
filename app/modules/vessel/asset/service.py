"""Asset ledger, base profile, and summary workflows."""

from __future__ import annotations

from app.modules.vessel.ais.methods import VesselAisMixin
from app.modules.vessel.asset.methods import VesselAssetMixin
from app.modules.vessel.certificate.methods import VesselCertificateMixin
from app.modules.vessel.compliance.methods import VesselComplianceMixin
from app.modules.vessel.quality.methods import VesselQualityMixin
from app.modules.vessel.relation.methods import VesselRelationMixin
from app.modules.vessel.shared.methods import VesselCoreMixin


class VesselAssetService(
    VesselCoreMixin,
    VesselAssetMixin,
    VesselCertificateMixin,
    VesselRelationMixin,
    VesselQualityMixin,
    VesselComplianceMixin,
    VesselAisMixin,
):
    """Asset ledger, base profile, and summary workflows."""


__all__ = ["VesselAssetService"]
