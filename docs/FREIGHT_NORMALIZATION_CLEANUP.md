# 货源原文级数据清洗说明

日期：2026-05-07

## 背景

正式货源允许以原文级装卸地和原文级货品入库。这样可以避免业务因为平台暂未维护运输节点、城市或标准货品而无法确认货源，但原文级数据不能直接进入城市、节点、标准货品和流向维度分析。

清洗任务的目标是：在后续新增节点、城市、货品后，把已有原文级货源提升为标准维度。

## 数据范围

清洗任务扫描 `freight` 中满足以下任一条件的数据：

- `origin_match_level_code = RAW` 或装货城市为空。
- `destination_match_level_code = RAW` 或卸货城市为空。
- `commodity_match_level_code = RAW` 或标准货品为空。

总量统计仍包含这些货源；维度分析只消费已标准化字段。

## 建议表

`freight_normalization_task` 保存每次清洗任务：

- `task_no`：清洗任务号。
- `celery_task_id`：Celery 后台任务 ID，便于在 worker 日志中追踪。
- `status_code`：`QUEUED`、`RUNNING`、`SUCCESS`、`PARTIAL_SUCCESS`、`FAILED`。
- `stage_code`、`stage_name`、`stage_message`、`progress_percent`：前端展示真实进度。
- `scanned_count`、`suggestion_count`、`auto_applied_count`、`pending_count`、`failed_count`：任务结果统计。

`freight_normalization_suggestion` 保存每条建议：

- `clean_task_id`：来源清洗任务。
- `suggestion_type_code`：`ORIGIN`、`DESTINATION`、`COMMODITY`。
- `raw_text`：待清洗原文。
- `suggested_level_code`：建议提升到 `NODE`、`CITY` 或 `STANDARD`。
- `confidence_score`：匹配置信度。
- `status_code`：`PENDING`、`APPLIED`、`AUTO_APPLIED`、`REJECTED`。
- `before_json`、`after_json`：应用前后快照。

## 执行方式

清洗通过 Celery 异步执行。启动 worker：

```bash
celery -A app.tasks.celery_app:celery_app worker -Q freight_ai,analysis -l info
```

接口提交任务：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/freight/normalization/clean
```

响应会包含 `task_id`、`task_no` 和 `celery_task_id`。如果 worker 正常消费，终端会看到 `freight.clean_normalization` 任务。

查询任务：

```bash
curl "http://127.0.0.1:8000/api/v1/freight/normalization/tasks?page=1&page_size=5"
curl http://127.0.0.1:8000/api/v1/freight/normalization/tasks/{task_id}
```

查询质量统计：

```bash
curl http://127.0.0.1:8000/api/v1/freight/normalization/quality
```

查询待确认建议：

```bash
curl "http://127.0.0.1:8000/api/v1/freight/normalization-suggestions?status_code=PENDING"
```

批量应用建议：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/freight/normalization-suggestions/bulk-apply \
  -H "Content-Type: application/json" \
  -d '{"suggestion_ids":[1,2,3]}'
```

前端入口：`货源采集 -> 数据清洗`。

页面会展示最近任务、进度条、失败原因、货源详情悬浮预览，并支持“勾选批量应用”和“应用当前筛选全部待确认建议”。

## 自动与人工策略

- 高置信装卸地建议自动回填：默认阈值 `0.86`。
- 高置信货品建议自动回填：默认阈值 `0.82`。
- 低置信建议保留为 `PENDING`，由业务人员在数据清洗页应用或拒绝。
- 拒绝建议不会修改正式货源。
- 重复清洗不会重复生成同一正式货源、同一类型的待处理建议。

## 分析重算

清洗自动回填或人工应用后，会触发受影响日期范围的货源分析事实重算：

- 货源流向事实。
- 标准货品结构事实。
- 城市维度事实。
- 运输节点维度事实。

这样可以保证原文级货源被提升后，后续分析报表能看到新的标准维度贡献。
