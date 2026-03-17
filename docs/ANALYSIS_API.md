# 数据分析模块接口文档

> 更新日期：2026-03-17

---

## 模块概述

数据分析模块（`/api/v1/analysis`）提供仪表盘统计、货源热力、货源趋势、货品排名、船舶热力、船舶类型占比等数据可视化接口。

**设计原则：**
- 所有分析接口**只读统计表**，不直接查询业务主表，保证响应速度 < 200ms
- 统计数据由每日 02:00 的 ETL 定时任务写入统计表
- 支持管理员手动触发统计聚合（用于补数据）

---

## 目录结构

```
app/
├── api/v1/analysis/
│   └── router.py                 # 路由层（7 个接口）
├── services/
│   └── analysis_service.py       # 业务逻辑层
├── repositories/
│   └── analysis_repository.py    # 数据访问层（统计表 CRUD）
├── models/
│   └── analysis.py               # 统计表 ORM 模型（5 张表）
└── tasks/
    └── stat_tasks.py             # ETL 定时任务（每日 02:00）
```

---

## 统计表设计

分析模块使用 5 张统计表，每日由 ETL 任务从业务主表聚合写入：

### 1. `cargo_heatmap_daily` — 货源热力日表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 主键 |
| stat_date | Date | 统计日期 |
| node_id | BigInteger FK | 运输节点 ID（关联 `transport_node`）|
| stat_type | String(16) | `ORIGIN`（装货节点）或 `DEST`（卸货节点）|
| cargo_count | Integer | 货源数量 |
| total_tonnage | DECIMAL(16,2) | 总吨位（吨）|
| created_at / updated_at | DateTime | 时间戳 |

- **唯一约束：** `(stat_date, node_id, stat_type)`
- **数据来源：** `cargo_opportunity` 按节点 + 装卸类型聚合

---

### 2. `ship_heatmap_daily` — 船舶热力日表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 主键 |
| stat_date | Date | 统计日期 |
| node_id | BigInteger FK | 运输节点 ID |
| vessel_count | Integer | 在港/在途船舶数量 |
| total_deadweight | DECIMAL(16,2) | 总载重吨（DWT）|
| created_at / updated_at | DateTime | 时间戳 |

- **唯一约束：** `(stat_date, node_id)`
- **数据来源：** `vessel_dynamic`（AIS 当前位置）JOIN `vessel` 按节点聚合

---

### 3. `cargo_stat_daily` — 货源每日汇总

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 主键 |
| stat_date | Date | 统计日期（每日唯一）|
| total_count | Integer | 当日新增货源总量 |
| active_count | Integer | `CONFIRMED` 状态货源数 |
| pending_count | Integer | `PENDING_CONFIRM` 状态货源数 |
| total_tonnage | DECIMAL(18,2) | 当日新增总吨位（吨）|
| created_at / updated_at | DateTime | 时间戳 |

- **唯一约束：** `stat_date`
- **数据来源：** `cargo_opportunity` 按日期 + 状态聚合
- **用途：** 趋势图、仪表盘核心指标

---

### 4. `cargo_commodity_stat_daily` — 货品分类货源统计

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 主键 |
| stat_date | Date | 统计日期 |
| commodity_category_id | BigInteger FK | 货品大类 ID |
| category_name | String(64) | 货品大类名称（冗余存储）|
| cargo_count | Integer | 货源数量 |
| total_tonnage | DECIMAL(16,2) | 总吨位（吨）|
| created_at / updated_at | DateTime | 时间戳 |

- **唯一约束：** `(stat_date, commodity_category_id)`
- **数据来源：** `cargo_opportunity` → `commodity_standard` → `commodity_type` → `commodity_category`（三层 JOIN）
- **用途：** 货品分类排名饼/柱图

---

### 5. `ship_type_stat_daily` — 船舶类型统计

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 主键 |
| stat_date | Date | 统计日期 |
| vessel_type_id | BigInteger FK | 船舶类型 ID |
| type_name | String(64) | 船舶类型名称（冗余存储）|
| vessel_count | Integer | 船舶数量 |
| total_deadweight | DECIMAL(16,2) | 总载重吨（DWT）|
| created_at / updated_at | DateTime | 时间戳 |

- **唯一约束：** `(stat_date, vessel_type_id)`
- **数据来源：** `vessel` JOIN `vessel_type_dict`（过滤 `data_status=1, is_deleted=0`）
- **用途：** 船舶类型占比饼图

---

## ETL 统计任务

**文件：** `app/tasks/stat_tasks.py`
**触发方式：** APScheduler 每日 02:00 自动执行 / 管理员 API 手动触发

