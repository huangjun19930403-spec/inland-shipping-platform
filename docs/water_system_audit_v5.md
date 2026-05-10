# 水系数据 v5 官方航道体系清洗审计

数据版本：`revier_wgs84_navigation_v5`

来源文件：`/Users/hj/Documents/河道数据/revier.zip`。上线 seed 只读取 `scripts/seed_data/navigation_water_systems_v5.py` 内置压缩数据，不在初始化时重新清洗 Shapefile。

## 官方命名依据

- 交通运输部《全国内河航道与港口布局规划》：两横一纵、两网、十八线作为国家骨干目录。
- 珠江航务管理局水系简介：珠江由西江、北江、东江及珠江三角洲水网组成，珠三角水道作为增强目录。
- 江苏两纵五横、浙江内河航道布局、上海一环十射、黑龙江水路规划等公开资料：作为区域增强目录。

## v5 清洗口径

- 全部 `一级水系` 至 `七级水系` 面要素进入离线候选池和逐条审计，共 `39431` 个源要素。
- seed 主数据采用“官方航道/水系目标名称 + revier 面边界集合”，不再按 Shapefile 单要素建业务水系。
- 精确/别名命名匹配优先；低等级或无名面要素若与已命中官方目标边界 5km 内邻近，则作为 `SPATIAL_CARRIER` 合入。
- 干河床、消失河、排水沟、灌渠、明显非航运小型水库等不作为正式航道；个别用于解释通道连续性的对象标记为 `LOW_CONFIDENCE_CARRIER`。
- `geometry_json` 保持 WGS84 用于后端 AIS 点面匹配；`boundary_paths_low/medium/high` 和展示中心为 GCJ-02，用于高德地图展示。
- 长江干线、京杭运河、钱塘江、太湖、松花江等超长或复合承载对象使用人工业务展示中心，避免 bbox 中心或船位算术均值被低等级承载面、长距离弯曲河段拉偏；态势聚合气泡优先使用业务展示中心，实时船位热力中心仅作兜底解释。
- 这些边界只用于 AIS 水域归属、态势展示和空间背景，不代表官方航道等级、尺度、中心线、里程或通航条件。

## 统计

- seed 行数：`120`
- 有边界对象：`111`
- 航运分层：`{'CORE': 12, 'IMPORTANT': 79, 'MISSING': 9, 'REVIEW': 2, 'WATER_AREA': 18}`
- 水系类别：`{'CANAL': 31, 'DELTA_NETWORK': 15, 'LAKE': 18, 'MAIN_RIVER': 16, 'TRIBUTARY': 40}`
- AIS 态势范围：`{'EXCLUDED': 11, 'INCLUDED': 109}`
- 源要素归并/排除：`{'ALIAS': 1157, 'EXACT': 255, 'EXCLUDED': 7894, 'NOT_INCLUDED': 24338, 'REVIEW': 6, 'SPATIAL_CARRIER': 5781}`

## 重点目标核对

