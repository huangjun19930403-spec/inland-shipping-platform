# Navigation Engine Centerline And Graph Rules

日期：2026-05-22

本文冻结中心线生产和 graph 构建的执行规则。后续实现必须先满足本文，再写导入脚本、graph builder 或 routing engine。核心原则是：中心线是 graph 的唯一几何来源，graph edge 是路径搜索的唯一对象；polygon、water area、boundary 都不能被当成路线。

## 1. 不可突破的硬规则

- 第一阶段进入 graph 的中心线只允许来自 `MANUAL`、`SEED_CENTERLINE`、已审核的 `OSM_WATERWAY`。
- `AIS_INFERRED` 是第二阶段增强来源，第一阶段只允许作为参考或待审核候选。
- `WATER_SKELETON` 和 `HIFLEET_REFERENCE` 永远不能自动发布为正式中心线。
- 无 `review_status_code=APPROVED` 且 `is_current=True` centerline 的航道不得进入 graph。
- 路径搜索只能基于 `navigation_graph_edge`。
- `navigation_water_area` 和 `navigation_channel_boundary` 只用于展示、候选生成、空间约束和质量校验，不能当路线。
- graph 构建发现不确定交汇、疑似错连、断点、重复线时，必须降级为 `NEED_REVIEW` 或生成 annotation task，不能猜测发布为 `READY`。

## 2. 江苏 MVP 中心线来源策略

第一阶段江苏/长三角 MVP 的主源顺序：

| 优先级 | 来源 | 第一阶段用途 | 是否可直接入 graph |
| --- | --- | --- | --- |
| 1 | `MANUAL` | 人工绘制和人工校验后的主线、支线、码头接入线 | 可以，必须 `APPROVED/current` |
| 2 | `SEED_CENTERLINE` | 未来随 seed 提供的中心线资产 | 可以，必须 `APPROVED/current` |
| 3 | `OSM_WATERWAY` | OSM river/canal 候选线，补充人工线不足 | 只有审核通过后可以 |
| 4 | `AIS_INFERRED` | 第二阶段用真实轨迹校准和补缺边 | 第一阶段不得自动入 graph |
| 5 | `HYDRORIVERS` | 自然河流方向参考 | 不直接入江苏 MVP graph |
| 6 | `WATER_SKELETON` | 无线源时从 polygon 抽候选骨架 | 不得自动发布 |
| 7 | `HIFLEET_REFERENCE` | 与外部结果对比、辅助人工判断 | 不得自动发布 |

第一阶段真实可用 graph 的瓶颈是中心线，而不是 river polygon。开发时如果某航道只有 water area 或 boundary，正确结果是 `NO_APPROVED_CENTERLINE`，不是从面数据临时画线。

## 3. 人工中心线 GeoJSON 格式

导入脚本应接受 `FeatureCollection`，每个 feature 表示一条候选中心线。几何必须是 WGS84 `LineString`；`MultiLineString` 必须在导入前或导入时拆成多条 `LineString`，并保留同一个 `source_group_id`。

