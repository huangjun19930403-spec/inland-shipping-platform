# 货源模块本地测试指南

本文档包含货源相关功能的完整测试流程、模拟数据说明和接口调用示例。

---

## 目录

1. [快速开始](#快速开始)
2. [测试数据说明](#测试数据说明)
3. [接口测试流程](#接口测试流程)
   - [Step 0 — 获取 Token](#step-0--获取-token)
   - [Step 1 — 货品管理接口](#step-1--货品管理接口)
   - [Step 2 — 手动录入货源](#step-2--手动录入货源-manual-渠道)
   - [Step 3 — AI 文本解析流程](#step-3--ai-文本解析流程-wechat_ai-渠道)
   - [Step 4 — 货源查询与筛选](#step-4--货源查询与筛选)
   - [Step 5 — 统计分析接口](#step-5--统计分析接口)
4. [完整字段参考](#完整字段参考)
5. [常见问题](#常见问题)

---

## 快速开始

### 1. 启动服务

```bash
# 项目根目录
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 2. 初始化测试数据

```bash
# 统一初始化：基础字典 + 货源测试数据 + 最近 7 天统计聚合
python -m scripts.seed_data
```

### 3. 访问文档

- Swagger UI：http://localhost:8000/docs
- ReDoc：http://localhost:8000/redoc

---

## 测试数据说明

### 可用账号

| 用户名      | 密码         | 角色          | 可调用接口            |
|------------|-------------|--------------|----------------------|
| `admin`    | `Admin@2026` | SUPER_ADMIN  | 全部（含审核、统计）   |
| `collector1`| `Test@2026` | COLLECTOR    | 货源提交、查询        |

### 港口城市（17 个，用于 origin_admin_code / dest_admin_code）

| 城市代码   | 城市名   | 经度       | 纬度      |
|-----------|---------|-----------|----------|
| `310100`  | 上海市   | 121.4737  | 31.2304  |
| `320100`  | 南京市   | 118.7969  | 32.0603  |
| `320500`  | 苏州市   | 120.5853  | 31.2990  |
| `320600`  | 南通市   | 120.8651  | 32.0160  |
| `420100`  | 武汉市   | 114.3054  | 30.5931  |
| `500100`  | 重庆市   | 106.5516  | 29.5630  |
| `440100`  | 广州市   | 113.2644  | 23.1291  |
| `430100`  | 长沙市   | 112.9388  | 28.2278  |
| `410100`  | 郑州市   | 113.6254  | 34.7466  |
| `330100`  | 杭州市   | 120.1551  | 30.2741  |
| `360100`  | 南昌市   | 115.8581  | 28.6820  |
| `120100`  | 天津市   | 117.1901  | 39.1256  |
| `230100`  | 哈尔滨市  | 126.5350  | 45.8038  |
| `350200`  | 厦门市   | 118.1000  | 24.4797  |
| `370200`  | 青岛市   | 120.3826  | 36.0671  |
| `510100`  | 成都市   | 104.0657  | 30.6595  |
| `320700`  | 连云港市  | 119.1725  | 34.5997  |

### 货品体系（4 大类 → 9 类型 → 19 标准货品）

| 标准货品 ID | 货品代码          | 货品名称  | 所属大类  | 类型       |
|-----------|-----------------|---------|---------|-----------|
| 自动分配   | `IRON_ORE`      | 铁矿石   | 散货     | 矿石类     |
| 自动分配   | `COPPER_ORE`    | 铜矿石   | 散货     | 矿石类     |
| 自动分配   | `MANGAN_ORE`    | 锰矿石   | 散货     | 矿石类     |
| 自动分配   | `STEAM_COAL`    | 动力煤   | 散货     | 煤炭类     |
| 自动分配   | `COKING_COAL`   | 焦煤    | 散货     | 煤炭类     |
| 自动分配   | `SOYBEAN`       | 大豆    | 散货     | 粮食类     |
| 自动分配   | `CORN`          | 玉米    | 散货     | 粮食类     |
| 自动分配   | `WHEAT`         | 小麦    | 散货     | 粮食类     |
| 自动分配   | `GASOLINE`      | 汽油    | 液货     | 石油制品   |
| 自动分配   | `DIESEL`        | 柴油    | 液货     | 石油制品   |
| 自动分配   | `FUEL_OIL`      | 燃料油  | 液货     | 石油制品   |
| 自动分配   | `METHANOL`      | 甲醇    | 液货     | 化工液体   |
| 自动分配   | `CAUSTIC_SODA`  | 液碱    | 液货     | 化工液体   |
| 自动分配   | `HOME_APPLIANCE`| 家电    | 集装箱货  | 日用品    |
| 自动分配   | `CLOTHING`      | 服装    | 集装箱货  | 日用品    |
| 自动分配   | `FURNITURE`     | 家具    | 集装箱货  | 日用品    |
| 自动分配   | `STEEL`         | 钢材    | 件杂货   | 建材类    |
| 自动分配   | `CEMENT`        | 水泥    | 件杂货   | 建材类    |
| 自动分配   | `SAND_GRAVEL`   | 砂石    | 件杂货   | 建材类    |

> 货品 ID 通过 `GET /api/v1/cargo/commodity/standards/all` 查询获取。

### 预置货源记录（30 条）

数据跨越最近 7 天，覆盖以下路线：

| 主要路线              | 货品      | 吨位       | 计价方式  |
|--------------------|---------|----------|---------|
| 武汉 → 上海          | 铁矿石   | 5000 吨   | 按吨     |
| 重庆 → 武汉          | 动力煤   | 8000 吨   | 按吨     |
| 南京 → 上海          | 大豆    | 2000 吨   | 按吨     |
| 广州 → 武汉          | 汽油    | 4000 吨   | 按吨     |
| 上海 → 哈尔滨        | 服装    | 1200 吨   | 按吨     |
| 天津 → 上海          | 柴油    | 6000 吨   | 按吨     |
| 上海 → 广州          | 家具    | 600 吨    | 包干     |
| ... 共 30 条         | ...     | ...      | ...     |

---

## 接口测试流程

所有请求的 Base URL：`http://localhost:8000/api/v1`

---

### Step 0 — 获取 Token

**接口：** `POST /auth/login`

```bash
# 使用管理员账号登录（表单格式）
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=Admin%402026"
```

**响应示例：**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user_id": 1,
  "username": "admin",
  "real_name": "系统管理员",
  "roles": ["SUPER_ADMIN"]
}
```

> 后续所有请求均需在 Header 中携带：`Authorization: Bearer <access_token>`

```bash
# 设置环境变量方便使用
TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

---

### Step 1 — 货品管理接口

#### 1.1 查询货品大类列表

```bash
curl http://localhost:8000/api/v1/cargo/commodity-category \
  -H "Authorization: Bearer $TOKEN"
```

#### 1.2 查询货品类型（按大类）

```bash
# 将 {category_id} 替换为实际 ID（如 1）
curl "http://localhost:8000/api/v1/cargo/commodity-category/1/types" \
  -H "Authorization: Bearer $TOKEN"
```

#### 1.3 查询所有标准货品（不分页，用于下拉选择）

```bash
curl http://localhost:8000/api/v1/cargo/commodity/standards/all \
  -H "Authorization: Bearer $TOKEN"

# 按类型过滤
curl "http://localhost:8000/api/v1/cargo/commodity/standards/all?type_id=1" \
  -H "Authorization: Bearer $TOKEN"
```

#### 1.4 标准货品分页查询

```bash
curl "http://localhost:8000/api/v1/cargo/commodity/standards?page=1&page_size=10&keyword=铁" \
  -H "Authorization: Bearer $TOKEN"
```

#### 1.5 创建货品大类（需要 ADMIN/OPERATOR 角色）

```bash
curl -X POST http://localhost:8000/api/v1/cargo/commodity-category \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "特种货",
    "code": "SPECIAL",
    "description": "需要特殊运输条件的货物"
  }'
```

#### 1.6 创建标准货品

```bash
# 先查到 type_id，再创建标准货品
curl -X POST http://localhost:8000/api/v1/cargo/commodity-type/1/standards \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "钴矿石",
    "code": "COBALT_ORE",
    "commodity_class": "散货",
    "density": "2.30",
    "loading_method": "抓斗"
  }'
```

#### 1.7 创建货品别名

```bash
# standard_id 为标准货品 ID
curl -X POST http://localhost:8000/api/v1/cargo/commodity/standard/1/aliases \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "alias_name": "铁矿",
    "alias_type": "ABBR",
    "priority": 10
  }'
```

---

### Step 2 — 手动录入货源（MANUAL 渠道）

**接口：** `POST /freight/freight`

#### 2.1 城市级录入（最常见方式）

```bash
curl -X POST http://localhost:8000/api/v1/freight/freight \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "origin_admin_code": "420100",
    "origin_admin_name": "武汉市",
    "origin_raw_text": "武汉港阳逻港区",
    "dest_admin_code": "310100",
    "dest_admin_name": "上海市",
    "dest_raw_text": "上海港外高桥码头",
    "commodity_text": "铁矿石",
    "tonnage": 3500,
    "loading_date": "2026-03-20",
    "freight_price": 42.0,
    "price_type": 1,
    "price_unit": "元/吨",
    "contact_person": "张三",
    "contact_phone": "13812345678",
    "remark": "可接散装，需提前预约泊位"
  }'
```

#### 2.2 节点级录入（精确到具体港口）

```bash
# transport_node ID 可从 GET /address/node 查询
curl -X POST http://localhost:8000/api/v1/freight/freight \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "origin_node_id": 3,
    "dest_node_id": 5,
    "commodity_id": 1,
    "tonnage": 5000,
    "loading_date": "2026-03-22",
    "freight_price": 38.5,
    "price_type": 1,
    "contact_person": "李四",
    "contact_phone": "13987654321"
  }'
```

#### 2.3 包干计价录入

```bash
curl -X POST http://localhost:8000/api/v1/freight/freight \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "origin_admin_code": "310100",
    "origin_admin_name": "上海市",
    "dest_admin_code": "440100",
    "dest_admin_name": "广州市",
    "commodity_text": "家用电器",
    "tonnage": 800,
    "loading_date": "2026-03-25",
    "freight_price": 180000,
    "price_type": 3,
    "price_unit": "元/单",
    "contact_person": "王五",
    "contact_phone": "13611111111"
  }'
```

**响应示例：**
```json
{
  "code": 200,
  "data": {
    "id": 31,
    "freight_no": "CS-20260318-A1B2C3D4",
    "source_type": "MANUAL",
    "status": "CONFIRMED",
    "origin_admin_code": "420100",
    "origin_admin_name": "武汉市",
    "origin_precision": "CITY",
    "dest_admin_code": "310100",
    "dest_admin_name": "上海市",
    "dest_precision": "CITY",
    "tonnage": "3500.00",
    "freight_price": "42.00",
    "audit_status": 0,
    ...
  }
}
```

---

### Step 3 — AI 文本解析流程（WECHAT_AI 渠道）

该流程模拟从微信群收到货运文本、提交 AI 解析、人工确认三个步骤。

#### 3.1 提交原始货运文本

```bash
curl -X POST http://localhost:8000/api/v1/freight/text \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "raw_text": "武汉到上海，铁矿石5000吨，3月20日装，运价38元/吨，联系张三13812345678",
    "source_type": "WECHAT_GROUP",
    "group_name": "长江散货群",
    "sender_name": "张三"
  }'
```

**响应：**
```json
{
  "code": 200,
  "data": {
    "id": 1,
    "status": "PENDING",
    "message": "解析任务已提交"
  }
}
```

> AI 解析为后台异步任务，提交后稍等几秒再查询结果。

#### 3.2 查询原始消息详情

```bash
curl http://localhost:8000/api/v1/freight/text/1 \
  -H "Authorization: Bearer $TOKEN"
```

#### 3.3 查询 AI 解析结果

```bash
# msg_id 为原始消息 ID
curl http://localhost:8000/api/v1/freight/parse-result/1 \
  -H "Authorization: Bearer $TOKEN"
```

**响应示例（解析完成后）：**
```json
{
  "code": 200,
  "data": {
    "id": 1,
    "raw_message_id": 1,
    "origin_text": "武汉",
    "dest_text": "上海",
    "origin_admin_code": "420100",
    "origin_admin_name": "武汉市",
    "dest_admin_code": "310100",
    "dest_admin_name": "上海市",
    "commodity_text": "铁矿石",
    "tonnage": "5000.00",
    "loading_date": "2026-03-20",
    "freight_price": "38.00",
    "price_type": 1,
    "contact_person": "张三",
    "contact_phone": "13812345678",
    "overall_confidence": 92,
    "parse_status": "PENDING_CONFIRM"
  }
}
```

#### 3.4 人工确认解析结果（写入 cargo_freight）

```bash
# result_id 为解析结果 ID
curl -X POST http://localhost:8000/api/v1/freight/parse-result/1/confirm \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

也可以在确认时修正 AI 解析值：

```bash
curl -X POST http://localhost:8000/api/v1/freight/parse-result/1/confirm \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "origin_admin_code": "420100",
    "dest_admin_code": "310100",
    "tonnage": 5200,
    "freight_price": 39.0,
    "remark": "AI识别准确，运价略微调整"
  }'
```

#### 3.5 查询原始消息列表

```bash
# 查询所有待解析文本
curl "http://localhost:8000/api/v1/freight/text?status=PENDING&page=1&page_size=20" \
  -H "Authorization: Bearer $TOKEN"

# 查询已解析的文本
curl "http://localhost:8000/api/v1/freight/text?status=PARSED" \
  -H "Authorization: Bearer $TOKEN"
```

---

### Step 4 — 货源查询与筛选

#### 4.1 查询货源列表（全量）

```bash
curl "http://localhost:8000/api/v1/freight/freight?page=1&page_size=20" \
  -H "Authorization: Bearer $TOKEN"
```

#### 4.2 按状态筛选

```bash
# status: PENDING / CONFIRMED / CANCELLED / EXPIRED
curl "http://localhost:8000/api/v1/freight/freight?status=CONFIRMED" \
  -H "Authorization: Bearer $TOKEN"
```

#### 4.3 按来源渠道筛选

```bash
# source_type: TMS / WECHAT_AI / MANUAL
curl "http://localhost:8000/api/v1/freight/freight?source_type=MANUAL" \
  -H "Authorization: Bearer $TOKEN"
```

#### 4.4 按起点城市筛选

```bash
# origin_admin_code: 城市行政区划代码
curl "http://localhost:8000/api/v1/freight/freight?origin_admin_code=420100" \
  -H "Authorization: Bearer $TOKEN"
```

#### 4.5 按起终点城市组合筛选

```bash
curl "http://localhost:8000/api/v1/freight/freight?origin_admin_code=420100&dest_admin_code=310100" \
  -H "Authorization: Bearer $TOKEN"
```

#### 4.6 按日期筛选

```bash
curl "http://localhost:8000/api/v1/freight/freight?stat_date=2026-03-18" \
  -H "Authorization: Bearer $TOKEN"
```

#### 4.7 按货品筛选

```bash
# 先从 commodity/standards/all 查到 commodity_id
curl "http://localhost:8000/api/v1/freight/freight?commodity_id=1" \
  -H "Authorization: Bearer $TOKEN"
```

#### 4.8 获取货源详情

```bash
curl http://localhost:8000/api/v1/freight/freight/1 \
  -H "Authorization: Bearer $TOKEN"
```

---

### Step 5 — 统计分析接口

> 所有分析接口依赖统计表中的数据。运行 `seed_data.py` 后已触发 7 天统计，可直接查询。
> 如需重新聚合，调用 `POST /analysis/run-stats`。

#### 5.1 仪表盘数据（综合指标）

```bash
curl http://localhost:8000/api/v1/analysis/dashboard \
  -H "Authorization: Bearer $TOKEN"
```

**响应包含：**
- 今日/本周货源总量与总吨位
- 最新每日统计
- 最新统计日期

#### 5.2 货源城市热力图

```bash
# 装货城市热力（默认今天）
curl "http://localhost:8000/api/v1/analysis/cargo/heatmap?stat_type=ORIGIN" \
  -H "Authorization: Bearer $TOKEN"

# 卸货城市热力
curl "http://localhost:8000/api/v1/analysis/cargo/heatmap?stat_type=DEST&stat_date=2026-03-17" \
  -H "Authorization: Bearer $TOKEN"
```

**响应示例：**
```json
{
  "code": 200,
  "data": {
    "stat_date": "2026-03-18",
    "items": [
      {
        "city_code": "420100",
        "city_name": "武汉市",
        "city_longitude": "114.30540000",
        "city_latitude": "30.59310000",
        "stat_type": "ORIGIN",
        "cargo_count": 5,
        "total_tonnage": "28000.00"
      },
      ...
    ]
  }
}
```

> `city_longitude` / `city_latitude` 可直接用于前端热力地图渲染。

#### 5.3 货源趋势图

```bash
# 最近 7 天趋势
curl "http://localhost:8000/api/v1/analysis/cargo/trend?days=7" \
  -H "Authorization: Bearer $TOKEN"

# 指定日期范围
curl "http://localhost:8000/api/v1/analysis/cargo/trend?start_date=2026-03-12&end_date=2026-03-18" \
  -H "Authorization: Bearer $TOKEN"
```

**响应示例：**
```json
{
  "code": 200,
  "data": {
    "days": [
      {
        "stat_date": "2026-03-18",
        "total_count": 5,
        "confirmed_count": 5,
        "pending_count": 0,
        "total_tonnage": "28000.00",
        "avg_tonnage": "5600.00"
      },
      ...
    ]
  }
}
```

#### 5.4 货品分类排名

```bash
curl "http://localhost:8000/api/v1/analysis/cargo/commodity_rank?stat_date=2026-03-18" \
  -H "Authorization: Bearer $TOKEN"
```

#### 5.5 OD 流量矩阵（桑基图数据）

```bash
# 最近 7 天 Top 20 路线
curl "http://localhost:8000/api/v1/analysis/cargo/od_flow?days=7&top_n=20" \
  -H "Authorization: Bearer $TOKEN"

# 指定单日
curl "http://localhost:8000/api/v1/analysis/cargo/od_flow?stat_date=2026-03-18&top_n=10" \
  -H "Authorization: Bearer $TOKEN"
```

**响应示例：**
```json
{
  "code": 200,
  "data": {
    "routes": [
      {
        "origin_city_code": "420100",
        "origin_city_name": "武汉市",
        "dest_city_code": "310100",
        "dest_city_name": "上海市",
        "cargo_count": 3,
        "total_tonnage": "15000.00"
      },
      ...
    ]
  }
}
```

#### 5.6 渠道质量统计

```bash
# 今日各渠道数据
curl "http://localhost:8000/api/v1/analysis/cargo/channel_stats?stat_date=2026-03-18" \
  -H "Authorization: Bearer $TOKEN"

# 最近 30 天渠道趋势
curl "http://localhost:8000/api/v1/analysis/cargo/channel_stats?days=30" \
  -H "Authorization: Bearer $TOKEN"
```

#### 5.7 手动触发统计聚合（仅 ADMIN/SUPER_ADMIN）

```bash
# 重新聚合今天的统计
curl -X POST "http://localhost:8000/api/v1/analysis/run-stats" \
  -H "Authorization: Bearer $TOKEN"

# 聚合指定日期
curl -X POST "http://localhost:8000/api/v1/analysis/run-stats?target_date=2026-03-17" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 完整字段参考

### CargoManualInput（手动录入货源请求体）

| 字段                | 类型       | 必填 | 说明                                      |
|--------------------|-----------|------|------------------------------------------|
| `origin_node_id`   | integer   | 否   | 装货节点 ID（与 admin_code 二选一）         |
| `origin_admin_code`| string    | 否   | 装货城市行政区划代码（如 `420100`）          |
| `origin_admin_name`| string    | 否   | 装货城市名称（冗余，可不传）                 |
| `origin_raw_text`  | string    | 否   | 装货地原始描述（如"武汉港阳逻港区"）          |
| `dest_node_id`     | integer   | 否   | 卸货节点 ID（与 admin_code 二选一）         |
| `dest_admin_code`  | string    | 否   | 卸货城市行政区划代码                        |
| `dest_admin_name`  | string    | 否   | 卸货城市名称                               |
| `dest_raw_text`    | string    | 否   | 卸货地原始描述                             |
| `commodity_id`     | integer   | 否   | 标准货品 ID（与 commodity_text 二选一）     |
| `commodity_text`   | string    | 否   | 货品自由文本描述                           |
| `tonnage`          | decimal   | 否   | 货物吨位（吨）                             |
| `loading_date`     | date      | 否   | 装货日期，格式 `YYYY-MM-DD`                |
| `expire_date`      | date      | 否   | 货源有效截止日                             |
| `freight_price`    | decimal   | 否   | 运价                                      |
| `price_type`       | integer   | 否   | 1=按吨 / 2=按方 / 3=包干 / 4=按箱 / 5=面议 |
| `price_unit`       | string    | 否   | 计价单位（如"元/吨"）                      |
| `contact_person`   | string    | 否   | 联系人姓名                                |
| `contact_phone`    | string    | 否   | 联系人电话                                |
| `source_type`      | string    | 否   | 默认 `MANUAL`，也可传 `TMS`               |
| `remark`           | string    | 否   | 备注                                      |

### origin_precision / dest_precision 枚举值

| 值           | 说明                      |
|-------------|--------------------------|
| `NODE`      | 已关联到 transport_node   |
| `CITY`      | 已关联到 admin_region 城市 |
| `COORDINATE`| 仅有坐标，未匹配到节点/城市 |
| `UNKNOWN`   | 无法识别                  |

### price_type 枚举值

| 值 | 说明   |
|----|-------|
| 1  | 按吨  |
| 2  | 按方  |
| 3  | 包干  |
| 4  | 按箱  |
| 5  | 面议  |

---

## 常见问题

### Q: 统计接口返回空数组？

运行种子脚本后统计数据应已就绪。如仍为空，手动触发聚合：

```bash
curl -X POST "http://localhost:8000/api/v1/analysis/run-stats" \
  -H "Authorization: Bearer $TOKEN"
```

### Q: 手动录入后统计未更新？

手动录入会在后台异步触发 `refresh_cargo_stats`。如想立即看到数据，调用 `POST /analysis/run-stats`。

### Q: 创建货源时提示 404 TransportNode？

`origin_node_id` / `dest_node_id` 必须是 `transport_node` 表中已存在的节点 ID。
可通过 `GET /address/node` 查询可用节点，或改用城市级字段 `origin_admin_code`。

### Q: 如何重置测试数据？

```bash
# 删除所有货源相关测试数据后重新初始化
sqlite3 inland_shipping.db "DELETE FROM cargo_freight WHERE freight_no LIKE 'CS-%-TEST%';"
sqlite3 inland_shipping.db "DELETE FROM cargo_city_heatmap;"
sqlite3 inland_shipping.db "DELETE FROM cargo_od_daily;"
sqlite3 inland_shipping.db "DELETE FROM cargo_channel_daily;"
sqlite3 inland_shipping.db "DELETE FROM cargo_stat_daily;"
sqlite3 inland_shipping.db "DELETE FROM cargo_commodity_stat_daily;"
python -m scripts.seed_data
```

### Q: Token 过期怎么办？

重新调用 `POST /auth/login` 获取新 Token，默认有效期在 `app/core/config.py` 的 `ACCESS_TOKEN_EXPIRE_MINUTES` 配置。

### Q: 如何用 Swagger UI 测试？

1. 打开 http://localhost:8000/docs
2. 点击右上角 **Authorize** 按钮
3. 先调用 `/auth/login` 获取 Token（在 Swagger 中点 Try it out）
4. 将 Token 填入 Authorize 弹窗（格式：Bearer `<token>`）
5. 之后所有接口均会自动携带认证头