| 目标 | 状态 | 来源要素数 | 边界质量 | 说明 |
|---|---:|---:|---|---|
| 长江干线 | AVAILABLE | 1800 | MEDIUM_CONFIDENCE | 清洗自 revier.zip 全等级水系面边界，可用于 AIS 水系态势和水域空间归属；不代表官方航道等级、通航尺度、航道中心线或航线规划依据。；含低等级/无名水系面边界作为空间承载补强，不代表官方航道边界、等级或中心线。 |
| 西江航运干线 | AVAILABLE | 113 | HIGH_CONFIDENCE | 清洗自 revier.zip 全等级水系面边界，可用于 AIS 水系态势和水域空间归属；不代表官方航道等级、通航尺度、航道中心线或航线规划依据。；含低等级/无名水系面边界作为空间承载补强，不代表官方航道边界、等级或中心线。 |
| 京杭运河 | AVAILABLE | 81 | MEDIUM_CONFIDENCE | 清洗自 revier.zip 全等级水系面边界，可用于 AIS 水系态势和水域空间归属；不代表官方航道等级、通航尺度、航道中心线或航线规划依据。；含低等级/无名水系面边界作为空间承载补强，不代表官方航道边界、等级或中心线。 |
| 淮河出海航道—盐河 | AVAILABLE | 6 | CARRIER_COMPOSITE | 以 revier.zip 全等级可追溯自然水系面作为航道相关水域近似承载，用于 AIS 水域归属和态势展示，不代表官方航道边界、等级、尺度、中心线或里程。 |
| 连申线 | AVAILABLE | 11 | CARRIER_COMPOSITE | 以 revier.zip 全等级可追溯自然水系面作为航道相关水域近似承载，用于 AIS 水域归属和态势展示，不代表官方航道边界、等级、尺度、中心线或里程。 |
| 杭甬运河 | AVAILABLE | 10 | CARRIER_COMPOSITE | 以 revier.zip 全等级可追溯自然水系面作为航道相关水域近似承载，用于 AIS 水域归属和态势展示；不代表官方航道边界、等级、尺度、中心线或里程。；含低等级/无名水系面边界作为空间承载补强，不代表官方航道边界、等级或中心线。 |
| 杭申线 | AVAILABLE | 17 | CARRIER_COMPOSITE | 以 revier.zip 全等级可追溯自然水系面作为航道相关水域近似承载，用于 AIS 水域归属和态势展示；不代表官方航道边界、等级、尺度、中心线或里程。；含低等级/无名水系面边界作为空间承载补强，不代表官方航道边界、等级或中心线。 |
| 太浦河 | AVAILABLE | 3 | CARRIER_COMPOSITE | 长三角航道网相关水域。；含低等级/无名水系面边界作为空间承载补强，不代表官方航道边界、等级或中心线。 |
| 望虞河 | AVAILABLE | 6 | CARRIER_COMPOSITE | 江苏干线航道网相关水域。；含低等级/无名水系面边界作为空间承载补强，不代表官方航道边界、等级或中心线。 |
| 德胜河 | AVAILABLE | 1 | PRECISE_SOURCE | 江苏干线航道网相关水域。 |
| 南淝河 | AVAILABLE | 4 | LOW_CONFIDENCE_CARRIER | 按安徽合裕线公开航道名称，用南淝河并追溯巢湖、裕溪河作为近似承载边界；不代表官方航道边界或等级。；含低等级/无名水系面边界作为空间承载补强，不代表官方航道边界、等级或中心线。 |
| 乌苏里江 | AVAILABLE | 40 | CARRIER_COMPOSITE | 黑龙江水路体系重要边境河流。；含低等级/无名水系面边界作为空间承载补强，不代表官方航道边界、等级或中心线。 |
| 蕉门水道 | AVAILABLE | 1 | PRECISE_SOURCE | 珠三角高等级航道网出海水道。 |
| 横门水道 | AVAILABLE | 8 | CARRIER_COMPOSITE | 珠三角高等级航道网出海水道。；含低等级/无名水系面边界作为空间承载补强，不代表官方航道边界、等级或中心线。 |
| 小榄水道 | AVAILABLE | 1 | CARRIER_COMPOSITE | 珠三角高等级航道网水道。；含低等级/无名水系面边界作为空间承载补强，不代表官方航道边界、等级或中心线。 |
| 虎跳门水道 | AVAILABLE | 1 | PRECISE_SOURCE | 珠三角高等级航道网出海水道。 |

## 全源要素审计

逐条 assignment 写入 `docs/water_system_source_assignment_v5.jsonl`，每行包含：`source_layer`、`source_level`、`object_id`、`name`、`remark`、`assignment_status`、`assignment_reason`、`target_water_system_code`、`target_water_system_name`、`secondary_trace_targets`。

未进入 seed 的源要素不会静默丢弃，原因主要包括：`LOW_VALUE_TERM`、`SALINE_LAKE_OUTSIDE_NAVIGATION_SCOPE`、`RESERVOIR_NOT_NAVIGATION_TARGET`、`NO_OFFICIAL_TARGET_WITHIN_5KM`。

## 历史未知样本复核

对 `/private/tmp/water_v3_unknown2.json` 中 36 艘历史未知水系船位，用 v5 seed 后端匹配逻辑复核：

- v5 命中：`33/36`。
- 剩余未知：`3/36`，分别位于湖州 `120.401113,30.710943`、苏州 `121.127107,31.599620`、苏州 `121.126807,31.599967`。
- 剩余 3 个点用 `一级` 至 `七级` revier 源边界全量复扫，5km 内无可用源水系边界候选；其中两个苏州点距离最近长江源边界约 9.2km，湖州点 10km 内无候选。
- 无锡样本 `120.242867,31.737067` 距七级淡水湖 `L7-17113` 约 3.8km，已作为 `SPATIAL_CARRIER` 合入 `锡澄运河`，匹配结果从未知修正为近边界归属。
