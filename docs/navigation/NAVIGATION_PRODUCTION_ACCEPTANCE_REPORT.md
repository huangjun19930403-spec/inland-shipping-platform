# 航道图生产主流程与地图交互纠偏验收报告

验收时间：2026-05-26
验收环境：本地真实环境，Redis、MySQL、PostgreSQL/PostGIS Docker 容器已启动。
验收方式：启动状态下使用后端 `uvicorn --reload` 与前端 Vite dev server，在真实浏览器中点击页面完成。

## 实际验收航道

- 航道名称：西江航运干线
- channel_id：315
- channel_code：NC-XIJIANG
- 已归属水体数量：11
- 边界候选数量：9
- 当前发布边界：ID 551，previous_boundary_id 550，caused_downstream_stale=true
- 当前中心线状态：已过期
- 当前 Graph 状态：已过期
- 中心线区段数量：1
- 已确认区段数量：1
- 路径验证结果：result_id 6，request_id 10，READY_WITH_WARNING，1.4111 km，quality_score 98，graph_version_id 3

## 本轮浏览器点击验收

1. 边界页生成候选：已点击“生成新的边界候选”，既有候选可继续载入修正。
2. 载入候选为草稿：已点击“载入候选修正”，草稿点数 18954，预校验 ERROR 0 / WARNING 1。
3. 定位按钮：已点击“定位候选边界”“定位当前草稿”，视野状态显示用户锁定。
4. 保存草稿：已点击“保存草稿”，草稿状态变为已保存。
5. 发布边界：已点击“发布新边界版本”并确认发布，新 current boundary 为 551。
6. 下游失效提示：发布后边界页显示中心线状态“已过期”、Graph 状态“已过期”。
7. 中心线页生成区段：已点击“重新生成中心线区段”并确认，生成基于边界 551 的区段。
8. 区段定位：已点击“定位当前区段”“定位吸附点”。
9. 补画当前区段：已点击“补画当前区段”，地图补点后保存。
10. 保存/确认区段：误补画越界时被拦截；已重置为生成候选后点击“确认区段”，区段状态为已确认。
11. 路径验证地图选点：已点击“地图选起点”“地图选终点”，地图点击写入经纬度；覆盖物点击透出 map-click 后可在 Graph/边界上选点。
12. 生成路径：为贴合当前 Graph 端点，选点后校准到图边端点并点击“生成路径”，路径生成成功。

## 发现的问题和修复情况

1. 新边界发布后旧中心线/Graph 没有历史 `source_boundary_id` 时，页面仍显示未过期。
   - 已修复：后端使用 current boundary 的 `caused_downstream_stale=true` 兜底判断 legacy 下游资产过期。

2. 旧发布边界在新版本发布后被前端误计入候选边界数量。
   - 已修复：前端候选列表按 `coverage_policy_code` / `boundary_quality_code` 区分候选与历史版本。

3. 路径验证中点击边界、中心线、Graph 覆盖物时，地图选点没有写入表单。
   - 已修复：`BaseAmap` 在 polygon、polyline、marker、circle marker 点击时同步触发 `map-click`。

4. 路径页定位到 Graph 后，地图选点按钮在左侧表单，滚动操作容易点偏。
   - 已修复：路径页地图工具条增加“地图选起点”“地图选终点”。

## 测试结果

- `.venv/bin/python -m compileall app scripts`：通过
- navigation focused pytest：61 passed
- full pytest：未通过，属于既有非 navigation 历史失败；navigation 相关测试均通过。
  - 结果：320 passed，2 skipped，41 failed，26 errors
  - 主要历史失败示例：`tests/test_freight_collection_rework.py` 中 `Region(audit_status=...)` 与模型字段不匹配；另有 freight、route track、vessel spatial 等既有失败。
- `npm run type-check`：通过
- `npm run build`：通过，保留既有 chunk size warning。

## 敏感配置保护确认

- 是否修改 `.env`：否
- 是否修改 `.env.*`：否
- 是否修改 key/token：否
- 是否修改 AI provider / 高德 key / hifleet key：否
- 是否重置 seed：否
- 是否重置用户/角色/权限/菜单/AI 配置/系统配置：否
- 是否提交数据库备份：否
- 是否提交 `scripts/seeds/loaders/production_freights.py`：否

## 遗留问题

1. 当前 active Graph 只有 1 条 edge，备选路径切换仍无法在该航道上验证。
2. 路径验证真实点击中，第二个地图点曾因浏览器自动化坐标落点偏移而选到远处；页面能力已修复覆盖物点击透传，但人工验收仍建议直接在可见 Graph 端点附近点击。
3. 当前 Graph 在新边界发布后已标记过期；生产上需要重新合并发布中心线并重建/激活 Graph。
