"""Implementation methods for the vessel ais domain."""

from __future__ import annotations

from app.modules.vessel.ais.boundaries import VesselAisBoundaryMixin
from app.modules.vessel.ais.profile_queries import VesselAisProfileQueryMixin
from app.modules.vessel.ais.public_methods import VesselAisPublicMethodsMixin
from app.modules.vessel.ais.realtime_search import VesselAisRealtimeSearchMixin
from app.modules.vessel.ais.response_builders import VesselAisResponseBuilderMixin
from app.modules.vessel.ais.runtime_cache import VesselAisRuntimeCacheMixin
from app.modules.vessel.ais.snapshot_readers import VesselAisSnapshotReaderMixin
from app.modules.vessel.ais.common import _public_ais_error_message


class VesselAisMixin(
    VesselAisRuntimeCacheMixin,
    VesselAisPublicMethodsMixin,
    VesselAisSnapshotReaderMixin,
    VesselAisProfileQueryMixin,
    VesselAisRealtimeSearchMixin,
    VesselAisResponseBuilderMixin,
    VesselAisBoundaryMixin,
):
    """Implementation methods for the vessel AIS domain."""


__all__ = ["VesselAisMixin", "_public_ais_error_message"]
