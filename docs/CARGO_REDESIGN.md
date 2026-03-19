# 货源模块优化方案

> 版本：v2.0
> 状态：已实施
> 日期：2026-03-17

---

## 一、背景与问题

原始设计中 `CargoOpportunity` 强依赖 `transport_node`（NOT NULL），导致：

1. **TMS渠道** 无法直接导入：TMS坐标与项目节点不精确对应
2. **AI解析渠道** 城市/港口/运河名称无法精确匹配节点，只能存原文，无法统计
3. **统计体系** 基于节点级热力（每日ETL T+1），实时性差，且依赖强耦合
4. **分析维度单一**：缺少OD流量矩阵和渠道质量分析

---

## 二、优化目标

- 支持三路录入渠道（TMS / WeChat AI解析 / 手工录入）
- 多精度位置存储（节点级 / 城市级 / 坐标级 / 原文）
- 统计从 T+1 ETL 升级为写入事件驱动实时刷新
- 新增 OD流量矩阵 和 渠道质量统计 两个分析维度
- 热力图从节点级升级为城市级

---

## 三、数据模型重设计

### 3.1 删除的表

| 表名 | 原因 |
|------|------|
| `cargo_opportunity` | 强依赖节点，替换为 `cargo_freight` |
| `cargo_heatmap_daily` | 节点级，替换为城市级 `cargo_city_heatmap` |

### 3.2 新增的表

#### `cargo_freight`（货源主表）

替换 `cargo_opportunity`，核心改进：

```sql
-- 位置字段（以装货地为例，卸货地对称）
origin_node_id       BIGINT NULL        -- 节点级（可空）
origin_admin_code    VARCHAR(12) NULL   -- 城市行政区划代码（统计主维度）
origin_admin_name    VARCHAR(50) NULL   -- 城市名称（冗余）
origin_region_id     BIGINT NULL        -- 商业区域（可选）
origin_longitude     DECIMAL(11,8) NULL -- 坐标经度
origin_latitude      DECIMAL(10,8) NULL -- 坐标纬度
origin_raw_text      VARCHAR(200) NULL  -- AI/TMS原始文本
origin_precision     VARCHAR(12)        -- NODE/CITY/COORDINATE/UNKNOWN

-- 来源追踪
source_type          VARCHAR(20)        -- TMS/WECHAT_AI/MANUAL
tms_external_id      VARCHAR(100) UNIQUE NULL  -- TMS原始单号（幂等键）
raw_message_id       BIGINT NULL        -- WeChat原始消息
parse_result_id      BIGINT NULL        -- AI解析结果
```

**位置精度（origin_precision）说明：**

| 精度值 | 含义 | 来源 |
|--------|------|------|
| `NODE` | 已精确关联到 transport_node | 任意渠道（节点匹配成功） |
| `CITY` | 城市级，已关联到 admin_region | AI解析/TMS模糊匹配/MANUAL城市录入 |
| `COORDINATE` | 仅有坐标，无法匹配 | TMS有坐标但节点匹配失败 |
| `UNKNOWN` | 无任何位置信息 | AI未提取/用户未填写 |

#### `tms_cargo_raw`（TMS原始报文暂存表）

```sql
tms_message_id   VARCHAR(100) UNIQUE  -- TMS唯一ID（幂等控制）
raw_payload      JSON                  -- TMS原始报文快照
tms_origin_name  VARCHAR(200)          -- TMS装货地名称
tms_origin_lng   DECIMAL(11,8)         -- TMS装货地经度
tms_origin_lat   DECIMAL(10,8)         -- TMS装货地纬度
matched_origin_node_id BIGINT NULL     -- 本系统节点匹配结果
matched_origin_admin_code VARCHAR(12)  -- 本系统城市匹配结果
match_strategy   VARCHAR(50)           -- NAME_EXACT/NAME_FUZZY/PROXIMITY/REGION/FALLBACK
match_confidence SMALLINT              -- 匹配置信度 0-100
process_status   VARCHAR(20)           -- PENDING/MATCHED/IMPORTED/FAILED
freight_id       BIGINT NULL           -- 成功导入后的cargo_freight.id
```

#### `cargo_city_heatmap`（城市级货源热力统计）

