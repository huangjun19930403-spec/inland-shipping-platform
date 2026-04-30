# 全局后端重构路线

## 1. 后端总原则

- 表结构服务业务链路。
- 不为低价值页面保留业务主表。
- 导入批次类对象不作为业务主对象。
- 分析模块需要面向图表 API。
- 如果前端产品需要聚合接口，后端必须新增，不让前端硬拼。
- 基础数据、演示数据、E2E 数据必须在脚本和编码上可区分。
- 分类、类型、导入批次等后台支撑对象可以保留模型和接口，但不能驱动一级业务页面。
- 当现有表结构无法表达采集、候选、确认、画像、地图分析等业务时，允许重构表结构和 migration。

## 2. 分模块后端整改

### 基础数据域

保留：

- admin_region
- region
- region_boundary_version
- transport_node
- navigation_constraint_point
- navigation_constraint_profile
- commodity 系列表

后续新增：

- entity_match_log
- standardization_feedback
- node_match_candidate
- region_assignment_snapshot

整改方向：

- `admin_region` 作为行政区划基础 seed，不作为频繁业务操作对象。
- `region` 承载业务区域和分析区域。
- `transport_node` 承载港口、码头、作业点、换装点等业务能力。
- `navigation_constraint_point` 承载桥梁、船闸、浅滩、限航点等航线约束。
- `commodity_category`、`commodity_type` 保留为基础 seed 和筛选维度，业务主对象是 `commodity_standard` 及其别名、包装、适配规则。
- 标准化链路需要记录匹配日志、候选、人工反馈和区域归属快照。

### 货源域

保留：

- freight

新增方向：

- freight_ingest_batch
- freight_raw_message
- freight_clue
- freight_candidate
- freight_candidate_match
- freight_confirm_record
- freight_quality_score
- freight_duplicate_relation

整改方向：

- `freight` 只表达正式货源。
- 原始消息、AI 解析、候选、确认、质量分、重复关系不应塞进正式货源表。
- 货源链路必须支撑“采集 -> AI解析 -> 候选 -> 确认 -> 正式货源 -> 分析”。
- 分析统计应基于正式货源和确认记录生成。

### 船舶域

保留：

- ship_profile
- ship_capacity
- ship_operation
- ship_owner
- ship_certificate
- ship_mmsi_history

重新评估：

- ship_import_batch
- ship_import_raw
- ship_import_record

目标：

- 导入批次不作为业务页面。
- 可降级为通用 import_task 或后台日志。

新增方向：

- ship_profile_quality
- ship_region_daily_stat
- ship_flow_daily_stat
- ship_heat_grid_daily
- ship_capacity_distribution_daily
- ship_age_distribution_daily

整改方向：

- 船舶业务主对象是档案和画像，不是导入批次。
- 导入流程作为船舶列表动作，接口返回摘要、成功数、失败数、错误明细下载地址。
- 船舶画像需要质量评分、运力分布、船龄分布、区域分布、流向统计、热力统计。

### 分析域

现有统计表保留。

新增 chart/dashboard API：

- cargo overview
- cargo trend
- cargo flow map
- ship overview
- ship distribution
- ship heatmap

整改方向：

- 当前分页表 API 继续服务明细穿透。
- 第 4 轮新增面向图表和地图的聚合 API。
- 货源分析需要 overview、日趋势、城市排行、货品分布、渠道漏斗、流向地图。
- 船舶分析需要 overview、城市分布、运力分布、船龄分布、流向地图、热力网格。
- 聚合 API 返回前端可直接渲染的 series、ranking、geo points、flow lines、heat grid，不让前端从分页表硬拼。

### 航线路径域

保留 4B-4D 成果。

后续第 8 轮继续。

整改方向：

- 保留 shipping_route、shipping_route_plan、shipping_route_line、shipping_route_line_node、shipping_route_line_segment、shipping_route_line_track。
- 暂缓继续深做路径节点编辑器。
- 第 8 轮统一实现节点串生成航段、geometry、约束影响、可行性判断。
- 旧航段主操作降级为生成结果和调试信息。

## 3. 每轮后端改造范围

### 第 0 轮：总控定稿

- 只新增 docs。
- 不改表。
- 不改接口。
- 不改 seed。
- 不改业务代码。
- 验收：`git diff --check` 通过，新增文档内容完整。

### 第 1 轮：Seed 与本地验证数据重构

- 拆分基础 seed、演示 seed、E2E seed。
- 扩充标准货品、别名、业务区域、运输节点、通航约束点、船舶、货源、分析统计。
- 调整 `seed_system_init` 的职责，避免 E2E 数据和演示数据混用。
- 可新增只读 seed 验证脚本。
- 原则上不改表；如现有表无法保存必要演示字段，再小范围改表。
- 验收：clean DB 后数量和日期范围达标。

### 第 2 轮：前端组件体系基建

- 后端不做业务改造。
- 如组件试点需要极小 API 字段补齐，单独评估。
- 验收：不引入后端行为变化。

### 第 3 轮：菜单与页面结构收敛

- 更新菜单 seed 和菜单查询结果。
- 删除或隐藏低价值菜单入口。
- 保留必要隐藏路由支撑详情页。
- 后端不删除 category/type/import batch 表，仅调整产品可见性。
- 验收：菜单接口不再返回货品分类、货品类型、船舶导入批次作为一级业务入口。

### 第 4 轮：分析模块产品化重构

- 新增货源和船舶 dashboard/chart/map 聚合接口。
- 现有分页统计接口保留为明细穿透。
- 视需要新增热力网格、分布统计、快照统计表。
- seed 补足统计样例。
- 验收：前端可直接用聚合接口渲染指标卡、ECharts、地图、流向、热力。

### 第 5 轮：基础数据模块产品化重构

- 基础数据域围绕标准化能力补表。
- 可新增 entity_match_log、standardization_feedback、node_match_candidate、region_assignment_snapshot。
- 地址、区域、节点、约束点、标准货品接口按用户任务提供聚合详情。
- 验收：标准化匹配、节点能力档案、约束能力可被货源、航线、分析引用。

### 第 6 轮：货源链路产品化重构

- 新增采集、原始消息、线索、候选、匹配、确认、质量、重复关系表。
- 正式货源接口保留，但从确认链路生成或关联。
- 新增采集与解析、候选确认、质量看板接口。
- 验收：采集 -> AI解析 -> 候选 -> 确认 -> 正式货源 -> 分析链路可跑通。

### 第 7 轮：船舶画像产品化重构

- 重新评估 ship_import_batch/raw/record，决定保留为后台日志或迁移为通用 import_task。
- 新增船舶质量、区域统计、流向统计、热力、运力分布、船龄分布相关表和 API。
- 船舶导入接口改为船舶列表动作。
- 验收：船舶画像、证书、AIS/MMSI、分析闭环；导入批次不再驱动业务页面。

### 第 8 轮：航线方案产品化重构

- 基于 4B-4D 模型统一重构航线方案链路。
- 新增或调整节点串生成航段、geometry、约束影响、可行性判断接口。
- 保留旧数据时要明确迁移或降级策略，不做兼容式页面堆叠。
- 验收：用户能从航线列表进入方案，维护节点串，生成航段和轨迹，查看约束影响与可行性结论。
