# Navigation Engine Execution Receipt Template

日期：2026-05-22

每一轮 Navigation Engine 结束时，最终回复必须按本模板输出执行回执。目标是快速判断本轮是否越界、是否偷跑后续轮次、是否用假路线掩盖数据缺口。

## 执行回执模板

```text
【本轮目标】
- Round:
- 目标摘要:

【实际改动文件】
- 新增:
- 修改:
- 删除:

【明确未改动】
- Python/TypeScript 代码:
- migration:
- requirements/依赖:
- seed 数据和 seed 执行逻辑:
- 数据导入:
- 数据库内容:

【禁止事项自查】
- 是否把 navigation_water_area / boundary polygon 当路径搜索对象: 否 / 是，说明:
- 是否覆盖或重写 seed boundary: 否 / 是，说明:
- 是否让 WATER 默认调用 HiFleet 主链: 否 / 是，说明:
- 是否把 HIFLEET_REFERENCE 发布为正式 centerline: 否 / 是，说明:
- 是否保留或新增水路 fallback 假路线: 否 / 是，说明:
- 是否让未审核 centerline 入 graph: 否 / 是，说明:
- 是否跳过 fixture 或验收说明: 否 / 是，说明:
- 是否未说明 UNKNOWN_CONSTRAINT_DATA 处理: 否 / 是，说明:
- 是否把 MVP/示例/实验数据写入本地演示库、页面默认值、生产 seed 或 active graph: 否 / 是，说明:
- 是否提前实现后续轮次: 否 / 是，说明:

【测试和检查】
- 命令:
- 结果:
- 未运行原因:

【关键结果】
- 本轮完成内容:
- 已知风险:
- 数据缺口:

【下一轮建议】
- 建议 Round:
- 建议开始前需要确认:
```

## 结果判定规则

- 任何 “是” 的禁止事项都必须解释，并说明是否需要回滚或改文档。
- 文档轮允许不运行 pytest，但必须运行或说明文档存在性/关键词检查。
- 实现轮必须跑与改动范围匹配的 focused tests。
- 如果本轮新增了配置、API 或模型，必须说明是否已更新对应文档。
- 如果本轮无法完成验收，不得用“后续优化”掩盖，应列为 blocker。