```sql
stat_date        DATE
city_code        VARCHAR(12)    -- 行政区划代码
city_name        VARCHAR(50)
city_longitude   DECIMAL(11,8)  -- 城市中心坐标
city_latitude    DECIMAL(10,8)
stat_type        VARCHAR(8)     -- ORIGIN/DEST
cargo_count      INT
total_tonnage    DECIMAL(16,2)
UNIQUE KEY (stat_date, city_code, stat_type)
```

#### `cargo_od_daily`（OD流量矩阵，新增）

```sql
stat_date           DATE
origin_city_code    VARCHAR(12)
origin_city_name    VARCHAR(50)
dest_city_code      VARCHAR(12)
dest_city_name      VARCHAR(50)
cargo_count         INT
total_tonnage       DECIMAL(16,2)
UNIQUE KEY (stat_date, origin_city_code, dest_city_code)
```

#### `cargo_channel_daily`（渠道质量统计，新增）

```sql
stat_date            DATE
source_type          VARCHAR(20)   -- TMS/WECHAT_AI/MANUAL
raw_msg_count        INT           -- 原始消息/消费数量
parse_success_count  INT           -- AI解析成功数（WECHAT_AI专用）
confirmed_count      INT           -- 最终确认货源数
total_tonnage        DECIMAL(16,2)
UNIQUE KEY (stat_date, source_type)
```

---

## 四、三路录入渠道设计

### 4.1 TMS渠道（结构化数据，坐标精确）

```
TMS系统 → Redis Stream (tms.cargo.available)
         → app/consumers/tms_cargo_consumer.py
         → tms_cargo_raw（幂等暂存）
         → 节点匹配（NAME_EXACT > NAME_FUZZY > PROXIMITY > REGION > FALLBACK）
         → cargo_freight (source_type=TMS, audit_status=1自动审核通过)
         → refresh_cargo_stats() （事件驱动统计刷新）
```

**节点匹配策略（按优先级）：**

| 策略 | 方式 | 置信度 |
|------|------|--------|
| `NAME_EXACT` | 节点名称精确匹配 | 95 |
| `NAME_FUZZY` | 节点名称模糊匹配（contains） | 75 |
| `PROXIMITY` | 坐标±0.1°范围内最近节点 | 60 |
| `REGION` | 区域名匹配 AdminRegion（城市级回退） | 50 |
| `FALLBACK` | 仅保留坐标 | 20 |

### 4.2 WeChat AI解析渠道（非结构化文本）

```
微信群文本 → POST /freight/text（提交）
           → trigger_cargo_parse（后台AI解析）
           → CargoParseWorkflow
               Stage1: 标记PARSING
               Stage2: CargoAgent（LLM提取 + 实体匹配）
               Stage3: 写入 cargo_ai_parse_result
               Stage4: 标记PARSED
           → 操作员人工确认：POST /freight/parse-result/{id}/confirm
           → cargo_freight (source_type=WECHAT_AI)
           → refresh_cargo_stats()
```

**AI解析结果字段（已修复）：**

- `dest_text`（原错误写为 `destination_text`）
- `commodity_id`（原错误写为 `commodity_standard_id`）
- `contact_person`（原错误写为 `contact`）
- `parse_status`（原错误写为 `status`）
- `origin_candidates` / `dest_candidates` / `commodity_candidates`（原合并为 `candidates_json`）

### 4.3 手工录入渠道（操作员直接录入）

```
操作员 → POST /freight/freight
       → CargoService.create_manual_freight()
       → cargo_freight (source_type=MANUAL)
       → refresh_cargo_stats()
```

**支持位置精度：**
- 节点级：填写 `origin_node_id` / `dest_node_id`
- 城市级：填写 `origin_admin_code` / `dest_admin_code`
- 两者均可混用（如装货节点级 + 卸货城市级）

---

## 五、统计体系重设计

### 5.1 货源统计：事件驱动（替代T+1 ETL）

| 旧设计 | 新设计 |
|--------|--------|
| 每日02:00 ETL批处理 | 写入事件后立即触发 BackgroundTask |
| 节点级热力（cargo_heatmap_daily） | 城市级热力（cargo_city_heatmap） |
| 无OD统计 | cargo_od_daily（起终点城市OD矩阵） |
| 无渠道统计 | cargo_channel_daily（TMS/AI/手工质量） |

触发方式：
```python
# 货源确认/录入后
background_tasks.add_task(refresh_cargo_stats, date.today())
```

