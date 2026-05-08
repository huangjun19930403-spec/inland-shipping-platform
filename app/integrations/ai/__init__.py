"""AI integration clients."""

from app.integrations.ai.dashscope_qwen_client import DashScopeQwenFreightParserClient
from app.integrations.ai.vessel_image_assistant import VesselCertificateImageAssistant

__all__ = ["DashScopeQwenFreightParserClient", "VesselCertificateImageAssistant"]
