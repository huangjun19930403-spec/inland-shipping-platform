from app.models.address import (  # noqa
    Waterway, Region, AdminRegion, NodeType, TransportNode, NodeAlias, RegionAddressRelation
)
from app.models.cargo import (  # noqa
    CommodityCategory, CommodityType, CommodityStandard, CommodityAlias,
    CargoRawMessage, CargoAiParseResult, CargoFreight, TmsCargoRaw
)
from app.models.analysis import (  # noqa
    CargoCityHeatmap, CargoStatDaily, CargoCommodityStatDaily,
    CargoOdDaily, CargoChannelDaily,
    ShipStatRegion, ShipStatCity, ShipStatDwt, ShipStatAge,
)
from app.models.vessel import (  # noqa
    VesselTypeDict, Vessel, VesselNameHistory, VesselAisHistory, VesselDynamic
)
from app.models.route import ShippingRoute, ShippingRoutePath, ShippingRoutePathNode  # noqa
from app.models.system import SysUser, SysRole, SysUserRole  # noqa
from app.models.audit import AuditRecord  # noqa