`refresh_cargo_stats()` 一次刷新5张统计表：
1. `cargo_city_heatmap` — 城市热力
2. `cargo_stat_daily` — 每日汇总
3. `cargo_commodity_stat_daily` — 货品分类
4. `cargo_od_daily` — OD矩阵
5. `cargo_channel_daily` — 渠道质量

### 5.2 船舶统计：保持每日定时任务

AIS数据本身为周期性快照，无需实时刷新：
- `ship_heatmap_daily`：每日02:00更新节点级船舶分布
- `ship_type_stat_daily`：每日02:00更新船型占比

---

## 六、分析接口设计

### 6.1 货源城市热力图
```
GET /analysis/cargo/heatmap?stat_date=2024-06-01&stat_type=ORIGIN
```
返回含城市经纬度的热力数据，前端使用 AMap/Leaflet 渲染热力层。

### 6.2 货源趋势图
```
GET /analysis/cargo/trend?days=30
```
返回每日 total/confirmed/pending/tonnage 四条时序，前端渲染多轴折线图。

### 6.3 货品分类排名
```
GET /analysis/cargo/commodity_rank?stat_date=2024-06-01
```
返回货品大类排名及占比，前端渲染横向柱状图或饼图。

### 6.4 OD流量矩阵（新增）
```
GET /analysis/cargo/od_flow?days=7&top_n=20
GET /analysis/cargo/od_flow?stat_date=2024-06-01&top_n=20
```
返回 Top N 起终点城市对的货源数量和吨位：
- **Sankey 桑基图**：origin → dest，节点宽度按 cargo_count
- **路线排行榜**：表格展示最热门航线

### 6.5 渠道质量统计（新增）
```
GET /analysis/cargo/channel_stats?stat_date=2024-06-01   # 单日模式
GET /analysis/cargo/channel_stats?days=30                # 趋势模式
```
- **单日模式**：三渠道对比卡片（消息数、解析率、确认数）
- **趋势模式**：堆叠面积图，Y轴按渠道堆叠 confirmed_count

---

## 七、文件变更清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `app/models/cargo.py` | 重建 | 删除CargoOpportunity，新增CargoFreight、TmsCargoRaw；更新CargoAiParseResult |
| `app/models/analysis.py` | 重建 | 删除CargoHeatmapDaily，新增CargoCityHeatmap、CargoOdDaily、CargoChannelDaily |
| `app/repositories/cargo_repository.py` | 重建 | 替换所有CargoOpportunity方法为CargoFreight方法 |
| `app/repositories/analysis_repository.py` | 重建 | 替换节点级热力方法，新增OD/渠道upsert方法 |
| `app/services/cargo_service.py` | 重建 | 使用CargoFreight，confirm流程生成货源而非机会 |
| `app/services/analysis_service.py` | 重建 | 新增get_cargo_od_stats、get_cargo_channel_stats |
| `app/tasks/stat_tasks.py` | 重建 | 货源统计改为事件驱动，船舶保持定时任务 |
| `app/workflows/cargo_parse_workflow.py` | 修复 | 修正5处字段名错误 |
| `app/schemas/cargo.py` | 更新 | CargoManualInput支持城市级，新增CargoFreightResponse |
| `app/api/v1/freight/router.py` | 重建 | 新增/freight CRUD，确认后触发统计刷新 |
| `app/api/v1/analysis/router.py` | 更新 | 新增od_flow、channel_stats接口 |
| `app/consumers/tms_cargo_consumer.py` | 新增 | TMS RQ消费者，含节点匹配逻辑 |

---

## 八、部署注意事项

1. **数据库迁移**：本次变更涉及表删除和重建，需执行完整迁移：
   ```bash
   # 开发环境：删除旧SQLite后重启（自动建表）
   rm -f *.db

   # 生产环境：执行 Alembic 迁移（需先生成迁移脚本）
   alembic revision --autogenerate -m "cargo_freight_redesign"
   alembic upgrade head
   ```

2. **TMS消费者启动**：在 `main.py` lifespan 中添加或作为独立进程：
   ```python
   from app.consumers.tms_cargo_consumer import consume_tms_cargo
   asyncio.create_task(consume_tms_cargo())
   ```

3. **船舶统计定时任务**：APScheduler配置调整，原来的 `daily_stat_job` 改为 `daily_ship_stat_job`：
   ```python
   scheduler.add_job(daily_ship_stat_job, "cron", hour=2, minute=0)
   ```
