"""分析统计任务定义目录。"""

from __future__ import annotations

from dataclasses import dataclass, field


MODULE_NAMES = {
    "FREIGHT": "货源分析",
    "SHIP": "船舶分析",
    "REGION": "区域分析",
    "FLOW": "流向分析",
    "PRICE": "运价分析",
    "SYSTEM": "综合分析",
}


@dataclass(frozen=True)
class AnalysisJobSpec:
    job_code: str
    job_name: str
    module_code: str
    description: str
    source_tables: list[str]
    target_tables: list[str]
    sort_order: int
    default_parameters: dict = field(default_factory=dict)
    schedule_cron: str | None = None
    schedule_enabled: bool = False

    @property
    def module_name(self) -> str:
        return MODULE_NAMES.get(self.module_code, self.module_code)


ANALYSIS_JOB_SPECS: list[AnalysisJobSpec] = [
    AnalysisJobSpec(
        "ANALYSIS_FREIGHT_DAILY",
        "货源日汇总",
        "FREIGHT",
        "按正式货源生成每日货源量、确认量、候选量、吨位和均价。",
        ["freight", "freight_candidate", "freight_source_inbound"],
        ["fact_freight_daily"],
        10,
    ),
    AnalysisJobSpec(
        "ANALYSIS_FREIGHT_FLOW_DAILY",
        "货源流向日汇总",
        "FLOW",
        "按正式货源起终点节点和城市生成货源流向。",
        ["freight", "transport_node", "commodity_standard"],
        ["fact_freight_flow_daily"],
        20,
    ),
    AnalysisJobSpec(
        "ANALYSIS_FREIGHT_COMMODITY_DAILY",
        "货品结构日汇总",
        "FREIGHT",
        "按标准货品、货品类型、货品大类生成货源结构。",
        ["freight", "commodity_standard", "commodity_type", "commodity_category"],
        ["fact_freight_commodity_daily"],
        30,
    ),
    AnalysisJobSpec(
        "ANALYSIS_FREIGHT_PRICE_DAILY",
        "运价区间日汇总",
        "PRICE",
        "按正式货源单价和价格桶生成运价分布。",
        ["freight", "analysis_bucket_definition"],
        ["fact_freight_price_daily"],
        40,
    ),
    AnalysisJobSpec(
        "ANALYSIS_FREIGHT_CITY_DAILY",
        "货源城市热力日汇总",
        "REGION",
        "按正式货源装卸城市生成城市热力，并为区域汇总提供底层事实。",
        ["freight", "admin_region", "region_city_relation"],
        ["fact_freight_city_daily"],
        50,
    ),
    AnalysisJobSpec(
        "ANALYSIS_SHIP_DAILY",
        "船舶结构日汇总",
        "SHIP",
        "按船舶档案、运力和运营状态生成船型、船龄、载重吨结构。",
        ["ship_profile", "ship_capacity", "ship_operation"],
        ["fact_ship_daily"],
        60,
    ),
    AnalysisJobSpec(
        "ANALYSIS_SHIP_CITY_DAILY",
        "船舶城市热力日汇总",
        "SHIP",
        "按船舶活动城市生成活跃船舶热力；本地无 ES 时使用确定性样例源。",
        ["ship_profile", "ship_capacity", "ship_dynamic", "ES_HISTORY"],
        ["fact_ship_city_daily"],
        70,
    ),
    AnalysisJobSpec(
        "ANALYSIS_SHIP_FLOW_DAILY",
        "船舶流向日汇总",
        "FLOW",
        "按同一 MMSI 城市迁移序列生成船舶城市流向；本地无 ES 时使用确定性样例源。",
        ["ship_profile", "ship_capacity", "ship_dynamic", "ES_HISTORY"],
        ["fact_ship_flow_daily"],
        80,
    ),
    AnalysisJobSpec(
        "ANALYSIS_REGION_DAILY",
        "区域日汇总",
        "REGION",
        "从城市货源和城市船舶热力按城市主区域汇总，不直接用区域 polygon 重算。",
        ["fact_freight_city_daily", "fact_ship_city_daily", "region_city_relation"],
        ["fact_region_daily"],
        90,
    ),
    AnalysisJobSpec(
        "ANALYSIS_ALL_DAILY",
        "全量分析日汇总",
        "SYSTEM",
        "编排所有日统计任务，用于定时调度和一键补算。",
        ["freight", "ship_profile", "ship_capacity", "ship_dynamic", "ES_HISTORY"],
        [
            "fact_freight_daily",
            "fact_freight_flow_daily",
            "fact_freight_commodity_daily",
            "fact_freight_price_daily",
            "fact_freight_city_daily",
            "fact_ship_daily",
            "fact_ship_city_daily",
            "fact_ship_flow_daily",
            "fact_region_daily",
        ],
        100,
        schedule_cron="20 2 * * *",
        schedule_enabled=True,
    ),
]

ANALYSIS_JOB_SPEC_BY_CODE = {item.job_code: item for item in ANALYSIS_JOB_SPECS}