每次执行按顺序运行 5 个子任务，全部成功后统一 commit，失败则 rollback：

### 子任务 1：货源热力聚合（`cargo_opportunity` → `cargo_heatmap_daily`）

```sql
-- ORIGIN 维度（装货节点）
SELECT origin_node_id AS node_id,
       COUNT(id) AS cargo_count,
       COALESCE(SUM(tonnage), 0) AS total_tonnage
FROM cargo_opportunity
WHERE DATE(created_at) = :stat_date
  AND origin_node_id IS NOT NULL
GROUP BY origin_node_id

-- DEST 维度（卸货节点）
SELECT dest_node_id AS node_id, ...
FROM cargo_opportunity
WHERE DATE(created_at) = :stat_date
  AND dest_node_id IS NOT NULL
GROUP BY dest_node_id
```

按装货和卸货两个维度分别聚合，结果 upsert 到 `cargo_heatmap_daily`。

---

### 子任务 2：货源日汇总（`cargo_opportunity` → `cargo_stat_daily`）

```sql
SELECT status,
       COUNT(id) AS cnt,
       COALESCE(SUM(tonnage), 0) AS tonnage
FROM cargo_opportunity
WHERE DATE(created_at) = :stat_date
GROUP BY status
```

Python 层汇总：`total = 所有状态之和`，`active = CONFIRMED 状态`，`pending = PENDING_CONFIRM 状态`。
upsert 到 `cargo_stat_daily`（每日一条）。

---

### 子任务 3：货品分类统计（`cargo_opportunity` + 三表 JOIN → `cargo_commodity_stat_daily`）

```sql
SELECT cc.id AS category_id,
       cc.name AS category_name,
       COUNT(co.id) AS cargo_count,
       COALESCE(SUM(co.tonnage), 0) AS total_tonnage
FROM cargo_opportunity co
JOIN commodity_standard cs ON cs.id = co.commodity_id
JOIN commodity_type ct     ON ct.id = cs.type_id
JOIN commodity_category cc ON cc.id = ct.category_id
WHERE DATE(co.created_at) = :stat_date
  AND co.commodity_id IS NOT NULL
GROUP BY cc.id, cc.name
```

按货品大类维度聚合，将 `category_name` 冗余写入统计表（避免查询时 JOIN）。

---

### 子任务 4：船舶类型快照（`vessel` + `vessel_type_dict` → `ship_type_stat_daily`）

```sql
SELECT vt.id AS type_id,
       vt.name AS type_name,
       COUNT(v.id) AS vessel_count,
       COALESCE(SUM(v.deadweight), 0) AS total_deadweight
FROM vessel v
JOIN vessel_type_dict vt ON vt.id = v.vessel_type_id
WHERE v.data_status = 1
  AND v.is_deleted = 0
GROUP BY vt.id, vt.name
```

统计当日所有**有效船舶**（启用且未删除）的类型分布快照。

---

### 子任务 5：船舶位置热力（`vessel_dynamic` + `vessel` → `ship_heatmap_daily`）

```sql
SELECT vd.current_node_id AS node_id,
       COUNT(v.id) AS vessel_count,
       COALESCE(SUM(v.deadweight), 0) AS total_deadweight
FROM vessel_dynamic vd
JOIN vessel v ON v.id = vd.vessel_id
WHERE v.data_status = 1
  AND v.is_deleted = 0
  AND vd.current_node_id IS NOT NULL
GROUP BY vd.current_node_id
```

基于 AIS 实时位置（`vessel_dynamic.current_node_id`）统计各节点在港/在途船舶数量和总载重。

---

## 接口详细说明

### 1. GET `/api/v1/analysis/dashboard` — 仪表盘统计

**权限：** 登录用户

**功能：** 返回仪表盘 4 个核心指标，数据取当日最新统计。

**查询表：**
- `cargo_stat_daily`：取最新一条（按 `stat_date DESC LIMIT 1`）
- `ship_heatmap_daily`：取最新日期所有节点汇总（`MAX(stat_date)` + `SUM`）

**统计逻辑：**
1. 查 `cargo_stat_daily` 最新一行，取 `total_count`、`active_count`、`pending_count`
2. 查 `ship_heatmap_daily` 中最新日期，对所有节点 `SUM(vessel_count)` 和 `SUM(total_deadweight)`

