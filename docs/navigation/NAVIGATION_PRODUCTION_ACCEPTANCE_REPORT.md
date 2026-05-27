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

### 2026-05-26 路径验证 Graph 诊断增补

本轮继续不录屏，聚焦路径验证页的生产诊断可见性。

1. Graph 全量诊断
   - `production-workspace` 新增 `graph_diagnostics`。
   - 诊断包含：激活 Graph 版本、节点数、总边数、可路由边数、约束缺失边数、约束完整度、Graph 校验 issue 统计、来源边界 ID。
   - 路径验证页新增“Graph 生产诊断”面板，显示激活版本、全量 Graph、当前视口图边、覆盖范围、约束数据。

2. 截断与全量区分
   - 路径验证页同时显示“全量 Graph 边数”和“当前视口加载图边数”。
   - 当前视口图边被 `limit` 截断时，明确提示“当前地图不是全量 Graph”。

3. 约束数据缺失提示
   - 若 Graph 存在 `UNKNOWN_CONSTRAINT_DATA`，页面直接展示缺失边数和 warning。
   - 路径仍可验证，但页面明确说明不能视为约束数据完整。

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
- navigation focused pytest：83 passed
  - 覆盖：centerline segments、boundary candidates、boundary draft ops、workbench service、routing engine、map layers、diagnostic service。
- 本轮增量测试：
  - `tests/test_navigation_workbench_service.py`：25 passed
  - `npm run type-check`：通过
- full pytest：未通过
  - 结果：328 passed，2 skipped，41 failed，26 errors
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

### 2026-05-27 Graph 构建页诊断增补

本轮目标：把路径页已能看到的全量 Graph 诊断前移到“图网络构建”页，避免操作员只看到一个版本列表，不知道该 Graph 是否能激活、是否缺少约束、是否保留了区段拓扑。

完成内容：

1. 后端新增共享 Graph 诊断服务，构建响应、激活响应、版本列表、生产工作台使用同一套指标。
2. Graph 版本列表返回 `diagnostics`，包括：
   - 全量节点数 / 图边数 / 可路由图边数；
   - 缺少完整约束数据的图边数；
   - 约束完整度；
   - 阻断问题数 / 警告问题数 / issue_counts；
   - 来源边界、来源中心线、来源区段；
   - `can_activate`、`activation_blockers`、`activation_warnings`。
3. 激活接口增加诊断闸门：
   - 非 READY、无图边、无可路由图边、存在阻断问题、Graph 断连时不能激活；
   - 约束数据缺失、警告问题、低质量分作为激活风险提示，不直接阻断。
4. 前端 Graph 构建页新增“Graph 生产诊断”面板：
   - 显示诊断版本、全量 Graph、覆盖范围、来源数据、约束数据、激活判断；
   - 表格每个版本显示可路由图边、缺失约束图边、是否可激活；
   - 有风险但可激活时弹出确认，明确说明“路径可以使用，但不能说明约束数据已经完整”。

验证结果：

- 后端增量测试：`tests/test_navigation_workbench_service.py` 26 passed。
- Navigation focused pytest：84 passed。
- Full pytest：未通过，`329 passed，2 skipped，41 failed，26 errors`；失败仍集中在 freight、route track、vessel spatial 等非 navigation 历史问题。
- 前端 `npm run type-check`：通过。
- 前端 `npm run build`：通过，保留既有 chunk size warning。
- 浏览器检查：已在本地页面打开 `/navigation/production/graphs?channel_id=314`，确认页面显示当前长江干线 Graph 诊断：635 节点、634 边、623 可路由边、606 来源区段、边界覆盖 99%、634 条图边缺少完整约束数据。
- 本轮未录制视频，按用户要求后续不再做视频录屏。

### 2026-05-27 Graph 问题图边定位与修复入口

本轮目标：让“约束数据缺失”不再只是统计数字，操作员可以从 Graph 构建页直接进入具体图边，定位并生成修复任务。

完成内容：

1. 后端新增 `GET /navigation/graph-versions/{id}/issue-edges`：
   - 支持 `issue_code/channel_id/page/page_size/include_geometry`；
   - 可筛选 `UNKNOWN_CONSTRAINT_DATA`、不可路由、低质量或带警告图边；
   - 返回图边 ID、编码、长度、质量、问题类型、约束记录数、中心点、bbox、几何和已存在开放标注任务 ID。
2. 前端 Graph 构建页新增问题图边抽屉：
   - “查看缺约束图边”默认打开缺约束图边；
   - “全部问题图边”用于查看不可路由和质量问题图边；
   - 支持分页、刷新、复制中心点/bbox；
   - 选中图边后左侧地图以橙色高亮该图边。
3. 修复入口：
   - 抽屉内可直接“生成标注任务”；
   - 可跳转“打开标注任务”，后续在标注任务页补齐约束或回修中心线。

