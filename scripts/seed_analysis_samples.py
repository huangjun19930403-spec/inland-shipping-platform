"""数据分析模块本地验证 seed。

分析事实数据通过正式统计聚合服务生成，避免 seed 与真实任务口径分叉。
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.address import TransportNode
from app.models.analysis import (
    AnalysisBucketDefinition,
    AnalysisIndicatorDefinition,
    AnalysisJobDefinition,
    AnalysisJobRun,
    AnalysisSnapshot,
    FactFreightCityDaily,
    FactFreightCommodityDaily,
    FactFreightDaily,
    FactFreightFlowDaily,
    FactFreightPriceDaily,
    FactRegionDaily,
    FactShipCityDaily,
    FactShipDaily,
    FactShipFlowDaily,
)
from app.models.commodity import CommodityStandard
from app.models.freight import Freight
from app.models.ship import ShipProfile
from app.modules.analysis.job_catalog import ANALYSIS_JOB_SPEC_BY_CODE
from app.modules.analysis.statistics import AnalysisStatisticsService, seed_analysis_job_definitions


PRICE_BUCKETS = [
    ("PRICE_LT_20", "20元/吨以下", None, 20),
    ("PRICE_20_35", "20-35元/吨", 20, 35),
    ("PRICE_35_50", "35-50元/吨", 35, 50),
    ("PRICE_50_70", "50-70元/吨", 50, 70),
    ("PRICE_GT_70", "70元/吨以上", 70, None),
]

AGE_BUCKETS = [
    ("AGE_0_5", "0-5年", 0, 5),
    ("AGE_6_10", "6-10年", 6, 10),
    ("AGE_11_20", "11-20年", 11, 20),
    ("AGE_21_30", "21-30年", 21, 30),
    ("AGE_GT_30", "30年以上", 31, None),
]

DEADWEIGHT_BUCKETS = [
    ("DWT_LT_1000", "1000吨以下", 0, 1000),
    ("DWT_1000_3000", "1000-3000吨", 1000, 3000),
    ("DWT_3000_6000", "3000-6000吨", 3000, 6000),
    ("DWT_6000_10000", "6000-10000吨", 6000, 10000),
    ("DWT_GT_10000", "10000吨以上", 10000, None),
]

INDICATORS = [
    ("FREIGHT", "FREIGHT_COUNT", "货源量", "条", "LINE", "正式货源总量"),
    ("FREIGHT", "FREIGHT_TONNAGE", "货源吨位", "吨", "LINE", "正式货源估算吨位"),
    ("FREIGHT", "AVG_UNIT_PRICE", "平均运价", "元/吨", "LINE", "正式货源发布均价"),
    ("SHIP", "ACTIVE_SHIP_COUNT", "活跃船舶", "艘", "LINE", "按船舶档案和城市活动去重后的活跃船舶"),
    ("SHIP", "SHIP_TYPE_DISTRIBUTION", "船型分布", "艘", "PIE", "船舶主档船型结构"),
    ("REGION", "REGION_HEAT", "区域热力", "热度", "MAP", "城市事实按主区域汇总后的热力"),
    ("FLOW", "FREIGHT_FLOW", "货源流向", "条", "MAP", "正式货源起终点流向"),
    ("PRICE", "PRICE_BUCKET", "运价区间", "条", "BAR", "正式货源运价分布"),
]


def _status_name(status_code: str) -> str:
    return {
        "SUCCESS": "成功",
        "PARTIAL_SUCCESS": "部分成功",
        "FAILED": "失败",
    }.get(status_code, status_code)


async def _clear(session) -> None:
    for model in (
        AnalysisSnapshot,
        AnalysisJobRun,
        FactRegionDaily,
        FactShipFlowDaily,
        FactShipCityDaily,
        FactShipDaily,
        FactFreightPriceDaily,
        FactFreightCommodityDaily,
        FactFreightFlowDaily,
        FactFreightCityDaily,
        FactFreightDaily,
        AnalysisJobDefinition,
        AnalysisBucketDefinition,
        AnalysisIndicatorDefinition,
    ):
        await session.execute(delete(model))


async def _seed_definitions(session, now: datetime) -> None:
    for idx, (module, code, name, unit, chart, description) in enumerate(INDICATORS, start=1):
        session.add(
            AnalysisIndicatorDefinition(
                module_code=module,
                indicator_code=code,
                indicator_name=name,
                unit=unit,
                chart_type_code=chart,
                description=description,
                sort_order=idx,
                status=1,
                created_at=now,
                updated_at=now,
            )
        )
    sort = 1
    for group_code, buckets, unit in (
        ("FREIGHT_PRICE", PRICE_BUCKETS, "元/吨"),
        ("SHIP_AGE", AGE_BUCKETS, "年"),
        ("SHIP_DEADWEIGHT", DEADWEIGHT_BUCKETS, "吨"),
    ):
        for code, name, low, high in buckets:
            session.add(
                AnalysisBucketDefinition(
                    bucket_group_code=group_code,
                    bucket_code=code,
                    bucket_name=name,
                    min_value=low,
                    max_value=high,
                    unit=unit,
                    sort_order=sort,
                    status=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            sort += 1


async def _record_run(session, service: AnalysisStatisticsService, job_code: str, start: date, end: date, triggered_by: str) -> AnalysisJobRun:
    spec = ANALYSIS_JOB_SPEC_BY_CODE[job_code]
    now = datetime.utcnow()
    run = AnalysisJobRun(
        job_code=spec.job_code,
        job_name=spec.job_name,
        module_code=spec.module_code,
        module_name=spec.module_name,
        stat_date_from=start,
        stat_date_to=end,
        status_code="RUNNING",
        status_name="运行中",
        queued_at=now,
        started_at=now,
        parameters_json={"force_rebuild": True, "seed": True},
        triggered_by=triggered_by,
        created_at=now,
    )
    session.add(run)
    await session.flush()
    try:
        result = await service.run(job_code, start, end, force_rebuild=True)
        finished = datetime.utcnow()
        run.status_code = "SUCCESS"
        run.status_name = _status_name(run.status_code)
        run.finished_at = finished
        run.duration_ms = int((finished - now).total_seconds() * 1000)
        run.input_rows = result.input_rows
        run.output_rows = result.output_rows
        run.affected_rows = result.affected_rows
        run.result_summary_json = result.as_summary()
        definition = await session.scalar(select(AnalysisJobDefinition).where(AnalysisJobDefinition.job_code == job_code))
        if definition is not None:
            definition.last_run_id = run.id
            definition.last_status_code = run.status_code
            definition.last_finished_at = run.finished_at
            definition.last_result_summary_json = run.result_summary_json
            definition.updated_at = finished
    except Exception as exc:
        finished = datetime.utcnow()
        run.status_code = "FAILED"
        run.status_name = _status_name(run.status_code)
        run.finished_at = finished
        run.duration_ms = int((finished - now).total_seconds() * 1000)
        run.error_message = str(exc)[:4000]
        raise
    return run


async def seed_analysis_samples() -> None:
    async with AsyncSessionLocal() as session:
        freight_count = int(await session.scalar(select(Freight.id).limit(1)) is not None)
        ship_count = int(await session.scalar(select(ShipProfile.id).limit(1)) is not None)
        node_count = int(await session.scalar(select(TransportNode.id).limit(1)) is not None)
        commodity_count = int(await session.scalar(select(CommodityStandard.id).limit(1)) is not None)
        if not all((freight_count, ship_count, node_count, commodity_count)):
            raise RuntimeError("seed_analysis_samples requires foundation, ship and freight sample data")

        await _clear(session)
        now = datetime.utcnow()
        await _seed_definitions(session, now)
        await seed_analysis_job_definitions(session)

        service = AnalysisStatisticsService(session)
        start = date.today() - timedelta(days=89)
        end = date.today()
        week_start = date.today() - timedelta(days=6)
        run_codes = [
            "ANALYSIS_FREIGHT_DAILY",
            "ANALYSIS_FREIGHT_FLOW_DAILY",
            "ANALYSIS_FREIGHT_COMMODITY_DAILY",
            "ANALYSIS_FREIGHT_PRICE_DAILY",
            "ANALYSIS_FREIGHT_CITY_DAILY",
            "ANALYSIS_SHIP_DAILY",
            "ANALYSIS_SHIP_CITY_DAILY",
            "ANALYSIS_SHIP_FLOW_DAILY",
            "ANALYSIS_REGION_DAILY",
            "ANALYSIS_ALL_DAILY",
            "ANALYSIS_FREIGHT_DAILY",
            "ANALYSIS_FREIGHT_FLOW_DAILY",
            "ANALYSIS_FREIGHT_COMMODITY_DAILY",
            "ANALYSIS_FREIGHT_PRICE_DAILY",
            "ANALYSIS_FREIGHT_CITY_DAILY",
        ]
        for idx, code in enumerate(run_codes):
            scope_start = week_start if idx >= 10 else start
            await _record_run(session, service, code, scope_start, end, "system_seed")

        latest_runs = (
            await session.execute(
                select(AnalysisJobRun)
                .where(AnalysisJobRun.status_code == "SUCCESS")
                .order_by(AnalysisJobRun.id.asc())
                .limit(5)
            )
        ).scalars().all()
        for idx, run in enumerate(latest_runs, start=1):
            session.add(
                AnalysisSnapshot(
                    snapshot_code=f"ANALYSIS-SEED-SNAPSHOT-{idx:02d}",
                    module_code=run.module_code,
                    snapshot_name=f"{run.module_name}本地验证快照",
                    stat_date_from=start,
                    stat_date_to=end,
                    payload_json={"status": "seeded", "job_code": run.job_code, "range_days": 90},
                    generated_by_job_id=run.id,
                    generated_at=run.finished_at or now,
                )
            )

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_analysis_samples())
