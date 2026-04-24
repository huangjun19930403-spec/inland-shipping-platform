"""统一状态枚举定义。"""
from enum import Enum, IntEnum


class AuditStatus(IntEnum):
    """审核状态。"""

    PENDING = 0
    APPROVED = 1
    REJECTED = 2


class RegionStatus(IntEnum):
    """商业区域业务状态。"""

    INACTIVE = 0
    ACTIVE = 1


class TransportNodeLifecycleStatus(IntEnum):
    """运输节点生命周期状态。"""

    INACTIVE = 0
    OPERATING = 1
    CONSTRUCTING = 2
    RETIRED = 3


class ShippingRouteStatus(str, Enum):
    """航线业务状态。"""

    PLANNING = "PLANNING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ShippingRoutePlanStatus(str, Enum):
    """航线路径方案状态。"""

    DRAFT = "DRAFT"
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    RETIRED = "RETIRED"


class RouteGeometryStatus(str, Enum):
    """路径段轨迹生成状态。"""

    PENDING = "pending"
    READY = "ready"
    FALLBACK = "fallback"
    FAILED = "failed"


class RouteGeometrySource(str, Enum):
    """路径段轨迹来源。"""

    MANUAL = "manual"
    MOCK = "mock"
    AMAP = "amap"
    HIFLEET = "hifleet"
    FALLBACK = "fallback"


class AiPromptOptimizationResultStatus(str, Enum):
    """Prompt 优化结果状态。"""

    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    ROLLED_BACK = "ROLLED_BACK"


class AiPromptOptimizationEvaluationStatus(str, Enum):
    """Prompt 优化结果评估状态。"""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    EVALUATED = "EVALUATED"
    FAILED = "FAILED"


class AiPromptFeedbackIssueType(str, Enum):
    """Prompt 反馈问题类型。"""

    SPLIT_ERROR = "split_error"
    EXTRACT_ERROR = "extract_error"
    MATCH_ERROR = "match_error"
    INVALID_MESSAGE = "invalid_message"
    WEAK_CONFIDENCE = "weak_confidence"
    CONFIRMED_GOOD = "confirmed_good"


class AiRuntimeTaskType(str, Enum):
    """运行时策略支持的任务类型。"""

    FREIGHT_CONTEXT_SEGMENTATION = "freight_context_segmentation"
    FREIGHT_CLUE_EXTRACTION = "freight_clue_extraction"
    FREIGHT_CANDIDATE_ASSEMBLE = "freight_candidate_assemble"
    FREIGHT_QUALITY_JUDGE = "freight_quality_judge"
    PROMPT_OPTIMIZE = "prompt_optimize"
    PROMPT_OPTIMIZATION_EVALUATE = "prompt_optimization_evaluate"


class FreightSourceType(str, Enum):
    """Freight source types."""

    MANUAL_PASTE = "MANUAL_PASTE"
    MANUAL_FORM = "MANUAL_FORM"
    TMS = "TMS"
    API_PUSH = "API_PUSH"


class FreightBusinessStatus(str, Enum):
    """Freight business lifecycle status."""

    DRAFT = "DRAFT"
    OPEN = "OPEN"
    MATCHED = "MATCHED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"
    INVALID = "INVALID"


class FreightConfirmStatus(str, Enum):
    """Freight confirmation status."""

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class FreightMatchLevel(str, Enum):
    """Freight standardization match level."""

    EXACT = "EXACT"
    CITY = "CITY"
    FUZZY = "FUZZY"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    UNMATCHED = "UNMATCHED"


class FreightWorkflowType(str, Enum):
    """Freight workflow types."""

    BATCH_PASTE_STANDARDIZE = "BATCH_PASTE_STANDARDIZE"
    TMS_INBOUND_STANDARDIZE = "TMS_INBOUND_STANDARDIZE"
    CANDIDATE_CONFIRM = "CANDIDATE_CONFIRM"
    QUALITY_REVIEW = "QUALITY_REVIEW"


class FreightTaskStatus(str, Enum):
    """Generic freight task status."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class FreightStepStatus(str, Enum):
    """Freight workflow step status."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class FreightProcessorType(str, Enum):
    """Processor type for freight workflow steps."""

    SKILL = "SKILL"
    TOOL = "TOOL"
    SYSTEM = "SYSTEM"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class FreightManualFeedbackType(str, Enum):
    """Manual feedback types for candidate correction."""

    FIELD_CORRECTION = "FIELD_CORRECTION"
    REJECT = "REJECT"
    STATUS_ADJUST = "STATUS_ADJUST"
    QUALITY_OVERRIDE = "QUALITY_OVERRIDE"


class AiPromptOptimizationTaskStatus(str, Enum):
    """Prompt optimization task status."""

    DRAFT = "DRAFT"
    RUNNING = "RUNNING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
