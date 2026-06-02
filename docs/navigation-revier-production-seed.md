# revier 航道生产种子

本流程从 `revier.zip` Shapefile 直接构建航道生产种子，不使用 GeoJSON 中间源，不生成演示图，也不绕开现有 navigation 模型、seed profile、路由引擎和前端页面。

## 输入

- 推荐路径：`scripts/source_data/navigation/revier.zip`
- 本地原始文件：`/Users/hj/Documents/河道数据/revier.zip`
- 必读图层：`rx`、`rx8`、`一级水系`、`二级水系`、`三级水系`、`四级水系`、`五级水系`、`六级水系`、`七级水系`
- CRS：优先读取 `.prj`，缺失或不可解析时回退 `EPSG:4326` 并写入报告。

## 构建

```bash
.venv/bin/python -m scripts.navigation.build_revier_production_seed \
  --source-zip scripts/source_data/navigation/revier.zip \
  --output-dir runtime/navigation-production \
  --export-seed \
  --self-feedback \
  --use-qwen-if-available \
  --use-es-if-available \
  --max-feedback-rounds 3
```

主要输出：

- `scripts/seed_data/navigation/navigation_water_areas.revier.prod.jsonl.gz`
- `scripts/seed_data/navigation/navigation_water_areas.jsonl.gz`
- `scripts/seed_data/navigation/navigation_channel_boundaries.revier.prod.json`
- `scripts/seed_data/navigation/navigation_channel_centerlines.revier.prod.json`
- `scripts/seed_data/navigation/navigation_centerline_segments.revier.prod.json`
- `scripts/seed_data/navigation/navigation_graph_versions.revier.prod.json`
- `scripts/seed_data/navigation/navigation_graph_nodes.revier.prod.json`
- `scripts/seed_data/navigation/navigation_graph_edges.revier.prod.json`
- `scripts/seed_data/navigation/navigation_annotation_tasks.revier.prod.json`
- `runtime/navigation-production/reports/*.json`

中心线策略是边界切片中线生成，并执行边界内、点数、长度、折返、近直线等校验。未通过的中心线不进入图，改为生成 annotation task；路由服务不启用直线 fallback。

## 导入

```bash
.venv/bin/python -m scripts.seeds.cli --profile production
```

production profile 会重建现有 navigation channel seed，加载水域、水体、匹配、约束、TransportNode，并在最后加载 `NAV_GRAPH_REVIER_PROD_V1` 图版本。为保证可重复运行，profile 会先清理旧图边/节点/中心线等依赖，再重建航道。

## 验证

```bash
.venv/bin/python -m scripts.navigation.validate_revier_routing_with_transport_nodes \
  --graph-version-code NAV_GRAPH_REVIER_PROD_V1 \
  --min-success-count 5 \
  --sample-count 10 \
  --use-es-if-available
```

验证只统计真实图路径：必须有 `edge_ids`，必须包含非 `TRANSPORT_NODE_CONNECTOR` 图边，且 `straight_line_fallback_allowed=false`。

```bash
.venv/bin/python -m scripts.navigation.navigation_production_acceptance \
  --graph-version-code NAV_GRAPH_REVIER_PROD_V1
```

验收报告写入：

- `runtime/navigation-production/reports/transport_node_routing_validation_report.json`
- `runtime/navigation-production/reports/navigation_production_acceptance_report.json`

## 当前验收快照

截至 2026-06-01 本地执行结果：

- `revier.zip` 读取 9 个图层，共 92,480 个要素。
- `RIVER_SHAPEFILE_2026` 水域入库 92,480 条。
- 水体入库 37,414 条。
- `NAV_GRAPH_REVIER_PROD_V1` 状态 READY 且 active。
- 图节点 156 个，图边 137 条。
- TransportNode OD 验证 10/10 成功，最少要求 5 条。
- HiFleet benchmark 因 `HIFLEET_ENABLED=false` 跳过。

## 限制

- 当前图是基于 revier 水系边界和 TransportNode 生成的生产候选图，不等同官方通航安全图。
- 部分边界和中心线仍有 annotation task，需要人工结合 AIS/HiFleet、闸口、桥梁、航道等级、船型限制复核。
- Qwen/ES/HiFleet 只用于报告或外部对照，不参与几何生成，也不会改写中心线坐标。
