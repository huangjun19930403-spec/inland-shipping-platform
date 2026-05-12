# Round 07 Report - Map Four-State Contract

## Scope

本轮把航线地图失败态从“空白或提示文案”提升为后端契约，并拆出报价航线服务的第一块独立 service。没有新增机会落表，避免在状态机尚未闭合前制造壳表。

## Changes

1. 新增 `AnalysisMapStateBlock`。
   - 统一 `READY / PENDING / FAILED / NOT_COMPUTABLE`。
   - 返回 `provider_code`、`cache_status`、`last_updated_at`、`error_reason`、`missing_fields`、`not_computable_reasons`、`retry_action`、`business_impact`。
   - AMMS/HiFleet 内部实现不再向前端暴露 HiFleet 文案。

2. 新增 `app/modules/analysis/map_state.py`。
   - 负责 provider 文案归一、缺失字段推断、默认重试动作和业务影响说明。
   - 避免每个分析接口自己拼失败态。

3. 拆出 `QuoteRouteEstimateService`。
   - 从 `analysis/service.py` 移入 `app/modules/analysis/quote_route_service.py`。
   - 报价航线响应现在带 `map_state`。
   - 成功状态的 `geometry_source` 对外统一为 `AMMS`。

4. 流向地图接入 `map_state`。
   - 坐标缺失、坐标相同、缓存未命中、AMMS 未配置、AMMS 返回空轨迹、真实轨迹生成成功都返回明确状态。
   - 生产口径继续禁止用直线或样例轨迹冒充真实航线。

5. 测试补强。
   - 报价航线覆盖 READY、NOT_COMPUTABLE、FAILED 的 map state。
   - 流向地图覆盖 READY、PENDING、NOT_COMPUTABLE。

## Deletion Boundary

- `/freight` 旧列表接口本轮未删除，因为后端仍保留为内部资源接口候选。
- 前端普通业务消费已在前端第七轮迁走，下一轮后端可以开始删除旧列表响应中的展示冗余字段，或把接口降级为维护资源接口。

## Quality Check

- `app/modules/analysis/quote_route_service.py`：223 行。
- `app/modules/analysis/map_state.py`：103 行。
- `app/modules/analysis/service.py`：1887 行。

`analysis/service.py` 已低于上一轮的 1927 行，但仍是遗留超大对象，不满足最终质量目标。下一轮必须继续拆 `AnalysisDashboardService` 的货源、运力、区域流向、价格分析块。

## Verification

- `.venv/bin/python -m py_compile app/modules/analysis/map_state.py app/modules/analysis/quote_route_service.py app/modules/analysis/service.py app/modules/analysis/schemas.py`
- `.venv/bin/python -m pytest tests/test_analysis_quote_route_estimate.py tests/test_shipping_opportunity_service.py`

结果：10 个测试通过，存在既有 `datetime.utcnow()` 警告。
