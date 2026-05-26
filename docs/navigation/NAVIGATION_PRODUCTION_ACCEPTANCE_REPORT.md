# 航道图生产工具可用性与完整性验收报告

验收时间：2026-05-26
验收环境：本地真实环境，Redis、MySQL、PostgreSQL/PostGIS Docker 容器已启动。
验收方式：后端 `uvicorn --reload` 与前端 Vite dev server 启动，在真实浏览器中按操作员流程录制大屏视频。

## 实际验收航道

- 航道名称：长江干线
- channel_id：314
- channel_code：NC-YANGTZE
- 已归属水体数量：4
- 历史问题边界：V552 覆盖范围约 `117.03-122.06`，不能覆盖长江干线内陆段。
- 当前发布边界：ID 567，`CHANNEL_CORRIDOR_ENVELOPE`
- 当前发布边界 bbox：`104.628600,28.702000,122.066200,32.332400`
- 当前发布边界点数：39189
- 非当前可用边界版本数量：5
- 生产导向线：segment_id 601，长度 3025.24 km
- 生产导向线 bbox：`104.650424,28.706111,122.044376,32.321411`
- 当前中心线：ID 10，已发布
- 中心线区段：606 段，已确认/已发布 606 段，待修复 0 段
- 当前激活 Graph：ID 10，`READY`，节点 635，边 634，质量分 65
- 路径验证：route_result_id 21，graph_version_id 10，`READY_WITH_WARNING`，距离 3025.2431 km

## 大屏浏览器验收

- 视频文件：`/Users/hj/Documents/paltform_data_V2/navigation_changjiang_full_flow_2560_20260526.webm`
- 事件日志：`/Users/hj/Documents/paltform_data_V2/navigation_changjiang_full_flow_2560_events_20260526.json`
- 视频尺寸：2560 x 1440
- 视频大小：22 MB
- 是否真实浏览器点击：是

覆盖步骤：

1. 登录本地系统并进入长江干线边界页。
2. 查看当前发布边界和边界版本列表。
3. 进入中心线页，打开大屏地图并折叠区段列表/编辑面板。
4. 点击“重新生成中心线区段”，基于当前发布边界和生产导向线生成 606 段。
5. 分页读取并确认全部 606 段。
6. 点击“合并发布中心线”，发布中心线 ID 10。
7. 进入图网络构建页，构建并激活 Graph ID 10。
8. 进入路径验证页，点击“定位当前 Graph”。
9. 点击“地图选起点”和“地图选终点”，在地图上完成点选。
10. 点击“生成路径”，并用首段起点到末段终点验证完整 Graph，结果为 `SUCCESS / READY_WITH_WARNING`。

## 本轮修复

### 2026-05-26 下一轮可用性增补

本轮不再录屏，重点处理真实操作中继续暴露的三个可用性问题：区段数量上来后无法按问题批量处理、路径验证大图层截断提示不清、边界/中心线/Graph 覆盖差异不够直观。

1. 中心线区段批量质量处理
   - 后端区段列表新增 `issue_code` 筛选和 `issue_stats` 聚合。
   - `issue_stats` 按问题类型统计受影响区段数，并保留最高严重级别。
   - 前端区段列表新增“质量报告”，支持从问题类型 chip 或下拉框直接筛选问题段。
   - `只看问题段` 改用统一问题解析逻辑，兼容 `validation_summary_json.issues` 与 `issue_summary_json.issue_codes`。

2. 覆盖范围可视化
   - 工作台响应新增 `current_centerline_bbox`、`active_graph_bbox`。
   - 工作台响应新增边界/中心线/Graph 的 bbox 覆盖比例。
   - 中心线页新增覆盖面板，同屏展示已归属水体、当前发布边界、当前中心线、当前 Graph 的范围、状态和覆盖比例。
   - 操作员可以直接看到“边界完整但中心线/Graph 只覆盖局部”的差异，不再只靠地图肉眼判断。

3. 路径验证图层截断
   - 地图图层响应新增 `layer_counts`、`layer_limits`。
   - 路径验证页图层状态显示 `160/160+` 这类截断标记。
   - 截断 tag 改为明确文案：仅显示前 N 条，避免把当前视口渲染结果误解成完整 Graph。

### 2026-05-26 完整流验收修复

1. 地图载体
   - 增加程序 fit 事件窗口，避免 AMap 异步 `moveend` 被误判为用户拖拽后继续漂移。
   - 保存、刷新、选择、分页、校验不再自动 fit；只有定位按钮触发 fit。
   - 中心线页增加大屏地图、折叠区段列表、折叠编辑面板。
   - 中心线地图可加载区段背景层，不再只依赖当前页。

2. 大数据区段
   - 中心线区段列表新增后端分页参数 `page/page_size/include_geometry/status_code/only_problem`。
   - 前端默认分页展示，避免一次性把所有区段几何塞进列表。
   - 地图图层新增 `centerline_segments`，支持 bbox/limit 图层加载。

