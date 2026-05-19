"""货源 AI 解析流水线边界。

`FreightBatchTaskService.run_parse_now` 仍承载当前流水线实现；该模块为后续把
AI 编排、证据门控、主数据匹配和候选生成迁出 service.py 预留稳定入口。
"""

from app.modules.freight.legacy_service import FreightBatchTaskService

FreightWechatParserPipeline = FreightBatchTaskService

__all__ = ["FreightWechatParserPipeline"]
