# 航道图生产本地端到端验收报告

验收时间：2026-05-26

## 本地环境说明

- Docker 服务：Redis、MySQL、PostgreSQL/PostGIS 均使用本地 Docker 容器。
- 数据库类型：PostgreSQL/PostGIS 为航道图生产主库；MySQL 容器保留本地业务配置兼容；Redis 用于缓存和异步任务。
- Alembic 状态：`012_navigation_centerline_segment (head)`。
- 是否使用生产 seed：是，使用本地生产 seed 和真实配置。
- 敏感配置保护：未修改 `.env`、`.env.*`、key/token/password、AI provider、模型配置、高德/Hifleet 配置。
- Seed 保护：未执行全库重置，未清空用户、角色、权限、菜单、AI provider、model profile、runtime policy 或集成配置。

## 实际验收航道

- 航道名称：西江航运干线
- channel_id：315
- channel_code：NC-XIJIANG
- 已归属水体数量：11
- 水体候选数量：80
- 生成边界候选数量：本次生成 3 类；验收时累计候选 7 个
- 发布边界 ID：550
- 生成中心线区段数量：1
- 发布中心线 ID：3
- Graph version ID：3
- Graph version code：ACCEPTANCE-LOCAL-GRAPH-20260526040341
- 路径请求 ID：5、6、7、8

## 验收结果

### 1. 航道水系规划

- 页面可打开并选择“西江航运干线”。
- 已归属水体显示 11 个，系统推荐水体显示 80 个。
- 文案区分“已归属水体”和“系统推荐”，页面说明已归属水体用于下一步边界生成。
- 地图图层使用中文名称，例如“已归属水体边界”“规划航道参考范围”。

### 2. 边界生成

- 顶部来源链显示“已归属水体 11 个 → 边界候选 9 个 → 当前发布边界 1 个”。候选数量包含历史验收生成记录。
- 点击“生成边界候选”后生成：
  - WATER_BODY_UNION_RAW
  - WATER_BODY_UNION_CLEANED
  - WATER_BODY_UNION_SIMPLIFIED
- 候选卡片显示候选类型、来源水体数量、点数、面积、是否简化、用途说明。
- 浏览器中实际点击候选“查看”，候选可被选中并定位。
- API 验证候选载入草稿、预校验、保存和发布成功。
- 边界修复操作验证通过：
  - DELETE_PART：成功，点数 21842 -> 21195。
  - KEEP_ONLY_PART：成功，点数 21842 -> 14。
  - UNION_PATCH：成功。
  - SUBTRACT_PATCH：成功。
  - CLEAN_SMALL_PARTS：成功。
  - SIMPLIFY：成功，点数 21842 -> 18954。
- 发布前页面明确提示：发布后成为当前边界、后续需重新生成中心线区段和 Graph、本操作不会创建审批任务。

### 3. 中心线分段生产

- 页面显示“基于当前边界生成中心线区段，逐段修复确认，不需要一次性画完整航道”。
- 主操作为“生成中心线区段”“补画当前区段”“确认区段”“合并发布中心线”，未把“绘制完整中心线”作为主入口。
- 本次生成 1 个区段，区段编号 001。
- 浏览器中实际点击区段 001，右侧工具显示定位、补画、编辑顶点、端点吸附等操作。
- API 验证区段更新、确认成功，区段状态为 CONFIRMED。
- 合并发布中心线成功，返回 centerline_id = 3。
- 发布响应提示需要重新构建并激活 Graph。

### 4. Graph 构建与激活

- 基于发布中心线构建 Graph 成功。
- Graph version ID：3。
- node_count：2。
- edge_count：1。
- status_code：READY。
- quality_score：97。
- 构建结果包含 1 条 WARNING：`UNKNOWN_CONSTRAINT_DATA`，无 BLOCKING。
- Graph 已激活为 active READY graph。

### 5. 路径验证

- 浏览器中实际填写起点/终点并点击“生成路径”，默认推荐路径成功。
- API 验证四种策略均使用真实 Graph 成功生成：
  - RECOMMENDED：request_id 5，SUCCESS，distance 1.4111 km。
  - SHORTEST：request_id 6，SUCCESS，distance 1.4111 km。
  - SAFEST：request_id 7，SUCCESS，distance 1.4111 km。
  - LOCK_AVOIDING：request_id 8，SUCCESS，distance 1.4111 km。
- 成本解释可显示，包含距离成本、质量惩罚、船闸惩罚、未知约束成本。
- 失败解释机制未触发真实失败；Graph 约束缺失以 WARNING 显示 next review 信息。
- 本次验收 Graph 只有 1 条 edge，因此备选路径返回 0 条，未出现可切换备选卡片。该结果来自真实 Graph，不使用 mock。

## 发现问题

### 已修复

1. Graph 构建未识别分段合并发布中心线。
   - 原因：Graph ready 中心线来源白名单漏掉 `CENTERLINE_SEGMENT_MERGE`。
   - 修复：将 `CENTERLINE_SEGMENT_MERGE` 纳入 Graph ready source，并补充测试。

2. PostgreSQL 路径生成空间校验报 `could not identify an equality operator for type json`。
   - 原因：对包含 JSON 字段的 `NavigationWaterBody` ORM 实体直接 `.distinct()`。
   - 修复：先 distinct 水体 ID，再按 ID 查询实体，避免 JSON 等值比较。

3. 大边界候选定位时浏览器报 `Maximum call stack size exceeded`。
   - 原因：前端 `fitAmapPoints()` 使用 `Math.min(...lngs)` 展开大量点。
   - 修复：改为循环聚合 bbox，避免大数组展开。

### 未修复 / 后续建议

1. 本次验收航道生成的 Graph 只有 1 条 edge，无法验证备选路径切换 UI。后续应使用多分支、多边、多节点 Graph 数据补一条专门验收航道。
2. 西江航运干线粗生成中心线区段只有 1 段，区段化工作台可用但没有体现多段前后连接场景。后续应选择或补充更长真实中心线验收数据。
3. Graph 构建 WARNING `UNKNOWN_CONSTRAINT_DATA` 说明通航约束数据仍需补齐；当前路径可用于测算，但不是安全通航确认。

## 敏感配置保护确认

- 是否修改 `.env`：否
- 是否修改 key/token：否
- 是否重置用户/角色/AI provider 配置：否
- 是否提交敏感文件：否
- 是否执行全库重置：否
- 是否提交数据库备份：否
- 是否提交 `scripts/seeds/loaders/production_freights.py`：否