**响应示例：**
```json
{
  "code": 0,
  "data": {
    "cargo_total": 1280,
    "cargo_active": 960,
    "cargo_pending": 320,
    "active_vessels": 4350
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| cargo_total | int | 当日新增货源总量 |
| cargo_active | int | CONFIRMED 状态货源数 |
| cargo_pending | int | PENDING_CONFIRM 状态货源数 |
| active_vessels | int | 全国在港/在途船舶总数 |

---

### 2. POST `/api/v1/analysis/run-stats` — 手动触发统计聚合

**权限：** ADMIN / SUPER_ADMIN

**功能：** 手动执行 ETL 统计任务，可指定日期（用于历史补跑）。

**Query 参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| target_date | date | 否 | 统计日期，默认今天，格式 `YYYY-MM-DD` |

**统计逻辑：** 串行执行 5 个 ETL 子任务，全成功后 commit，失败则 rollback 并返回错误。

**响应示例：**
```json
{
  "code": 0,
  "message": "统计聚合完成",
  "data": {
    "stat_date": "2026-03-17",
    "cargo_heatmap_nodes": 128,
    "cargo_stat_daily": true,
    "cargo_commodity_stat": true,
    "ship_type_stat": true,
    "ship_heatmap": true
  }
}
```

---

### 3. GET `/api/v1/analysis/cargo/heatmap` — 货源热力图

**权限：** 登录用户

**功能：** 返回各节点货源数量和总吨位，用于地图热力渲染。

**Query 参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| stat_date | date | 否 | 统计日期，默认今天 |
| stat_type | string | 否 | `ORIGIN`（装货）或 `DEST`（卸货），默认 `ORIGIN` |
| region_id | int | 否 | 按区域过滤（内存过滤，通过节点的 `region_id` 字段）|

**查询表：** `cargo_heatmap_daily`（JOIN 加载 `transport_node`）

**统计逻辑：**
1. 按 `stat_date` + `stat_type` 过滤，按 `cargo_count DESC` 排列
2. 关联加载节点坐标（`joinedload`）
3. 若传入 `region_id`，在 Python 层过滤 `node.region_id != region_id` 的记录

**响应示例：**
```json
{
  "code": 0,
  "data": {
    "stat_date": "2026-03-17",
    "items": [
      {
        "node_id": 1001,
        "node_name": "武汉港",
        "cargo_count": 320,
        "total_tonnage": 48000.00,
        "stat_type": "ORIGIN",
        "stat_date": "2026-03-17",
        "longitude": 114.3054,
        "latitude": 30.5931
      }
    ]
  }
}
```

---

### 4. GET `/api/v1/analysis/cargo/trend` — 货源趋势图

**权限：** 登录用户

**功能：** 返回最近 N 天每日货源新增量趋势，用于折线图渲染。

**Query 参数：**
| 参数 | 类型 | 必填 | 默认 | 范围 | 说明 |
|------|------|------|------|------|------|
| days | int | 否 | 30 | 1~365 | 统计天数 |

**查询表：** `cargo_stat_daily`

**统计逻辑：** 查询 `stat_date >= today - (days-1)` 的所有记录，按日期升序返回。

**响应示例：**
```json
{
  "code": 0,
  "data": {
    "days": 30,
    "trend": [
      {
        "date": "2026-02-16",
        "total": 1105,
        "active": 820,
        "pending": 285,
        "tonnage": 165750.00
      },
      {
        "date": "2026-02-17",
        "total": 1280,
        "active": 960,
        "pending": 320,
        "tonnage": 192000.00
      }
    ]
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| date | string | 日期 YYYY-MM-DD |
| total | int | 当日新增货源总量 |
| active | int | CONFIRMED 状态数 |
| pending | int | PENDING_CONFIRM 状态数 |
| tonnage | float | 当日新增总吨位（吨）|

---

### 5. GET `/api/v1/analysis/cargo/commodity_rank` — 货品分类排名

**权限：** 登录用户

**功能：** 返回货品大类货源数量排名（含占比），用于柱状图/饼图渲染。

**Query 参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| stat_date | date | 否 | 统计日期，默认今天 |

**查询表：** `cargo_commodity_stat_daily`

**统计逻辑：**
1. 按 `stat_date` 查询，按 `cargo_count DESC` 排列
2. 计算 `ratio = cargo_count / total_all * 100`，保留 2 位小数

**响应示例：**
```json
{
  "code": 0,
  "data": {
    "stat_date": "2026-03-17",
    "items": [
      {
        "rank": 1,
        "commodity_category_id": 5,
        "category_name": "矿石类",
        "cargo_count": 450,
        "total_tonnage": 90000.00,
        "ratio": 35.16
      },
      {
        "rank": 2,
        "commodity_category_id": 3,
        "category_name": "煤炭类",
        "cargo_count": 320,
        "total_tonnage": 64000.00,
        "ratio": 25.00
      }
    ]
  }
}
```

---

### 6. GET `/api/v1/analysis/ship/heatmap` — 船舶分布热力图

**权限：** 登录用户

**功能：** 返回各节点在港/在途船舶数量及总载重，用于船舶位置热力地图渲染。

**Query 参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| stat_date | date | 否 | 统计日期，默认今天 |
| region_id | int | 否 | 按区域过滤（内存过滤）|

**查询表：** `ship_heatmap_daily`（JOIN 加载 `transport_node`）

**统计逻辑：**
1. 按 `stat_date` 查询，按 `vessel_count DESC` 排列
2. 关联加载节点坐标
3. 若传入 `region_id`，在 Python 层过滤

**响应示例：**
```json
{
  "code": 0,
  "data": {
    "stat_date": "2026-03-17",
    "items": [
      {
        "node_id": 1001,
        "node_name": "武汉港",
        "vessel_count": 85,
        "total_deadweight": 425000.00,
        "stat_date": "2026-03-17",
        "longitude": 114.3054,
        "latitude": 30.5931
      }
    ]
  }
}
```

---

### 7. GET `/api/v1/analysis/ship/type_ratio` — 船舶类型占比

**权限：** 登录用户

**功能：** 返回各船型数量和总载重占比，用于饼图渲染。

**Query 参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| stat_date | date | 否 | 统计日期，默认今天 |

**查询表：** `ship_type_stat_daily`

**统计逻辑：**
1. 按 `stat_date` 查询，按 `vessel_count DESC` 排列
2. 计算 `ratio = vessel_count / total_all * 100`，保留 2 位小数

**响应示例：**
```json
{
  "code": 0,
  "data": {
    "stat_date": "2026-03-17",
    "items": [
      {
        "vessel_type_id": 2,
        "type_name": "散货船",
        "vessel_count": 1850,
        "total_deadweight": 9250000.00,
        "ratio": 42.53
      },
      {
        "vessel_type_id": 1,
        "type_name": "集装箱船",
        "vessel_count": 1200,
        "total_deadweight": 3600000.00,
        "ratio": 27.59
      }
    ]
  }
}
```

---

## 数据流转图

```
业务主表（实时写入）
    │
    │  每日 02:00 ETL 任务
    ▼
┌─────────────────────────────────────────────────────┐
│                     ETL 子任务                       │
│                                                     │
│  cargo_opportunity ──────────► cargo_heatmap_daily  │
│  cargo_opportunity ──────────► cargo_stat_daily     │
│  cargo_opportunity (3层JOIN) ► cargo_commodity_stat │
│  vessel + vessel_type_dict ──► ship_type_stat_daily │
│  vessel_dynamic + vessel ────► ship_heatmap_daily   │
└─────────────────────────────────────────────────────┘
    │
    │  HTTP GET 请求（< 200ms）
    ▼
┌─────────────────────────────────┐
│  Router → Service → Repository  │
│  （只读统计表，不查业务主表）     │
└─────────────────────────────────┘
    │
    ▼
前端可视化（热力图 / 折线图 / 饼图 / 柱状图）
```

---

## 权限矩阵

| 接口 | GUEST | USER | ADMIN | SUPER_ADMIN |
|------|-------|------|-------|-------------|
| GET /dashboard | ✗ | ✓ | ✓ | ✓ |
| POST /run-stats | ✗ | ✗ | ✓ | ✓ |
| GET /cargo/heatmap | ✗ | ✓ | ✓ | ✓ |
| GET /cargo/trend | ✗ | ✓ | ✓ | ✓ |
| GET /cargo/commodity_rank | ✗ | ✓ | ✓ | ✓ |
| GET /ship/heatmap | ✗ | ✓ | ✓ | ✓ |
| GET /ship/type_ratio | ✗ | ✓ | ✓ | ✓ |

---

## 注意事项

1. **数据时效性：** 统计数据每日 02:00 更新，当天白天查询的是昨日统计结果。若需当日实时数据，需联系管理员手动触发 `POST /run-stats`。
2. **region_id 过滤：** 货源热力和船舶热力的 `region_id` 过滤在内存中执行（非数据库层），数据量极大时注意性能。
3. **category_name / type_name 冗余：** 统计表中存储了名称字段，查询时无需 JOIN 字典表，但若字典名称变更，历史统计数据中的名称不会同步更新。
4. **stat_date 默认值：** 所有接口默认取今天的统计数据，若今日 ETL 尚未执行（02:00 前），将返回空数据，建议前端降级显示昨日数据。
