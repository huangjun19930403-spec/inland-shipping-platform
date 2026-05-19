"""微信货源批次服务边界。

当前阶段先作为兼容入口承接 router/import，后续可把批次状态与解析流水线代码从
legacy service 中逐步搬迁到这里。
"""

from app.modules.freight.legacy_service import FreightBatchTaskService

__all__ = ["FreightBatchTaskService"]