真实浏览器检查：

- 页面：`/navigation/production/graphs?channel_id=314`
- 航道：长江干线
- 操作：点击“查看缺约束图边”
- 结果：抽屉显示真实问题图边列表，首批图边如 `REAL-CJ-V552-FULL-1779796708376-E-00001`，问题包含“带警告 / 约束缺失”，长度约 4.85 km，状态可路由，支持“定位 / 复制坐标”。

验证结果：

- `.venv/bin/python -m compileall app scripts`：通过。
- Navigation focused pytest：84 passed。
- Full pytest：未通过，`329 passed，2 skipped，41 failed，26 errors`；失败仍集中在 freight、route track、vessel spatial 等非 navigation 历史问题。
- `npm run type-check`：通过。
- `npm run build`：通过，保留既有 chunk size warning。
- 本轮未修改敏感配置，未提交 `.env`、key/token、数据库备份或 `scripts/seeds/loaders/production_freights.py`。

### 2026-05-27 中心线点位标记自动连线

本轮目标：把中心线主流程从“自动生成/手画线段”调整为“标记全航道控制点 -> 系统按编号直连预览 -> 校验 -> 按里程自动切区段”。现有生产导向线只作为导入点位草稿来源，不能绕过点位版本直接成为发布结果。

完成内容：

1. 后端新增持久点位版本资产：
   - `navigation_centerline_point_set`
   - `navigation_centerline_control_point`
   - 点位版本记录当前边界 ID、版本号、状态、点数、连线长度、bbox、自动连线 GeoJSON、校验摘要和来源追踪。
2. 后端新增点位 API：
   - `GET /navigation/channels/{id}/centerline-point-sets`
   - `POST /navigation/channels/{id}/centerline-point-sets`
   - `PUT /navigation/centerline-point-sets/{id}/points`
   - `POST /navigation/centerline-point-sets/{id}/preview`
   - `POST /navigation/centerline-point-sets/{id}/archive`
3. 区段生成新增 `source_mode=CONTROL_POINTS`：
   - 必须传 `point_set_id`；
   - 按控制点顺序直接生成 LineString，不做平滑、不绕行、不改路径算法；
   - 区段来源记录 `source_point_set_id`、点位 ID、点位 hash、`based_on_boundary_id`；
   - 新区段完全创建和校验后才归档旧活动区段，避免接口失败时先打掉旧数据。
4. 前端中心线页改为点位主流程：
   - 顶部主按钮改为“创建点位草稿 / 导入导向线为点位 / 保存点位 / 预览自动连线 / 基于点位生成区段”；
   - 新增中心线控制点面板，支持选择点位版本、地图打点、拖动点位、删除、插入、上移/下移、撤销、清空、归档隐藏；
   - 地图显示编号控制点和紫色虚线自动连线预览；
   - 保存、预览、分页、生成后遵守视野锁定，不自动漂移。
5. 长干线边界局部 polygon 偏差处理：
   - 点位连线 bbox 覆盖当前边界主轴但局部 polygon 不覆盖时，降级为复核 warning；
   - 点位来源区段不再批量打 `SEGMENT_OUT_OF_BOUNDARY` error，而是显示 `SEGMENT_BOUNDARY_REVIEW_FROM_CONTROL_POINTS` warning，要求操作员逐段复核。

真实浏览器检查：

- 页面：`/navigation/production/centerlines?channel_id=314`
- 航道：长江干线
- 当前发布边界：ID 567
- 当前点位版本：V2 / CURRENT
- 点位数量：798
- 自动连线长度：3025.24 km
- 点位校验：0 阻断 / 1 警告
- 操作：点击“基于点位重新生成”，确认弹窗后完成重新生成。
- 结果：生成 606 个 `CONTROL_POINTS_AUTOLINK` 区段，均为待修复；问题统计为 606 个 `SEGMENT_BOUNDARY_REVIEW_FROM_CONTROL_POINTS` warning，另有 10 个急转弯复核 warning；不再出现旧逻辑的 315 个 `SEGMENT_OUT_OF_BOUNDARY` error。
- 体验记录：首次进入时 5MB 工作台响应会先显示 0 段默认态，约 1 秒后加载为真实数据。后续应继续拆分工作台大响应，避免操作员误判为空数据。

验证结果：

- `.venv/bin/python -m compileall app scripts`：通过。
- `tests/test_navigation_centerline_segments.py`：19 passed。
- Navigation focused pytest：76 passed。
- `npm run type-check`：通过。
- `npm run build`：通过，保留既有 chunk size warning。
- 本轮未重置 seed，未修改敏感配置，未提交 `.env`、key/token、数据库备份或 `scripts/seeds/loaders/production_freights.py`。