3. 中心线生成
   - 新增生产导向线字段和迁移。
   - 生产 seed 为长江干线补齐导向线，长度覆盖完整主线。
   - 默认生成模式改为 `CHANNEL_GUIDE_WITH_BOUNDARY_CLIP`。
   - `BOUNDARY_ROUGH_LOCAL` 只作为局部粗生成，不再作为长干线主算法。
   - 导向线缺失、边界覆盖不足时返回 `BLOCKED`，不再生成误导性短线。
   - 对长江干线这类边界覆盖 bbox 合格但 polygon 裁剪会碎裂的情况，采用导向线 bbox 约束通过，并记录复核 warning。

4. Graph 构建
   - 发布中心线保留 `segment_ids/source_boundary_id/source_guide_id`。
   - Graph 构建从发布区段生成多节点多边，不再把整条中心线压成 2 节点 1 边。
   - Graph 校验阻断长航道边数过少的问题。
   - 对禁用的吸附/参考连接边，不再把孤立参考节点当作路由 Graph 断连错误。

5. 路径验证
   - 路径加载对可控规模 Graph 优先加载 Graph 构建范围，避免只按起终点小 bbox 截断长航道。
   - 约束数据缺失仍保留 warning，但不把长航道每条边的未知约束叠加成失败。
   - 边界覆盖不足但水体覆盖可用时降级为 warning，页面仍要求复核，不伪装为安全确认。

6. 生产状态
   - `CHANNEL_CORRIDOR_ENVELOPE` 作为可发布边界来源参与生产阶段判断。
   - 已发布区段计入“已确认/已发布”统计，避免发布后页面显示“已确认 0”。

## 发现的问题和修复情况

1. 问题：V552 边界只覆盖 `117.03-122.06`，中心线只到 `120.61-122.01`，与匹配水体 `104.63-122.06` 不一致。
   - 处理：按允许范围重置 navigation production 派生数据，并从生产 seed 重新发布当前边界 ID 567；旧历史不物理删除。

2. 问题：纯边界 Voronoi 抽轴在长干线场景只生成局部小线或碎裂线。
   - 处理：改为生产导向线主导、当前发布边界约束；长江干线生成 606 段，bbox 覆盖 `104.65-122.04`。

3. 问题：地图刷新、选择、保存后容易漂移，且三栏布局挤压地图。
   - 处理：增加视口锁定和程序 fit 识别；增加大屏地图和面板折叠。

4. 问题：区段数量上来后列表不可用。
   - 处理：后端分页、前端分页、地图层按图层加载；606 段验收可操作。

5. 问题：Graph 构建历史上可能出现 2 节点 1 边，无法支撑真实路径验证。
   - 处理：Graph 从区段拓扑生成，长江干线本次构建 635 节点、634 边。

6. 问题：路径验证图层 limit 只返回 500 条边，不能把图层首尾当完整路径首尾。
   - 处理：验收脚本改用发布区段首尾点做完整 Graph API 验证；页面仍保留地图选点体验。

## 测试结果

- `.venv/bin/python -m compileall app scripts`：通过
- navigation focused pytest：82 passed
  - 覆盖：centerline segments、boundary candidates、boundary draft ops、workbench service、routing engine、map layers、diagnostic service。
- full pytest：未通过
  - 结果：327 passed，2 skipped，41 failed，26 errors
  - navigation 本轮新增/修改测试已通过。
  - 主要非本轮失败示例：freight collection 中 `Region(audit_status=...)` 与模型字段不匹配；另有 node contacts/photos、production remediation、quote/rate estimator、route track、vessel spatial 等既有失败。
- `npm run type-check`：通过
- `npm run build`：通过，保留既有 chunk size warning。

## 敏感配置保护确认

- 是否修改 `.env`：否
- 是否修改 `.env.*`：否
- 是否修改 key/token：否
- 是否修改 AI provider / 高德 key / hifleet key：否
- 是否重置用户/角色/权限/菜单/AI 配置/系统配置：否
- 是否执行生产 seed 导向重置：是，仅限 navigation production 派生数据和长江干线当前边界/导向线。
- 是否提交数据库备份：否
- 是否提交 `scripts/seeds/loaders/production_freights.py`：否

## 遗留问题与下一轮方案

1. 当前路径结果是 `READY_WITH_WARNING`，原因是约束数据缺失、水体覆盖约 72.3%、边界覆盖仍需要人工复核。下一轮应做“约束数据完整度面板”和“边界/水体覆盖差异专门诊断”。
2. 中心线本轮已有按问题类型筛选，但仍缺“局部重算/拒绝本次生成/批量确认策略”。下一轮应把这些做成明确的生产动作，并保留操作日志。
3. 路径页已显示图层截断，但还没有 Graph 全量覆盖诊断卡。下一轮应直接展示 Graph 全量 bbox、当前视口 bbox、节点/边总量、已加载数量和截断原因。
4. 菜单 seed 当前已将“航道图生产”和“航线与区域基础”放在同一航线与区域中心下，并隐藏旧工作台入口；后续如果继续做信息架构，应只调整文案和入口，不拆数据表。
