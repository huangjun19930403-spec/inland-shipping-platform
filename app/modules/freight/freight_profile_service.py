"""正式货源档案服务边界。"""

from app.modules.freight.service import (
    FreightAttachmentService,
    FreightContactService,
    FreightService,
    FreightTagService,
)

__all__ = [
    "FreightAttachmentService",
    "FreightContactService",
    "FreightService",
    "FreightTagService",
]