示例：

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {
        "centerline_code": "JS-MANUAL-YANGTZE-JJ-001",
        "centerline_name": "长江江苏段靖江段人工中心线",
        "channel_code": "CN-JS-YANGTZE",
        "segment_code": "optional",
        "source_type_code": "MANUAL",
        "direction_code": "BIDIRECTIONAL",
        "is_main_line": true,
        "review_status_code": "APPROVED",
        "quality_code": "READY",
        "confidence_score": 95,
        "version_no": 1,
        "source_group_id": "manual_batch_20260522",
        "source_operator": "manual",
        "source_trace": "人工沿底图和业务航道边界绘制",
        "notes": "optional"
      },
      "geometry": {
        "type": "LineString",
        "coordinates": [
          [120.2193, 31.94489],
          [120.34265, 32.00218]
        ]
      }
    }
  ]
}
```

必填属性：

```text
centerline_code
channel_code 或 channel_id
source_type_code
direction_code
review_status_code
quality_code
confidence_score
version_no
geometry LineString
```

导入校验：

- 坐标顺序必须是 `[lng, lat]`。
- 点数必须大于等于 2。
- `confidence_score` 范围是 0-100。
- `source_type_code=MANUAL/SEED_CENTERLINE` 且 `review_status_code=APPROVED` 才能在第一阶段直接进入 graph。
- 未能解析 channel 的 feature 标记 `CHANNEL_NOT_RESOLVED`，不得入库为 current。
- 超出 active boundary 或明显离开 water area 的 feature 标记 `OUT_OF_BOUNDARY` 或 `NEED_REVIEW`。

## 4. OSM Waterway 归属规则

OSM 线归属到航道时必须同时考虑名称和空间，不允许只靠 `name`。

归属顺序：

1. `name` 与 `channel_name/official_name/alias_names` 精确匹配。
2. `name` 包含匹配，并通过省市范围或 channel boundary 限定。
3. 无名称线只能作为空间候选：必须位于 channel boundary 内或 boundary 外扩阈值内。
4. 对没有 boundary 的规划航道，OSM 线只能进 `NEED_REVIEW`，除非有人工 corridor 配置。
5. 同一条 OSM 线可被多个 channel 命中时，必须进入冲突报告，由人工拆分或指定归属。

建议阈值：

```text
boundary containment ratio >= 0.80: 可作为候选
boundary buffer distance <= 100m: 可作为候选
name/alias 未命中但空间命中: NEED_REVIEW
跨多个 channel 且无法拆分: DUPLICATED / NEED_REVIEW
```

OSM 候选默认 `source_type_code=OSM_WATERWAY`、`review_status_code=NEED_REVIEW`。只有人工审核后才能设置为 `APPROVED/current`。

## 5. 候选中心线去重和合并

去重必须在米制投影下计算，不能直接用经纬度度数判断距离。

同一 channel 内的重复判断：

```text
重叠长度比例 >= 0.80 且平均距离 <= 20m: 认为重复候选
重叠长度比例 >= 0.60 且平均距离 <= 50m: 标记疑似重复 NEED_REVIEW
端点距离 <= 20m 且方向一致: 可 snap 端点
平行线距离 <= 30m 但来源不同: 不自动删除，标记 PARALLEL_CANDIDATE
```

保留来源优先级：

```text
MANUAL
SEED_CENTERLINE
AIS_INFERRED approved
OSM_WATERWAY approved
HYDRORIVERS
WATER_SKELETON
HIFLEET_REFERENCE
```

合并规则：

- 只能合并同一 channel、方向兼容、审核状态兼容的中心线。
- `APPROVED/current` 不能被未审核候选覆盖。
- 被合并或停用的候选保留历史记录，`quality_code=DUPLICATED` 或 `review_status_code=REJECTED`。
- 合并结果必须写入 `source_trace_json`，记录参与候选、合并阈值和人工审核人。

## 6. Graph 构建输入门槛

graph builder 只读取：

```text
navigation_channel_centerline.review_status_code = APPROVED
navigation_channel_centerline.is_current = true
navigation_channel_centerline.quality_code in (READY, READY_WITH_WARNING)
navigation_channel.routing_enabled = true
```

禁止读取：

- 未审核 OSM 候选。
- `WATER_SKELETON` 候选。
- `HIFLEET_REFERENCE` 线。
- 只有 boundary 或 water area、没有中心线的 channel。

无合格中心线时 graph builder 必须输出：

```text
NO_APPROVED_CENTERLINE
```

## 7. 交汇和切分规则

中心线切分点来源：

- 线端点。
- 真实可通航交汇点。
- 码头/港口/锚地接入点。
- 船闸、桥梁、浅滩等约束点。
- 人工标注断点或连接点。

近距交汇规则：

```text
线端点距离另一条线 <= 20m: 可自动 snap，但必须记录 snap_distance_m
20m < 距离 <= 80m: 生成 candidate junction，quality=NEED_REVIEW
距离 > 80m: 不自动连接
```

线线相交规则：

- 两条中心线几何相交不等于可通航交汇。
- 同一 channel 或配置了 `allowed_junction` 的不同 channel，可创建 `CHANNEL_JUNCTION` node。
- 跨河桥、立交、不同水体投影相交但无通航连通关系时，不创建可路由 junction；生成 `CROSSING_NOT_NAVIGABLE` 质量问题。
- 来源不可靠或角度异常的交叉点默认 `NEED_REVIEW`。

## 8. 码头接入规则

码头、港口、锚地来自 `TransportNode`。自动接入必须基于距离和空间关系。

建议阈值：

```text
0-200m: 可自动创建 SNAP_CONNECTOR edge，quality=READY 或 READY_WITH_WARNING
200-500m: 创建候选 SNAP_CONNECTOR，quality=NEED_REVIEW
>500m: 不自动接入，生成 NO_GRAPH_NEAR_TRANSPORT_NODE
```

接入 edge 规则：

- `node_type_code=PORT/TERMINAL/ANCHORAGE` 的节点连接到最近 centerline split point。
- 接入线 `edge.source_type_code=SNAP_CONNECTOR`。
- 接入线必须检查是否大段穿陆；不满足时 `PATH_OUT_OF_WATER/NEED_REVIEW`。
- 若码头与 channel 有人工绑定，优先绑定 channel；否则按最近 approved centerline 候选，并写入 `snap_confidence`。

## 9. 船闸、桥梁和约束点规则

船闸、桥梁既可以是 graph node，也可以产生 constraint。

船闸：

- `NavigationConstraintPoint` 类型为 lock 时，snap 到 centerline 后创建 `node_type_code=LOCK`。
- 穿过该 node 的 edge 设置 `lock_required=true` 或生成 `LOCK_SCHEDULE` constraint。
- 船闸尺度、排队或时间窗缺失时生成 `UNKNOWN_CONSTRAINT_DATA`。

桥梁：

- bridge point snap 到 edge 后创建 `node_type_code=BRIDGE`。
- 净空、宽度、通行时间等写入 edge constraint。
- 缺净空时不禁用 edge，但产生 `UNKNOWN_CONSTRAINT_DATA` 并限制结果最高为 `READY_WITH_WARNING`。

浅滩、限宽、禁航等：

- 点状数据先 snap 到 edge。
- 若规则影响一段航道，应转换为 `navigation_graph_edge_constraint`。
- 命中 blocking 约束时禁用 edge。

约束点距离中心线超过 100m 时不得自动 snap，必须生成 `CONSTRAINT_POINT_NOT_SNAPPED`。

## 10. 断点识别和修复建议

断点类型：

```text
UNCONNECTED_ENDPOINT
CHANNEL_GAP
PORT_NOT_CONNECTED
LOCK_NOT_CONNECTED
ISOLATED_SUBGRAPH
```

识别规则：

- 非终点 centerline endpoint 没有连接 edge，标记 `UNCONNECTED_ENDPOINT`。
- 同一 channel 两个 endpoint 距离 `20-200m` 且方向一致，生成 `MANUAL_CONNECTOR` 候选，默认 `NEED_REVIEW`。
- 距离 `<=20m` 的同 channel 小缝隙可以自动 snap，但要写入修复报告。
- 距离 `>200m` 不自动补线，只生成 annotation task。

断点修复不得直接覆盖历史 centerline；必须生成新 centerline 版本或 connector 候选，再 rebuild graph。

## 11. Edge 去重、短边合并和方向

重复 edge：

- 同一 graph version 内，from/to node 相同且 geometry 重叠比例 `>=0.90`，保留质量更高或来源优先级更高的 edge。
- 被停用 edge 标记 `quality_code=DUPLICATED`、`routing_enabled=false`。

短边合并：

```text
length < 20m 且中间 node 不是 LOCK/BRIDGE/PORT/TERMINAL/JUNCTION/CONSTRAINT: 可合并
length < 20m 但中间 node 是约束或业务节点: 不合并
20m-50m: 标记 SHORT_EDGE_REVIEW，除非人工确认
```

方向判定：

- 默认 `BIDIRECTIONAL`。
- 只有官方、人工或明确规则提供单向信息时，才设置 `FORWARD_ONLY/REVERSE_ONLY`。
- LineString 坐标方向定义为 forward；构建 bidirectional graph 时生成两个可搜索方向或在搜索层显式处理反向。
- 方向不确定但来源声称单向时，标记 `DIRECTION_NEED_REVIEW`。

## 12. Graph 质量标记

graph builder 必须把问题写到 edge/node/version 报告，不允许只打印日志。

常见质量码：

```text
READY
READY_WITH_WARNING
NEED_REVIEW
BROKEN
OUT_OF_BOUNDARY
LOW_CONFIDENCE
DUPLICATED
DISABLED
UNKNOWN_CONSTRAINT_DATA
CROSSING_NOT_NAVIGABLE
SHORT_EDGE_REVIEW
```

发布门槛：

- 含 blocking disconnected issue 的 graph version 不能 `READY`。
- 含大量未知约束或待复核 connector 的 graph version 最高 `READY_WITH_WARNING` 或 `NEED_REVIEW`。
- `READY` 只表示业务路径图和几何结果可用，不代表官方安全通航确认。
