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

`freight_normalization_suggestion` 保存每条建议：

- `suggestion_type_code`：`ORIGIN`、`DESTINATION`、`COMMODITY`。
- `raw_text`：待清洗原文。
- `suggested_level_code`：建议提升到 `NODE`、`CITY` 或 `STANDARD`。
- `confidence_score`：匹配置信度。
- `status_code`：`PENDING`、`APPLIED`、`AUTO_APPLIED`、`REJECTED`。
- `before_json`、`after_json`：应用前后快照。

## 执行方式

接口执行：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/freight/normalization/clean
```

查询质量统计：

```bash
curl http://127.0.0.1:8000/api/v1/freight/normalization/quality
```

查询待确认建议：

```bash
curl "http://127.0.0.1:8000/api/v1/freight/normalization-suggestions?status_code=PENDING"
```

前端入口：`货源采集 -> 数据清洗`。

## 自动与人工策略

- 高置信装卸地建议自动回填：默认阈值 `0.86`。
- 高置信货品建议自动回填：默认阈值 `0.82`。
- 低置信建议保留为 `PENDING`，由业务人员在数据清洗页应用或拒绝。
- 拒绝建议不会修改正式货源。

## 分析重算

清洗自动回填或人工应用后，会触发受影响日期范围的货源分析事实重算：

- 货源流向事实。
- 标准货品结构事实。
- 城市维度事实。
- 运输节点维度事实。

这样可以保证原文级货源被提升后，后续分析报表能看到新的标准维度贡献。
