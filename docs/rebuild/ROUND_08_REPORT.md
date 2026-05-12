# Round 08 Report - Legacy Freight Entry Removal And Seed Menu Fix

## Scope

本轮不是最终收尾轮，而是最终文档重生前的删除式收口轮。重点处理本地运行页未变化的问题、旧货源列表入口残留，以及运输机会页面仍混用旧后台文案的问题。

## Completed

1. 确认本地库不是空库。
   - 本地库已有货源、船舶、水系、行政区划等 seed 数据。
   - 页面未变化的主因是 `sys_menu` 仍为旧后台信息架构，前端登录后优先使用 `/auth/me/menus`，不会使用静态兜底菜单。

2. 修复 production 菜单 seed。
   - `seed_system_base` 将顶层菜单收敛为：经营总览、货源洞察中心、运力中心、航线与区域中心、运价与报价中心、数据质量与治理、系统配置。
   - 同步修复数据治理员、运营分析员、业务录入员的菜单授权，避免非管理员缺父级菜单。
   - 已在本地执行 `python -m scripts.seed_system_init --profile production`，页面刷新后新菜单生效。

3. 删除旧货源列表业务入口。
   - 前端删除 `fetchFreights`，普通业务消费只保留 `fetchShippingOpportunities`。
   - 后端删除旧 `GET /api/v1/freight` 列表路由、对应 query schema、service/repository 列表方法。
   - 新增测试确认 `/api/v1/freight` 不再暴露 GET，业务列表入口为 `/api/v1/freight/opportunities`。

4. 收敛运输机会页面文案。
   - 货源列表页改为“运输机会”。
   - 删除“当前页发布货量”“当前页采集确认”局部统计卡，只保留后端返回的筛选结果总数。
   - 驾驶舱、候选确认、微信采集、船货适配筛选等前端入口统一改为“运输机会”。

5. 修正 seed 文档。
   - README 和 seed 文档改为显式 `--profile production`。
   - 明确 `local-demo` 只用于本地演示链路。

## Verification

- `py_compile scripts/seed_system_base.py` 通过。
- 菜单 seed、旧 `/freight` GET 删除相关单测通过。
- 前端 `npm run type-check` 通过。
- 前端 `npm run build` 通过。
- `GET /api/v1/freight` 本地返回 404，`GET /api/v1/freight/opportunities` 仍进入认证保护链。
- 本地 production seed 已成功写入数据库。
- 浏览器刷新本地前端后，左侧菜单已显示生产主线。

## Next

下一轮应进入最终统一文档包重生与验收：

- 删除旧沉积文档或迁入归档区。
- 生成统一 README、产品说明、架构、数据库、API、前端、seed、部署、验收文档。
- 全量运行后端测试、前端 type-check/build，并复核本地页面核心链路。
