# 一期分析口径设计

## 1. 通用口径
1. 统计对象：仅统计有效数据（未软删 + 状态有效）。
2. 时间基准：默认按 `created_at` 或 `source_message_time` 入统。
3. 统计输出：货源按日报，船舶按快照。

## 2. 货源热力
1. 维度：城市（ORIGIN/DEST）。
2. 指标：`cargo_count`、`total_tonnage`。
3. 数据来源：`cargo_freight`（一期语义=record）。
4. 过滤：`deleted_at is null` 且 `record_status in ('CONFIRMED','ACTIVE')`。

## 3. 货源趋势
1. 维度：天。
2. 指标：总量、确认量、待确认量、总吨位、平均吨位。
3. 数据来源：`cargo_stat_daily`。

## 4. 货品排行
1. 维度：货品大类。
2. 指标：货源数量、总吨位、占比。
3. 数据来源：`cargo_commodity_stat_daily`。

## 5. OD 统计
1. 维度：`origin_city_code -> dest_city_code`。
2. 指标：流量（count）、吨位（sum tonnage）。
3. 数据来源：`cargo_od_daily`。

## 6. 船舶区域热力
1. 维度：商业区域。
2. 指标：船舶数、总载重、占比。
3. 归属优先级：
- `current_region_id`（直接归属）
- 经纬度多边形匹配
- 未匹配归入 UNKNOWN

## 7. 船舶城市热力
1. 维度：城市（可上卷省级）。
2. 指标：船舶数、总载重。
3. 归属优先级：
- `current_city_code`
- 节点映射城市
- 最近城市质心近似

## 8. 载重/船龄分布
1. 载重分布数据源：`vessel.deadweight`。
2. 船龄分布数据源：`vessel.build_year`。
3. 分桶规则在任务代码集中维护（可配置化）。

## 9. AI 解释生成
1. 输入：统计结果数据结构（JSON）。
2. 输出：自然语言结论 + 风险提示 + 数据口径说明。
3. 要求：附带 prompt 模板版本和调用日志 ID。
