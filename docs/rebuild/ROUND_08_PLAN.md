# Round 08 Plan - Delete Legacy Freight Surface and Split Analysis Dashboard

## Goal

在前端已迁走普通业务消费后，后端开始删除或降级旧 `/freight` 列表面，并继续拆分 `analysis/service.py`，为最终文档删除重生做准备。

## Work Items

0. 本地运行与 seed 入口复核。
   - 检查本地数据库是否为空，区分“seed 未写入”和“后端菜单 seed 仍为旧信息架构”。
   - production seed 必须写入生产主线菜单，前端登录态菜单优先来自 `/auth/me/menus`。
   - 修正文档中未显式传入 `--profile production` 的旧 seed 命令。

1. 旧 `/freight` 接口处置。
   - 盘点是否还有非前端调用依赖旧列表响应。
   - 删除列表响应中大厅展示、分页局部统计和旧后台展示字段。
   - 如果仍需资源选择器，改成明确的内部 selector API，不再作为业务主入口。

2. 拆 `AnalysisDashboardService`。
   - 货源分析、运力分析、区域/流向分析、价格分析分别拆成独立 service。
   - 每个 service 必须围绕业务问题输出 context、metrics、insights、lineage、quality、actions。
   - 新 service 文件小于 800 行，旧 service 只保留编排或兼容导入。

3. 删除直线/样例轨迹风险。
   - 搜索生产分析链路中的 `LOCAL_SAMPLE`、直线 fallback、演示轨迹。
   - 任何生产接口不得把样例或直线作为真实航线依据。

4. 测试。
   - 旧 `/freight` 前端消费为 0。
   - 拆分后所有分析接口响应结构不变。
   - map_state 四态继续通过单测。

## Exit Criteria

- 本地运行页面能显示生产主线菜单，而不是旧后台菜单。
- `/freight` 不再是业务主列表入口。
- `analysis/service.py` 不再承载主要分析业务块。
- 可以进入最终统一文档包重生阶段。
