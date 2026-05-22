# Navigation Engine MVP Acceptance

日期：2026-05-22

本文定义江苏/长三角 MVP 的业务验收端点、路线、人工验收规则和不可接受结果。它不是全国验收标准，也不代表官方电子航道图能力。

## 1. READY 免责声明

`READY` 只代表：

- 当前 graph version 可用于业务路径搜索。
- 返回路线有 `graph_version_id`、`edge_ids`、`channel_ids`、geometry 和质量评分。
- 路线几何通过当前 water area、boundary 和 graph 质量校验。

`READY` 不代表：

- 官方安全通航确认。
- 实时水深、实时禁航、桥梁净空、船闸计划全部核验。
- 可替代官方电子航道图或船舶安全导航系统。

如果存在 `UNKNOWN_CONSTRAINT_DATA`，结果最高只能是 `READY_WITH_WARNING`。

## 2. MVP 验收端点候选

端点优先使用当前 `transport_node` seed 中可查到的码头、锚地或港口节点。后续 Round 12 若业务指定更精确码头，应在本文件补充 fixture 节点。

| 城市/区域 | node_id | node_code | node_name | lng | lat | 用途 |
| --- | ---: | --- | --- | ---: | ---: | --- |
| 靖江 | 1 | MT202508090010013 | 靖江永益码头 | 120.2193 | 31.94489 | 靖江主验收端点 |
| 靖江 | 3 | MT202508090010014 | 靖江博联码头 | 120.22667 | 31.94446 | 靖江备选端点 |
| 靖江 | 11 | MT202508090010011 | 靖江苏通港务 | 120.34265 | 32.00218 | 长江江苏段端点 |
| 苏州 | 8 | MT202601270010945 | 张家港沙钢 | 120.64344 | 31.96993 | 苏州沿江端点 |
| 苏州 | 103 | MT202508090010035 | 苏州渭塘华东材料 | 120.63105 | 31.4515 | 苏州内河端点 |
| 苏州 | 142 | MT202510150010591 | 吴江港口发展 | 120.66851 | 31.12761 | 苏南内河备选端点 |
| 无锡 | 47 | MT202508090010002 | 江阴长宏国际 | 120.18819 | 31.91705 | 无锡沿江端点 |
| 无锡 | 295 | MD202508090010054 | 无锡惠山锚地 | 120.206125 | 31.606669 | 无锡内河端点 |
| 无锡 | 296 | MT202508090010114 | 江苏江阴港港口集团 | 120.198187 | 31.916579 | 无锡沿江备选端点 |
| 扬州 | 25 | MT202508090010496 | 扬州海昌港务 | 119.81034 | 32.32482 | 扬州主验收端点 |
| 扬州 | 144 | MT202508090010275 | 江苏省扬州港务 | 119.442842 | 32.272907 | 扬州备选端点 |
| 常州 | 37 | MT202508090010018 | 常州中天特钢 | 120.07399 | 31.71087 | 常州内河端点 |
| 常州 | 360 | MT202512120010725 | 常州港 | 119.9942 | 31.96538 | 常州沿江端点 |

## 3. MVP 路线验收集

里程范围先以 `TBD_AFTER_GRAPH_FIXTURE_CALIBRATION` 表示。Round 12 发布 MVP graph 前必须用 fixture 和人工地图核验把范围补成具体数值。未标定前不能把“接口返回路线”作为通过。

| 编号 | 起点 | 终点 | 预期经过航道候选 | 里程范围 | 验收重点 |
| --- | --- | --- | --- | --- | --- |
| MVP-R01 | 靖江永益码头 `1` | 苏州渭塘华东材料 `103` | 长江江苏段、苏南内河、京杭运河/苏申相关航道候选 | TBD_AFTER_GRAPH_FIXTURE_CALIBRATION | 沿江到内河接入是否合理 |
| MVP-R02 | 靖江永益码头 `1` | 无锡惠山锚地 `295` | 长江江苏段、锡澄运河/苏南运河、京杭运河候选 | TBD_AFTER_GRAPH_FIXTURE_CALIBRATION | 靖江到无锡内河连通性 |
| MVP-R03 | 苏州渭塘华东材料 `103` | 扬州海昌港务 `25` | 京杭运河江苏段、苏南运河、长江/内河组合候选 | TBD_AFTER_GRAPH_FIXTURE_CALIBRATION | 苏州到扬州不应画直线跨陆 |
| MVP-R04 | 无锡惠山锚地 `295` | 常州中天特钢 `37` | 京杭运河江苏段、苏南运河、锡溧/丹金溧漕河候选 | TBD_AFTER_GRAPH_FIXTURE_CALIBRATION | 短途内河路径是否沿 graph |
| MVP-R05 | 苏州渭塘华东材料 `103` | 无锡惠山锚地 `295` | 京杭运河江苏段、苏南运河候选 | TBD_AFTER_GRAPH_FIXTURE_CALIBRATION | 京杭运河江苏段局部路径 |
| MVP-R06 | 靖江苏通港务 `11` | 常州中天特钢 `37` | 长江江苏段、苏南内河接入航道候选 | TBD_AFTER_GRAPH_FIXTURE_CALIBRATION | 长江干线到苏南内河码头接入 |

## 4. 不可接受结果

以下任一情况即验收失败：

- 返回直线、贝塞尔曲线或其他 fallback 假水路。
- 没有 `graph_version_id`、`edge_ids` 或 `channel_ids`。
- `provider_code=AUTO` 的 WATER 段调用 HiFleet 作为主链。
- `REFERENCE_HIFLEET` 被自动设为当前业务轨迹版本。
- route geometry 大段穿陆，且没有 `PATH_OUT_OF_WATER` 问题。
- 起终点吸附距离超过 2000m 却仍自动成功。
- 无 approved/current centerline 的航道被构造成 graph。
- 约束缺失却标成完全 `READY`，没有 `UNKNOWN_CONSTRAINT_DATA`。
- graph 不连通时用 polygon/boundary 临时补线。

## 5. 人工地图验收标准

每条 MVP 路线除了自动测试，还必须人工看图：

- 起点和终点 snap 到合理的码头、锚地、港口或附近 graph edge。
- 路线整体沿水域和业务航道边界，不出现明显跨陆直穿。
- 经过航道列表与业务常识相符；无法确认时标记 `NEED_REVIEW`。
- 过闸、过桥、接入码头的位置应在地图上可定位。
- 对未知桥梁净空、船闸计划、水深限制等，前端必须显示风险提示。
- 失败路线要定位失败区域，例如起点无 graph、终点无 graph、graph 断裂、约束阻断。

## 6. Round 12 前必须补齐

Round 12 业务验收前必须把以下字段补成具体值：

```text
expected_distance_km_min
expected_distance_km_max
expected_primary_channel_ids
expected_optional_channel_ids
known_lock_or_bridge_points
manual_map_reviewer
manual_map_reviewed_at
```

如果某条路线数据缺口过大，应保留在验收集中但状态为 `BLOCKED_BY_DATA_GAP`，不能从验收集中静默删除。
