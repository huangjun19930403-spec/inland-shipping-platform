"""分析统计任务定义目录。"""

from __future__ import annotations

from dataclasses import dataclass, field


MODULE_NAMES = {
    "FREIGHT": "货源分析",
    "SHIP": "船舶指标分析",
    "VESSEL_FACT": "船舶事实分析",
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
        ["freight", "freight_candidate", "freight_batch_task", "freight_tms_inbound"],
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
        "ANALYSIS_FREIGHT_NODE_DAILY",
        "货源节点热力日汇总",
        "FREIGHT",
        "按正式货源装卸节点生成节点级货源热力。",
        ["freight", "transport_node", "region_city_relation"],
        ["fact_freight_node_daily"],
        55,
    ),
    AnalysisJobSpec(
        "ANALYSIS_SHIP_DAILY",
        "船舶结构日汇总",
        "SHIP",
        "按船舶档案、运力和运营状态生成船型、船龄、载重吨结构。",
        ["vessel_profile", "vessel_capacity_dimension", "vessel_operator_period"],
        ["fact_ship_daily"],
        60,
    ),
    AnalysisJobSpec(
        "ANALYSIS_SHIP_CITY_DAILY",
        "船舶城市热力日汇总",
        "SHIP",
        "按船舶活动城市生成活跃船舶热力；本地无 ES 时使用确定性样例源。",
        ["vessel_profile", "vessel_capacity_dimension", "ES_HISTORY"],
        ["fact_ship_city_daily"],
        70,
    ),
    AnalysisJobSpec(
        "ANALYSIS_SHIP_FLOW_DAILY",
        "船舶流向日汇总",
        "FLOW",
        "按同一 MMSI 城市迁移序列生成船舶城市流向；本地无 ES 时使用确定性样例源。",
        ["vessel_profile", "vessel_capacity_dimension", "ES_HISTORY"],
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
        "ANALYSIS_VESSEL_ASSET_DAILY",
        "船舶资产事实日汇总",
        "VESSEL_FACT",
        "从船舶摘要、质量和风险字段生成可解释的资产事实。",
        ["vessel_profile_summary"],
        ["fact_vessel_asset_daily"],
        110,
    ),
    AnalysisJobSpec(
        "ANALYSIS_VESSEL_AIS_FRESHNESS_DAILY",
        "船舶 AIS 新鲜度事实日汇总",
        "VESSEL_FACT",
        "从 AIS 快照和最新位置快照生成新鲜度、匹配状态和覆盖率事实。",
        ["vessel_ais_snapshot", "vessel_latest_position_snapshot", "vessel_ais_city_snapshot_item"],
        ["fact_vessel_ais_freshness_daily"],
        120,
    ),
    AnalysisJobSpec(
        "ANALYSIS_VESSEL_TRAJECTORY_DAILY",
        "船舶轨迹事实日汇总",
        "VESSEL_FACT",
        "从空间航段匹配样本生成轨迹覆盖、断点和航段匹配事实；历史 AIS 缺失时输出不可计算。",
        ["vessel_route_segment_match_sample"],
        ["fact_vessel_trajectory_daily"],
        130,
    ),
    AnalysisJobSpec(
        "ANALYSIS_VESSEL_NODE_DAILY",
        "船舶节点观测事实日汇总",
        "VESSEL_FACT",
        "复用节点空间观测快照生成节点周边活跃、停靠、经过和低可信事实。",
        ["vessel_spatial_observation_snapshot", "vessel_node_observation_item", "vessel_node_observation_vessel"],
        ["fact_vessel_node_daily"],
        140,
    ),
    AnalysisJobSpec(
        "ANALYSIS_VESSEL_ROUTE_SEGMENT_DAILY",
        "船舶航段观测事实日汇总",
        "VESSEL_FACT",
        "复用航段空间观测快照生成航段匹配、覆盖、方向一致性和缺口事实。",
        ["vessel_spatial_observation_snapshot", "vessel_route_segment_observation_item", "vessel_route_segment_match_sample"],
        ["fact_vessel_route_segment_daily"],
        150,
    ),
    AnalysisJobSpec(
        "ANALYSIS_VESSEL_QUALITY_DAILY",
        "船舶质量事实日汇总",
        "VESSEL_FACT",
        "按质量问题类型、严重级别和状态生成新增、关闭和关闭时长事实。",
        ["vessel_data_quality_issue"],
        ["fact_vessel_quality_daily"],
        160,
    ),
    AnalysisJobSpec(
        "ANALYSIS_VESSEL_RISK_DAILY",
        "船舶风险事实日汇总",
        "VESSEL_FACT",
        "按风险类型、等级和状态生成风险趋势事实，UNKNOWN 风险单列。",
        ["vessel_risk_signal"],
        ["fact_vessel_risk_daily"],
        170,
    ),
    AnalysisJobSpec(
        "ANALYSIS_CANDIDATE_FIT_DAILY",
        "候选适配事实日汇总",
        "VESSEL_FACT",
        "从候选适配分析、候选明细和人工标注生成候选复盘事实。",
        ["vessel_candidate_analysis", "vessel_candidate_analysis_item", "vessel_candidate_analysis_annotation"],
        ["fact_candidate_fit_daily"],
        180,
    ),
    AnalysisJobSpec(
        "ANALYSIS_REGION_SUPPLY_DEMAND_DAILY",
        "区域供需分层事实日汇总",
        "REGION",
        "从标准货源样本、AIS 供给和可信档案样本生成区域供需分层事实。",
        ["fact_freight_city_daily", "fact_vessel_ais_freshness_daily", "fact_vessel_asset_daily"],
        ["fact_region_supply_demand_daily"],
        190,
    ),
    AnalysisJobSpec(
        "ANALYSIS_ALL_DAILY",
        "全量分析日汇总",
        "SYSTEM",
        "编排所有日统计任务，用于定时调度、一键补算和船舶事实闭环。",
        ["freight", "vessel_profile", "vessel_capacity_dimension", "vessel_profile_summary", "vessel_ais_snapshot", "vessel_spatial_observation_snapshot"],
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
            "fact_vessel_asset_daily",
            "fact_vessel_ais_freshness_daily",
            "fact_vessel_trajectory_daily",
            "fact_vessel_node_daily",
            "fact_vessel_route_segment_daily",
            "fact_vessel_quality_daily",
            "fact_vessel_risk_daily",
            "fact_candidate_fit_daily",
            "fact_region_supply_demand_daily",
        ],
        200,
        schedule_cron="20 2 * * *",
        schedule_enabled=True,
    ),
]

ANALYSIS_JOB_SPEC_BY_CODE = {item.job_code: item for item in ANALYSIS_JOB_SPECS}
