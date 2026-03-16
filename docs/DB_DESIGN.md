# 内河航运平台 · 数据库设计文档

> **数据库引擎**: MySQL 8.0 / SQLite 3（本地开发）
> **字符集**: utf8mb4 / utf8mb4_unicode_ci
> **ORM**: SQLAlchemy 2.x (async)
> **迁移工具**: Alembic
> **总表数**: 26 张
> **最后更新**: 2026-03-16

---

## 目录

1. [数据库总览](#1-数据库总览)
2. [模块一：系统基础（3 张）](#2-模块一系统基础)
3. [模块二：审核记录（1 张）](#3-模块二审核记录)
4. [模块三：地址体系（7 张）](#4-模块三地址体系)
5. [模块四：货品体系（4 张）](#5-模块四货品体系)
6. [模块五：货源体系（3 张）](#6-模块五货源体系)
7. [模块六：船舶体系（5 张）](#7-模块六船舶体系)
8. [模块七：航线体系（2 张）](#8-模块七航线体系)
9. [模块八：统计分析（1 张）](#9-模块八统计分析)
10. [表间关系 ER 概览](#10-表间关系-er-概览)
11. [接口与表映射](#11-接口与表映射)
12. [SQLite 切换到 MySQL 完整指南](#12-sqlite-切换到-mysql-完整指南)

---

## 1. 数据库总览

| 序号 | 表名 | 中文名 | 所属模块 | 模型文件 |
|------|------|--------|---------|---------|
| 1 | `sys_role` | 系统角色 | 系统基础 | `app/models/system.py` |
| 2 | `sys_user` | 系统用户 | 系统基础 | `app/models/system.py` |
| 3 | `sys_user_role` | 用户角色关联 | 系统基础 | `app/models/system.py` |
| 4 | `audit_record` | 审核记录 | 审核 | `app/models/audit.py` |
| 5 | `waterway` | 水系 | 地址体系 | `app/models/address.py` |
| 6 | `admin_region` | 行政区划 | 地址体系 | `app/models/address.py` |
| 7 | `node_type` | 节点类型 | 地址体系 | `app/models/address.py` |
| 8 | `region` | 商业区域 | 地址体系 | `app/models/address.py` |
| 9 | `transport_node` | 运输节点 | 地址体系 | `app/models/address.py` |
| 10 | `node_alias` | 节点别名 | 地址体系 | `app/models/address.py` |
| 11 | `region_address_relation` | 节点区域关系 | 地址体系 | `app/models/address.py` |
| 12 | `commodity_category` | 货品大类 | 货品体系 | `app/models/cargo.py` |
| 13 | `commodity_type` | 货品类型 | 货品体系 | `app/models/cargo.py` |
| 14 | `commodity_standard` | 标准货品 | 货品体系 | `app/models/cargo.py` |
| 15 | `commodity_alias` | 货品别名 | 货品体系 | `app/models/cargo.py` |
| 16 | `cargo_raw_message` | 原始货源文本 | 货源体系 | `app/models/cargo.py` |
| 17 | `cargo_ai_parse_result` | AI解析结果 | 货源体系 | `app/models/cargo.py` |
| 18 | `cargo_opportunity` | 货源信息 | 货源体系 | `app/models/cargo.py` |
| 19 | `vessel_type_dict` | 船舶类型字典 | 船舶体系 | `app/models/vessel.py` |
| 20 | `vessel` | 船舶主档案 | 船舶体系 | `app/models/vessel.py` |
| 21 | `vessel_name_history` | 船名变更历史 | 船舶体系 | `app/models/vessel.py` |
| 22 | `vessel_ais_history` | AIS/MMSI变更历史 | 船舶体系 | `app/models/vessel.py` |
| 23 | `vessel_dynamic` | 船舶动态 | 船舶体系 | `app/models/vessel.py` |
| 24 | `shipping_route` | 商业航线 | 航线体系 | `app/models/route.py` |
| 25 | `shipping_route_path` | 航线路径节点 | 航线体系 | `app/models/route.py` |
| 26 | `heatmap_stat_daily` | 热力统计日表 | 统计分析 | `app/models/analysis.py` |

---

## 2. 模块一：系统基础

### 2.1 `sys_role` — 系统角色表

**功能**: 定义平台角色，控制菜单与操作权限。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `code` | VARCHAR(32) | UNIQUE, NOT NULL | 角色编码: SUPER_ADMIN/ADMIN/OPERATOR/COLLECTOR |
| `name` | VARCHAR(64) | NOT NULL | 角色名称 |
| `description` | VARCHAR(256) | | 角色描述 |
| `status` | TINYINT | NOT NULL, DEFAULT 1 | 1=启用, 0=停用 |
| `sort_order` | TINYINT | NOT NULL, DEFAULT 0 | 排序 |
| `created_at` | DATETIME | | 创建时间 |
| `updated_at` | DATETIME | | 更新时间 |

**相关接口**: `POST /auth/roles`, `GET /auth/roles`

---

### 2.2 `sys_user` — 系统用户表

**功能**: 存储平台管理端用户，支持微信小程序 OpenID 绑定。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `username` | VARCHAR(64) | UNIQUE, NOT NULL | 登录名 |
| `real_name` | VARCHAR(64) | NOT NULL | 真实姓名 |
| `password_hash` | VARCHAR(256) | NOT NULL | Bcrypt 密码哈希 |
| `phone` | VARCHAR(32) | | 手机号 |
| `email` | VARCHAR(128) | | 邮箱 |
| `department` | VARCHAR(64) | | 部门 |
| `avatar` | VARCHAR(256) | | 头像URL |
| `wx_open_id` | VARCHAR(64) | INDEX | 微信 OpenID |
| `wx_bound` | TINYINT | DEFAULT 0 | 0=未绑定, 1=已绑定 |
| `status` | TINYINT | NOT NULL, DEFAULT 1 | 1=启用, 0=停用 |
| `last_login_at` | DATETIME | | 最后登录时间 |
| `created_by` | BIGINT | | 创建人ID |
| `created_at` | DATETIME | | 创建时间 |
| `updated_at` | DATETIME | | 更新时间 |

**相关接口**: `POST /auth/login`, `POST /auth/users`, `GET /auth/users/{id}`

---

### 2.3 `sys_user_role` — 用户角色关联表

**功能**: 多对多关联 sys_user 与 sys_role，实现 RBAC 权限控制。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `user_id` | BIGINT | FK → sys_user, UNIQUE(user_id,role_id) | 用户ID |
| `role_id` | BIGINT | FK → sys_role | 角色ID |
| `created_at` | DATETIME | | 创建时间 |

---

## 3. 模块二：审核记录

### 3.1 `audit_record` — 审核记录表

**功能**: 记录所有业务对象的审核操作历史，保障数据质量可追溯。支持的审核对象类型：`TRANSPORT_NODE` / `COMMODITY_CATEGORY` / `COMMODITY_TYPE` / `COMMODITY_STANDARD` / `VESSEL` / `WATERWAY` / `REGION` / `NODE_TYPE` / `CARGO_OPPORTUNITY`。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `target_type` | VARCHAR(64) | NOT NULL, INDEX | 审核对象类型 |
| `target_id` | BIGINT | NOT NULL, INDEX | 被审核对象ID |
| `target_name` | VARCHAR(256) | | 对象名称快照 |
| `action` | VARCHAR(32) | NOT NULL | CREATE/UPDATE/DISABLE/ENABLE/AI_CONFIRM |
| `before_data` | JSON | | 变更前数据快照 |
| `after_data` | JSON | | 变更后数据快照 |
| `audit_result` | VARCHAR(32) | NOT NULL, INDEX | PENDING/APPROVED/REJECTED |
| `audit_remark` | VARCHAR(512) | | 审核意见 |
| `submitter_id` | BIGINT | NOT NULL, INDEX | 提交人ID |
| `submitter_name` | VARCHAR(64) | | 提交人姓名快照 |
| `submitted_at` | DATETIME | INDEX | 提交时间 |
| `auditor_id` | BIGINT | | 审核人ID |
| `auditor_name` | VARCHAR(64) | | 审核人姓名快照 |
| `audited_at` | DATETIME | | 审核时间 |
| `created_at` | DATETIME | | 创建时间 |
| `updated_at` | DATETIME | | 更新时间 |

**相关接口**: `POST /address/node/{id}/approve`, `POST /region/{id}/approve`, `POST /region/{id}/reject` 等所有审核动作

---

## 4. 模块三：地址体系

### 4.1 `waterway` — 水系表

**功能**: 维护内河水系（干流/支流/运河）的层级结构，是运输节点和航线的地理基础。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `code` | VARCHAR(32) | UNIQUE, NOT NULL | 水系编码（格式：WW-LL-NNN） |
| `name` | VARCHAR(64) | NOT NULL | 水系名称 |
| `name_en` | VARCHAR(128) | | 英文名称 |
| `level` | TINYINT | NOT NULL, DEFAULT 1 | 1=主干水系, 2=支流, 3=运河 |
| `parent_id` | BIGINT | FK → waterway(self) | 上级水系ID（自关联） |
| `provinces` | VARCHAR(256) | | 流经省份 |
| `total_length_km` | DECIMAL(10,2) | | 总长度(km) |
| `navigable_length_km` | DECIMAL(10,2) | | 通航里程(km) |
| `description` | VARCHAR(512) | | 描述 |
| `sort_order` | INT | NOT NULL, DEFAULT 0 | 排序 |
| `status` | TINYINT | NOT NULL, DEFAULT 1 | 1=启用, 0=停用 |
| `created_at` | DATETIME | | 创建时间 |
| `updated_at` | DATETIME | | 更新时间 |

**相关接口**:
- `POST /address/waterway` — 新增水系（编码自动生成）
- `GET /address/waterway/list` — 分页查询
- `PUT /address/waterway/{id}` — 修改
- `DELETE /address/waterway/{id}` — 删除
- `POST /address/waterway/{id}/toggle-status` — 启用/停用

---

### 4.2 `admin_region` — 行政区划表

**功能**: 存储省/市/区县三级行政区划数据（含坐标），用于区域自动圈城市。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `code` | VARCHAR(12) | UNIQUE, NOT NULL | 行政区划代码（国标GB/T 2260） |
| `name` | VARCHAR(64) | NOT NULL | 名称 |
| `short_name` | VARCHAR(32) | | 简称 |
| `pinyin` | VARCHAR(128) | | 拼音 |
| `level` | TINYINT | NOT NULL | 1=省, 2=市, 3=区县 |
| `parent_code` | VARCHAR(12) | FK → admin_region(code) | 上级代码（自关联） |
| `full_path` | VARCHAR(256) | | 完整路径（如：湖北省/武汉市） |
| `longitude` | DECIMAL(11,8) | | 行政中心经度 |
| `latitude` | DECIMAL(10,8) | | 行政中心纬度 |
| `sort_order` | INT | DEFAULT 0 | 排序 |
| `status` | TINYINT | NOT NULL, DEFAULT 1 | 1=启用, 0=停用 |
| `created_at` | DATETIME | | 创建时间 |
| `updated_at` | DATETIME | | 更新时间 |

**业务说明**: `level=2`（市级）记录的经纬度被 `region` 新增/修改时用于**射线法**自动判断哪些城市在区域边界内，结果写入 `region.main_cities`。

**相关接口**: `GET /address/admin-region/list`, `POST /address/admin-region`

---

### 4.3 `node_type` — 节点类型字典表

**功能**: 定义运输节点的种类（港口/码头/锚地等），节点创建时必须指定此类型。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `code` | VARCHAR(32) | UNIQUE, NOT NULL | 类型编码 |
| `name` | VARCHAR(64) | NOT NULL | 类型名称 |
| `name_en` | VARCHAR(128) | | 英文名称 |
| `transport_mode` | VARCHAR(32) | NOT NULL, DEFAULT 'WATERWAY' | WATERWAY/RAILWAY/HIGHWAY/MULTIMODAL |
| `icon` | VARCHAR(256) | | 图标URL |
| `description` | VARCHAR(512) | | 描述 |
| `sort_order` | INT | NOT NULL, DEFAULT 0 | 排序 |
| `status` | TINYINT | NOT NULL, DEFAULT 1 | 1=启用, 0=停用 |
| `created_at` | DATETIME | | 创建时间 |
| `updated_at` | DATETIME | | 更新时间 |

**相关接口**: `GET /address/node-type/list`, `POST /address/node-type`, `DELETE /address/node-type/{id}`

---

### 4.4 `region` — 商业区域表

**功能**: 定义航运业务区域（如"长三角地区"），包含地理边界多边形，支持审核流程。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `code` | VARCHAR(50) | UNIQUE, NOT NULL | 区域编码（系统自动生成，格式 RG-NNN） |
| `name` | VARCHAR(64) | NOT NULL | 区域名称 |
| `name_en` | VARCHAR(128) | | 英文名称 |
| `center_longitude` | DECIMAL(11,8) | | 中心经度（由边界坐标算术均值自动计算） |
| `center_latitude` | DECIMAL(10,8) | | 中心纬度（由边界坐标算术均值自动计算） |
| `main_rivers` | JSON | | 主要水系 ID 数组，用户手动指定 |
| `main_cities` | JSON | | 主要城市 ID 数组，由边界+射线法自动计算 |
| `boundary_coordinates` | JSON | | 边界坐标序列 [[lng,lat],...] |
| `boundary_color` | VARCHAR(20) | DEFAULT '#3388ff' | 边界颜色 |
| `area_color` | VARCHAR(20) | DEFAULT '#3388ff' | 填充颜色 |
| `description` | VARCHAR(512) | | 描述 |
| `sort_order` | INT | NOT NULL, DEFAULT 0 | 排序 |
| `status` | TINYINT | NOT NULL, DEFAULT 0 | 1=启用, 0=停用（审批通过后自动启用） |
| `audit_status` | TINYINT | NOT NULL, DEFAULT 0 | 0=待审核, 1=已通过, 2=已驳回 |
| `audit_remark` | VARCHAR(512) | | 审核意见 |
| `submitter_id` | BIGINT | | 提交人ID |
| `auditor_id` | BIGINT | | 审核人ID |
| `created_at` | DATETIME | | 创建时间 |
| `updated_at` | DATETIME | | 更新时间 |

**业务说明**:
- 新建/修改时后端自动计算 `center_longitude/center_latitude`（边界顶点均值）和 `main_cities`（射线法匹配 level=2 城市）
- **修改前置条件**: status=0（停用）；修改后 audit_status 重置为 0（待审核）
- **审批通过**: audit_status=1, status 自动置为 1（启用）
- **驳回**: audit_status=2, status 保持 0

**相关接口**:
- `POST /address/region` — 新增（编码自动生成）
- `GET /address/region/list` — 分页查询（返回 RegionDetailResponse，展开水系和城市详情）
- `PUT /address/region/{id}` — 修改（仅 status=0 时可改）
- `POST /address/region/{id}/toggle-status` — 启用/停用（无需审批）
- `POST /address/region/{id}/approve` — 审批通过
- `POST /address/region/{id}/reject` — 驳回

---

### 4.5 `transport_node` — 运输节点表

**功能**: 记录港口、码头等实际物理节点，是货源起终点、航线节点、船舶动态的核心引用对象。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `code` | VARCHAR(32) | UNIQUE, NOT NULL | 节点编码 |
| `name` | VARCHAR(128) | NOT NULL | 节点标准名称 |
| `name_en` | VARCHAR(256) | | 英文名称 |
| `node_type_id` | BIGINT | FK → node_type, NOT NULL | 节点类型ID |
| `node_category` | TINYINT | NOT NULL, DEFAULT 4 | 1=装货, 2=卸货, 3=中转, 4=综合, 5=航道 |
| `waterway_id` | BIGINT | FK → waterway | 所属水系ID |
| `region_id` | BIGINT | FK → region | 所属商业区域ID |
| `province` | VARCHAR(32) | | 所属省份 |
| `city` | VARCHAR(32) | | 所属城市 |
| `district` | VARCHAR(32) | | 所属区县 |
| `address` | VARCHAR(256) | | 详细地址 |
| `longitude` | DECIMAL(11,8) | | 经度(WGS84) |
| `latitude` | DECIMAL(10,8) | | 纬度(WGS84) |
| `node_level` | TINYINT | DEFAULT 3 | 1=一级, 2=二级, 3=三级 |
| `is_hot_node` | TINYINT | NOT NULL, DEFAULT 0 | 0=否, 1=是 |
| `river_km` | DECIMAL(10,2) | | 航道里程标(km) |
| `max_tonnage` | INT | | 最大靠泊吨位(吨) |
| `berth_count` | INT | | 泊位数量 |
| `annual_throughput` | VARCHAR(64) | | 年吞吐量 |
| `description` | VARCHAR(512) | | 描述 |
| `sort_order` | INT | NOT NULL, DEFAULT 0 | 排序 |
| `status` | TINYINT | NOT NULL, DEFAULT 1 | 1=运营中, 0=停用, 2=建设中 |
| `audit_status` | TINYINT | DEFAULT 1 | 0=待审核, 1=已通过, 2=已驳回 |
| `audit_remark` | VARCHAR(512) | | 审核意见 |
| `submitter_id` | BIGINT | | 提交人ID |
| `auditor_id` | BIGINT | | 审核人ID |
| `created_at` | DATETIME | | 创建时间 |
| `updated_at` | DATETIME | | 更新时间 |

**相关接口**: `POST /address/node`, `GET /address/node/list`, `PUT /address/node/{id}`, `POST /address/node/{id}/approve`, `GET /address/node/search`

---

### 4.6 `node_alias` — 节点别名表

**功能**: 为运输节点维护多个别名（简称/历史名/行业俗称），用于 AI 货源解析时的文本匹配。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `node_id` | BIGINT | FK → transport_node, NOT NULL | 所属节点ID |
| `alias_name` | VARCHAR(128) | UNIQUE, NOT NULL | 别名 |
| `alias_type` | VARCHAR(32) | NOT NULL, DEFAULT 'COMMON' | COMMON/ABBR/HISTORICAL/SYSTEM |
| `source` | VARCHAR(64) | | 别名来源 |
| `priority` | INT | NOT NULL, DEFAULT 0 | 匹配优先级（越大越优先） |
| `status` | TINYINT | NOT NULL, DEFAULT 1 | 1=启用, 0=停用 |
| `created_at` | DATETIME | | 创建时间 |
| `updated_at` | DATETIME | | 更新时间 |

**相关接口**: `POST /address/node/alias`, `DELETE /address/node/alias/{id}`, `GET /address/node/{id}/aliases`

---

### 4.7 `region_address_relation` — 节点与区域关系表

**功能**: 记录运输节点归属哪个商业区域，支持一对多（一个节点可归属多个区域）。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `region_id` | BIGINT | FK → region, NOT NULL | 区域ID |
| `transport_node_id` | BIGINT | FK → transport_node, NOT NULL | 节点ID |
| `is_primary` | TINYINT | NOT NULL, DEFAULT 1 | 1=主归属 |
| `created_at` | DATETIME | | 创建时间 |
| `updated_at` | DATETIME | | 更新时间 |

---

## 5. 模块四：货品体系

### 5.1 `commodity_category` — 货品大类表

**功能**: 货品分类的第一层（如"矿石类"、"建材类"），支持审核。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `code` | VARCHAR(32) | | 分类编码 |
| `name` | VARCHAR(64) | NOT NULL | 大类名称 |
| `name_en` | VARCHAR(128) | | 英文名称 |
| `description` | VARCHAR(512) | | 描述 |
| `sort_order` | INT | NOT NULL, DEFAULT 0 | 排序 |
| `status` | TINYINT | NOT NULL, DEFAULT 1 | 1=启用, 0=停用 |
| `audit_status` | TINYINT | DEFAULT 1 | 0=待审核, 1=已通过, 2=已驳回 |
| `submitter_id` | BIGINT | | 提交人ID |
| `auditor_id` | BIGINT | | 审核人ID |
| `created_at` | DATETIME | | 创建时间 |
| `updated_at` | DATETIME | | 更新时间 |

**相关接口**: `GET /cargo/category/list`, `POST /cargo/category`, `PUT /cargo/category/{id}`

---

### 5.2 `commodity_type` — 货品类型表

**功能**: 货品分类第二层（如"铁矿石"、"煤炭"），归属于某个大类。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `category_id` | BIGINT | FK → commodity_category, NOT NULL | 所属大类ID |
| `code` | VARCHAR(32) | | 类型编码 |
| `name` | VARCHAR(64) | NOT NULL | 类型名称 |
| `name_en` | VARCHAR(128) | | 英文名称 |
| `description` | VARCHAR(512) | | 描述 |
| `sort_order` | INT | NOT NULL, DEFAULT 0 | 排序 |
| `status` | TINYINT | NOT NULL, DEFAULT 1 | 1=启用, 0=停用 |
| `audit_status` | TINYINT | DEFAULT 1 | 0=待审核, 1=已通过, 2=已驳回 |
| `submitter_id` | BIGINT | | 提交人ID |
| `auditor_id` | BIGINT | | 审核人ID |
| `created_at` | DATETIME | | 创建时间 |
| `updated_at` | DATETIME | | 更新时间 |

---

### 5.3 `commodity_standard` — 标准货品表

**功能**: 货品的最细粒度（如"5500大卡动力煤"），是货源和 AI 解析的核心匹配目标。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `type_id` | BIGINT | FK → commodity_type, NOT NULL | 所属类型ID |
| `code` | VARCHAR(32) | | 货品编码 |
| `name` | VARCHAR(128) | NOT NULL | 货品标准名称 |
| `name_en` | VARCHAR(256) | | 英文名称 |
| `commodity_class` | VARCHAR(32) | | 散货/件杂/液体/集装箱/特种 |
| `industry` | VARCHAR(64) | | 行业分类 |
| `density` | DECIMAL(8,4) | | 密度(t/m³) |
| `is_dangerous` | TINYINT | DEFAULT 0 | 0=否, 1=是 |
| `loading_method` | VARCHAR(64) | | 装货方式 |
| `recommended_ship_type` | VARCHAR(128) | | 推荐船型 |
| `description` | VARCHAR(512) | | 描述 |
| `sort_order` | INT | NOT NULL, DEFAULT 0 | 排序 |
| `status` | TINYINT | NOT NULL, DEFAULT 1 | 1=启用, 0=停用 |
| `audit_status` | TINYINT | DEFAULT 1 | 0=待审核, 1=已通过, 2=已驳回 |
| `audit_remark` | VARCHAR(512) | | 审核意见 |
| `submitter_id` | BIGINT | | 提交人ID |
| `auditor_id` | BIGINT | | 审核人ID |
| `created_at` | DATETIME | | 创建时间 |
| `updated_at` | DATETIME | | 更新时间 |

---

### 5.4 `commodity_alias` — 货品别名表

**功能**: 为标准货品维护别名（行业俗称/方言名/缩写），支持 AI 解析时的模糊匹配。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `commodity_id` | BIGINT | FK → commodity_standard, NOT NULL | 所属货品ID |
| `alias_name` | VARCHAR(128) | NOT NULL | 别名 |
| `alias_type` | VARCHAR(32) | DEFAULT 'COMMON' | COMMON/ABBR/DIALECT/INDUSTRY |
| `priority` | INT | NOT NULL, DEFAULT 0 | 匹配优先级 |
| `status` | TINYINT | NOT NULL, DEFAULT 1 | 1=启用, 0=停用 |
| `created_at` | DATETIME | | 创建时间 |
| `updated_at` | DATETIME | | 更新时间 |

---

## 6. 模块五：货源体系

### 6.1 `cargo_raw_message` — 原始货源文本表

**功能**: 存储从微信群/电话等渠道采集的原始货源消息，等待 AI 解析。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `raw_text` | TEXT | NOT NULL | 原始文本内容 |
| `source_type` | VARCHAR(32) | DEFAULT 'WECHAT_GROUP' | WECHAT_GROUP/PHONE/WEBSITE/OTHER |
| `group_name` | VARCHAR(128) | | 群名称 |
| `sender_name` | VARCHAR(64) | | 发送人 |
| `message_time` | DATETIME | INDEX | 消息时间 |
| `collector_id` | BIGINT | INDEX | 采集员ID |
| `status` | VARCHAR(32) | DEFAULT 'PENDING' | PENDING/PARSING/PARSED/INVALID |
| `created_at` | DATETIME | | 创建时间 |
| `updated_at` | DATETIME | | 更新时间 |

**相关接口**: `POST /cargo/raw-message`, `GET /cargo/raw-message/list`

---

### 6.2 `cargo_ai_parse_result` — AI 解析结果表

**功能**: 存储 AI 对原始货源文本的解析输出，包含起终点/货品/吨位/运价的匹配结果及置信度。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `raw_message_id` | BIGINT | FK → cargo_raw_message, NOT NULL | 原始文本ID |
| `origin_text` | VARCHAR(256) | | 起点原始文本 |
| `dest_text` | VARCHAR(256) | | 终点原始文本 |
| `commodity_text` | VARCHAR(256) | | 货品原始文本 |
| `tonnage_text` | VARCHAR(64) | | 吨位原始文本 |
| `loading_date_text` | VARCHAR(64) | | 时间原始文本 |
| `freight_text` | VARCHAR(128) | | 运价原始文本 |
| `contact_text` | VARCHAR(256) | | 联系方式原始文本 |
| `origin_node_id` | BIGINT | FK → transport_node | 匹配的起点节点ID |
| `dest_node_id` | BIGINT | FK → transport_node | 匹配的终点节点ID |
| `commodity_id` | BIGINT | FK → commodity_standard | 匹配的货品ID |
| `tonnage` | DECIMAL(12,2) | | 解析的吨位 |
| `loading_date` | DATE | | 解析的装货日期 |
| `freight_price` | DECIMAL(12,2) | | 解析的运价 |
| `price_type` | TINYINT | | 1=按吨,2=按方,3=包干,4=按箱,5=面议 |
| `contact_person` | VARCHAR(64) | | 联系人 |
| `contact_phone` | VARCHAR(32) | | 联系电话 |
| `origin_confidence` | INT | DEFAULT 0 | 起点置信度(0-100) |
| `dest_confidence` | INT | DEFAULT 0 | 终点置信度(0-100) |
| `commodity_confidence` | INT | DEFAULT 0 | 货品置信度(0-100) |
| `tonnage_confidence` | INT | DEFAULT 0 | 吨位置信度(0-100) |
| `overall_confidence` | INT | DEFAULT 0 | 综合置信度(0-100) |
| `origin_candidates` | JSON | | 起点候选列表 `[{id,name,score}]` |
| `dest_candidates` | JSON | | 终点候选列表 |
| `commodity_candidates` | JSON | | 货品候选列表 |
| `ai_model` | VARCHAR(64) | | 使用的AI模型 |
| `ai_prompt_tokens` | INT | | 消耗的tokens数 |
| `parse_status` | VARCHAR(32) | DEFAULT 'PENDING_CONFIRM' | PENDING_CONFIRM/CONFIRMED/DISCARDED |
| `confirmed_by` | BIGINT | | 确认人ID |
| `confirmed_at` | DATETIME | | 确认时间 |
| `discard_reason` | VARCHAR(256) | | 废弃原因 |
| `created_at` | DATETIME | | 创建时间 |
| `updated_at` | DATETIME | | 更新时间 |

---

### 6.3 `cargo_opportunity` — 货源信息表（正式数据）

**功能**: 经人工确认或直接手工录入的正式货源信息，是平台核心业务数据。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `opportunity_no` | VARCHAR(32) | UNIQUE, NOT NULL | 货源编号 |
| `origin_node_id` | BIGINT | FK → transport_node, NOT NULL | 装货节点ID |
| `dest_node_id` | BIGINT | FK → transport_node, NOT NULL | 卸货节点ID |
| `commodity_id` | BIGINT | FK → commodity_standard, NOT NULL | 货品ID |
| `tonnage` | DECIMAL(12,2) | NOT NULL | 货物吨位(吨) |
| `origin_region_id` | BIGINT | FK → region | 装货区域（系统自动匹配） |
| `dest_region_id` | BIGINT | FK → region | 卸货区域（系统自动匹配） |
| `route_id` | BIGINT | FK → shipping_route | 匹配航线（系统自动） |
| `loading_date` | DATE | INDEX | 装货日期 |
| `freight_price` | DECIMAL(12,2) | | 运价 |
| `price_type` | TINYINT | | 1=按吨,2=按方,3=包干,4=按箱,5=面议 |
| `price_unit` | VARCHAR(32) | | 计价单位 |
| `contact_person` | VARCHAR(64) | | 联系人 |
| `contact_phone` | VARCHAR(32) | | 联系电话 |
| `source_type` | VARCHAR(32) | DEFAULT 'WECHAT_GROUP' | 来源渠道 |
| `remark` | VARCHAR(512) | | 备注 |
| `raw_message_id` | BIGINT | FK → cargo_raw_message | 原始文本ID（溯源） |
| `parse_result_id` | BIGINT | FK → cargo_ai_parse_result | AI解析结果ID（溯源） |
| `status` | VARCHAR(32) | DEFAULT 'CONFIRMED', INDEX | PENDING_CONFIRM/CONFIRMED/CANCELLED |
| `input_type` | VARCHAR(32) | DEFAULT 'MANUAL' | MANUAL/AI_PARSE |
| `collector_id` | BIGINT | | 采集员ID |
| `created_at` | DATETIME | | 创建时间 |
| `updated_at` | DATETIME | | 更新时间 |

**相关接口**: `POST /cargo/opportunity`, `GET /cargo/opportunity/list`

---

## 7. 模块六：船舶体系

### 7.1 `vessel_type_dict` — 船舶类型字典表

**功能**: 定义船舶种类（散货船/液化气船/集装箱船等），支持审核。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `code` | VARCHAR(32) | UNIQUE, NOT NULL | 船型编码 |
| `name` | VARCHAR(64) | NOT NULL | 船型名称 |
| `name_en` | VARCHAR(128) | | 英文名称 |
| `transport_type` | VARCHAR(32) | DEFAULT 'WATERWAY' | 运输类型 |
| `applicable_goods` | JSON | | 适用货品类型列表 |
| `min_tonnage` | INT | | 最小载重吨(DWT) |
| `max_tonnage` | INT | | 最大载重吨(DWT) |
| `description` | VARCHAR(512) | | 描述 |
| `sort_order` | INT | NOT NULL, DEFAULT 0 | 排序 |
| `status` | TINYINT | NOT NULL, DEFAULT 1 | 1=启用, 0=停用 |
| `audit_status` | TINYINT | DEFAULT 1 | 0=待审核, 1=已通过, 2=已驳回 |
| `submitter_id` | BIGINT | | 提交人ID |
| `auditor_id` | BIGINT | | 审核人ID |
| `created_at` | DATETIME | | 创建时间 |
| `updated_at` | DATETIME | | 更新时间 |

---

### 7.2 `vessel` — 船舶主档案表

**功能**: 存储船舶的基本信息（尺度、船东、AIS等），以船检证书号为业务唯一标识。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `vessel_no` | VARCHAR(64) | UNIQUE, NOT NULL | 船舶检验证书号 |
| `vessel_name` | VARCHAR(128) | NOT NULL | 当前船名 |
| `mmsi` | VARCHAR(20) | INDEX | AIS编号/MMSI |
| `call_sign` | VARCHAR(32) | | 船舶呼号 |
| `vessel_type_id` | BIGINT | FK → vessel_type_dict | 船舶类型ID |
| `deadweight` | INT | | 载重吨(DWT) |
| `gross_tonnage` | DECIMAL(12,2) | | 总吨 |
| `net_tonnage` | DECIMAL(12,2) | | 净吨 |
| `length` | DECIMAL(8,2) | | 船长(m) |
| `breadth` | DECIMAL(8,2) | | 船宽(m) |
| `depth` | DECIMAL(8,2) | | 型深(m) |
| `max_draft` | DECIMAL(8,3) | | 最大吃水(m) |
| `build_year` | INT | | 建造年份 |
| `build_country` | VARCHAR(64) | | 建造国家 |
| `build_city` | VARCHAR(64) | | 建造地 |
| `home_port` | VARCHAR(128) | | 船籍港 |
| `flag` | VARCHAR(32) | DEFAULT '中国' | 船旗国 |
| `owner_name` | VARCHAR(128) | | 船东名称 |
| `contact_phone` | VARCHAR(32) | | 联系电话 |
| `data_status` | TINYINT | DEFAULT 1 | 1=有效, 0=注销 |
| `is_deleted` | TINYINT | DEFAULT 0 | 软删除标记 |
| `audit_status` | TINYINT | DEFAULT 1 | 0=待审核, 1=已通过, 2=已驳回 |
| `audit_remark` | VARCHAR(512) | | 审核意见 |
| `submitter_id` | BIGINT | | 提交人ID |
| `auditor_id` | BIGINT | | 审核人ID |
| `created_at` | DATETIME | | 创建时间 |
| `updated_at` | DATETIME | | 更新时间 |

**相关接口**: `POST /vessel`, `GET /vessel/list`, `PUT /vessel/{id}`, `POST /vessel/{id}/approve`

---

### 7.3 `vessel_name_history` — 船名变更历史表

**功能**: 记录船舶的所有改名记录，保留完整历史链。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `vessel_id` | BIGINT | FK → vessel, NOT NULL | 船舶ID |
| `old_name` | VARCHAR(128) | NOT NULL | 原船名 |
| `new_name` | VARCHAR(128) | NOT NULL | 新船名 |
| `change_reason` | VARCHAR(256) | | 变更原因 |
| `changed_by` | BIGINT | | 操作人ID |
| `changed_at` | DATETIME | | 变更时间 |
| `created_at` | DATETIME | | 创建时间 |

---

### 7.4 `vessel_ais_history` — AIS/MMSI 变更历史表

**功能**: 记录船舶 MMSI 变更记录，避免 AIS 数据错误导致船舶追踪混乱。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `vessel_id` | BIGINT | FK → vessel, NOT NULL | 船舶ID |
| `old_mmsi` | VARCHAR(20) | NOT NULL | 原MMSI |
| `new_mmsi` | VARCHAR(20) | NOT NULL | 新MMSI |
| `change_reason` | VARCHAR(256) | | 变更原因 |
| `changed_by` | BIGINT | | 操作人ID |
| `changed_at` | DATETIME | | 变更时间 |
| `created_at` | DATETIME | | 创建时间 |

---

### 7.5 `vessel_dynamic` — 船舶动态信息表

**功能**: 维护每艘船最新的实时位置和状态（每船唯一一条），支持地图热力展示。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `vessel_id` | BIGINT | FK → vessel, UNIQUE | 船舶ID（每船只有一条） |
| `current_longitude` | DECIMAL(11,8) | | 当前经度 |
| `current_latitude` | DECIMAL(10,8) | | 当前纬度 |
| `current_node_id` | BIGINT | FK → transport_node | 当前所在节点ID |
| `vessel_status` | VARCHAR(32) | DEFAULT 'UNDERWAY', INDEX | EMPTY/LOADED/IN_PORT/ANCHORED/UNDERWAY/MAINTENANCE |
| `current_draft` | DECIMAL(8,3) | | 当前吃水(m) |
| `dest_node_id` | BIGINT | FK → transport_node | 目的港节点ID |
| `eta` | DATETIME | | 预计到达时间 |
| `speed` | DECIMAL(5,2) | | 当前航速(节) |
| `heading` | DECIMAL(5,2) | | 当前船首向(度) |
| `cargo_info` | VARCHAR(256) | | 当前载货信息 |
| `remark` | VARCHAR(512) | | 备注 |
| `updated_by` | BIGINT | | 更新人ID |
| `created_at` | DATETIME | | 创建时间 |
| `updated_at` | DATETIME | | 更新时间 |

---

## 8. 模块七：航线体系

### 8.1 `shipping_route` — 商业航线表

**功能**: 定义起终区域之间的商业航线，用于货源的航线匹配和运力调度。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `code` | VARCHAR(32) | UNIQUE, NOT NULL | 航线编码 |
| `name` | VARCHAR(128) | NOT NULL | 航线名称 |
| `origin_region_id` | BIGINT | FK → region, NOT NULL | 起始区域ID |
| `dest_region_id` | BIGINT | FK → region, NOT NULL | 目的区域ID |
| `distance_km` | DECIMAL(10,2) | | 航线距离(km) |
| `duration_hours` | DECIMAL(8,2) | | 标准航行时长(小时) |
| `description` | VARCHAR(512) | | 航线描述 |
| `sort_order` | INT | NOT NULL, DEFAULT 0 | 排序 |
| `status` | TINYINT | NOT NULL, DEFAULT 1 | 1=启用, 0=停用 |
| `created_by` | BIGINT | | 创建人ID |
| `created_at` | DATETIME | | 创建时间 |
| `updated_at` | DATETIME | | 更新时间 |

---

### 8.2 `shipping_route_path` — 航线路径节点表

**功能**: 记录航线途经的真实航道节点序列（包含起止点和途经中间节点），用于路径渲染和里程计算。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `route_id` | BIGINT | FK → shipping_route, NOT NULL | 航线ID |
| `node_id` | BIGINT | FK → transport_node, NOT NULL | 途经节点ID |
| `sequence` | INT | NOT NULL | 序号（从1开始） |
| `distance_from_start` | DECIMAL(10,2) | | 距起点距离(km) |
| `node_role` | VARCHAR(32) | DEFAULT 'WAYPOINT' | START/WAYPOINT/END |
| `created_at` | DATETIME | | 创建时间 |
| `updated_at` | DATETIME | | 更新时间 |

---

## 9. 模块八：统计分析

### 9.1 `heatmap_stat_daily` — 热力统计日表

**功能**: 按节点、日期、统计类型聚合货源和运力数据，供地图热力图展示使用（每日定时任务生成）。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO | 主键 |
| `stat_date` | DATE | NOT NULL, UNIQUE(stat_date,node_id,stat_type) | 统计日期 |
| `node_id` | BIGINT | FK → transport_node, NOT NULL | 运输节点ID |
| `stat_type` | VARCHAR(32) | NOT NULL | CARGO_ORIGIN=装货统计, CARGO_DEST=卸货统计, VESSEL=运力统计 |
| `cargo_count` | INT | DEFAULT 0 | 货源数量 |
| `total_tonnage` | DECIMAL(16,2) | DEFAULT 0 | 总吨位(吨) |
| `vessel_count` | INT | DEFAULT 0 | 船舶数量 |
| `total_deadweight` | DECIMAL(16,2) | DEFAULT 0 | 总载重吨(DWT) |
| `created_at` | DATETIME | | 创建时间 |
| `updated_at` | DATETIME | | 更新时间 |

**相关接口**: `GET /analysis/heatmap?date=2026-03-16`

---

## 10. 表间关系 ER 概览

```
sys_user ──────────────── sys_user_role ─────── sys_role
                                │
                          (submitter_id/auditor_id 引用 sys_user.id，逻辑外键)

waterway (自关联树形)
    │
    └─── transport_node ──── node_type
             │    │    │
             │    │    └─── waterway
             │    │
             │    └─── region
             │
             ├─── node_alias (唯一别名)
             └─── region_address_relation

admin_region (自关联树形)
    └─── (level=2 坐标 → region.main_cities 自动圈城市)

region ─────┬─── shipping_route (origin/dest)
            ├─── cargo_opportunity (origin/dest region)
            └─── region_address_relation

commodity_category → commodity_type → commodity_standard → commodity_alias

cargo_raw_message → cargo_ai_parse_result → cargo_opportunity

vessel_type_dict → vessel ─┬─── vessel_name_history
                            ├─── vessel_ais_history
                            └─── vessel_dynamic

shipping_route → shipping_route_path

transport_node ─── heatmap_stat_daily
transport_node ─── cargo_opportunity (origin/dest)
transport_node ─── cargo_ai_parse_result (origin/dest)
transport_node ─── vessel_dynamic (current/dest)
transport_node ─── shipping_route_path

audit_record ─── (target_type + target_id 逻辑引用所有业务表)
```

---

## 11. 接口与表映射

| API 路径 | HTTP方法 | 主要操作表 | 功能说明 |
|----------|----------|-----------|---------|
| `/auth/login` | POST | sys_user, sys_user_role, sys_role | 用户登录 |
| `/auth/users` | GET/POST | sys_user | 用户管理 |
| `/address/waterway` | GET/POST | waterway | 水系查询/新增 |
| `/address/waterway/{id}` | PUT/DELETE | waterway | 水系修改/删除 |
| `/address/waterway/{id}/toggle-status` | POST | waterway | 水系启用/停用 |
| `/address/admin-region/list` | GET | admin_region | 行政区划查询 |
| `/address/admin-region` | POST | admin_region | 行政区划新增 |
| `/address/node-type/list` | GET | node_type | 节点类型列表 |
| `/address/node-type` | POST | node_type | 节点类型新增 |
| `/address/region` | POST | region, admin_region | 区域新增（自动计算质心/城市） |
| `/address/region/list` | GET | region, waterway, admin_region | 区域分页查询（展开水系/城市） |
| `/address/region/{id}` | PUT | region, admin_region | 区域修改（需 status=0） |
| `/address/region/{id}/toggle-status` | POST | region | 区域启用/停用 |
| `/address/region/{id}/approve` | POST | region, audit_record | 区域审批通过 |
| `/address/region/{id}/reject` | POST | region, audit_record | 区域审批驳回 |
| `/address/node` | POST | transport_node | 节点新增 |
| `/address/node/list` | GET | transport_node, node_alias | 节点分页查询 |
| `/address/node/{id}` | PUT/DELETE | transport_node | 节点修改/删除 |
| `/address/node/{id}/approve` | POST | transport_node, audit_record | 节点审批通过 |
| `/address/node/search` | GET | transport_node, node_alias | 节点模糊搜索 |
| `/address/node/alias` | POST | node_alias | 新增节点别名 |
| `/cargo/category/list` | GET | commodity_category | 货品大类查询 |
| `/cargo/category` | POST | commodity_category | 货品大类新增 |
| `/cargo/type/list` | GET | commodity_type | 货品类型查询 |
| `/cargo/standard/list` | GET | commodity_standard, commodity_alias | 标准货品查询 |
| `/cargo/raw-message` | POST | cargo_raw_message | 原始货源提交 |
| `/cargo/raw-message/list` | GET | cargo_raw_message | 原始货源列表 |
| `/cargo/parse-result/list` | GET | cargo_ai_parse_result | AI解析结果列表 |
| `/cargo/opportunity` | POST | cargo_opportunity | 货源录入 |
| `/cargo/opportunity/list` | GET | cargo_opportunity | 货源列表 |
| `/vessel` | POST | vessel | 船舶新增 |
| `/vessel/list` | GET | vessel | 船舶列表 |
| `/vessel/{id}/approve` | POST | vessel, audit_record | 船舶审批通过 |
| `/vessel/{id}/dynamic` | GET/PUT | vessel_dynamic | 船舶动态查看/更新 |
| `/route` | POST | shipping_route | 航线新增 |
| `/route/list` | GET | shipping_route | 航线列表 |
| `/analysis/heatmap` | GET | heatmap_stat_daily | 热力统计查询 |

---

## 12. SQLite 切换到 MySQL 完整指南

### 12.1 当前架构（开发环境）

```
# .env.local（开发环境）
DATABASE_URL=sqlite+aiosqlite:///./dev.db
```

- **驱动**: `aiosqlite`（异步 SQLite）
- **迁移**: Alembic，`batch_alter_table` 模式（SQLite 不支持 ALTER COLUMN）
- **局限**: 不支持并发写入、无完整外键约束、JSON 索引受限

---

### 12.2 MySQL 生产环境准备

#### 第一步：安装 MySQL 异步驱动

```bash
# 推荐：aiomysql（兼容 MySQL 8.0 + SQLAlchemy 2.x async）
pip install aiomysql cryptography

# 或使用 asyncmy（纯异步，更快）
pip install asyncmy

# 更新 requirements.txt
echo "aiomysql>=0.2.0" >> requirements.txt
echo "cryptography>=41.0.0" >> requirements.txt
```

#### 第二步：修改 `DATABASE_URL`

```bash
# .env.production
# aiomysql 驱动
DATABASE_URL=mysql+aiomysql://user:password@host:3306/inland_shipping?charset=utf8mb4

# asyncmy 驱动（二选一）
DATABASE_URL=mysql+asyncmy://user:password@host:3306/inland_shipping?charset=utf8mb4
```

**URL 格式说明**:
```
mysql+aiomysql://{用户名}:{密码}@{主机}:{端口}/{数据库名}?charset=utf8mb4
```

#### 第三步：修改 `alembic.ini`

```ini
# alembic.ini
[alembic]
# 生产环境 MySQL，从环境变量读取
sqlalchemy.url = mysql+aiomysql://user:password@host:3306/inland_shipping?charset=utf8mb4
```

**推荐做法**：通过 `env.py` 动态读取环境变量，避免密码明文写入 `alembic.ini`：

```python
# alembic/env.py
import os
from dotenv import load_dotenv

load_dotenv()

config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
```

#### 第四步：修改 `app/core/database.py`

当前代码已使用 `create_async_engine`，切换 MySQL 只需更换 URL，**无需修改引擎创建代码**：

```python
# app/core/database.py（当前代码，不需要改）
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

engine = create_async_engine(settings.DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
```

---

### 12.3 MySQL 上初始化表结构

#### 方案 A：直接执行 SQL 文件（推荐首次上线）

```bash
# 1. 登录 MySQL 并执行建表脚本
mysql -h 127.0.0.1 -u root -p < docs/init_mysql.sql

# 或指定用户
mysql -h your-mysql-host -P 3306 -u inland_user -p inland_shipping < docs/init_mysql.sql
```

#### 方案 B：通过 Alembic 初始化（适合后续持续迁移）

```bash
# 1. 确保数据库已创建
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS inland_shipping CHARACTER SET utf8mb4;"

# 2. 设置 DATABASE_URL 为 MySQL
export DATABASE_URL="mysql+aiomysql://user:password@localhost:3306/inland_shipping?charset=utf8mb4"

# 3. 生成初始迁移（如果还没有）
alembic revision --autogenerate -m "initial_mysql_migration"

# 4. 执行迁移
alembic upgrade head
```

> **注意**: 如果已有 SQLite 的 Alembic 迁移历史，切换到 MySQL 时建议先手动执行 `init_mysql.sql` 再通过 `alembic stamp head` 标记当前状态，避免重复执行已完成的迁移。

```bash
# 已用 init_mysql.sql 初始化后，跳过迁移历史，直接标记当前版本
alembic stamp head
```

---

### 12.4 代码层面需要修改的内容

切换 MySQL 时，大部分代码**无需修改**，以下是需要注意的点：

#### ✅ 无需修改的部分
- `app/repositories/` — 所有 SQLAlchemy 查询语句
- `app/services/` — 业务逻辑层
- `app/api/` — API 路由层
- `app/schemas/` — Pydantic 模型
- `app/models/` — SQLAlchemy ORM 模型（已使用标准类型）

#### ⚠️ 需要检查/修改的地方

**1. Alembic 迁移脚本中的 `batch_alter_table`**

SQLite 限制 ALTER TABLE，项目中使用了 `batch_alter_table`，在 MySQL 下会自动使用标准 `ALTER TABLE`，**无需手动修改**，Alembic 会自动处理。

但如果迁移脚本中有 `with op.batch_alter_table(...) as batch_op:`，在 MySQL 环境下也可以正常运行（`batch` 对 MySQL 是透明的）。

**2. JSON 字段**

本项目使用了 `JSON` 类型字段（`region.main_rivers`, `region.main_cities` 等），MySQL 8.0 原生支持 JSON 类型，**无需修改**。

> 注意：MySQL 5.7 也支持 JSON，但建议使用 8.0+。

**3. DECIMAL 精度**

`DECIMAL(11,8)` 用于经纬度，MySQL 完全支持，**无需修改**。

**4. `server_default=func.now()`**

SQLAlchemy 的 `func.now()` 在 MySQL 上会生成 `CURRENT_TIMESTAMP`，**无需修改**。

**5. 字符串长度与 `VARCHAR`**

MySQL utf8mb4 下，每个字符最多占 4 字节。`VARCHAR(255)` 以内完全没问题，本项目最长为 `VARCHAR(512)`，**无需修改**。

**6. 环境变量配置**

```python
# app/core/config.py（建议）
class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./dev.db"  # 开发默认值

    class Config:
        env_file = ".env"
```

部署时设置环境变量或 `.env` 文件中的 `DATABASE_URL` 即可，**无需修改代码**。

---

### 12.5 上线前完整操作流程

```bash
# ① 在 MySQL 服务器上创建数据库
mysql -u root -p -e "
  CREATE DATABASE IF NOT EXISTS inland_shipping
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;
  CREATE USER IF NOT EXISTS 'inland_user'@'%' IDENTIFIED BY 'your_password';
  GRANT ALL PRIVILEGES ON inland_shipping.* TO 'inland_user'@'%';
  FLUSH PRIVILEGES;
"

# ② 初始化表结构
mysql -u inland_user -p inland_shipping < docs/init_mysql.sql

# ③ 设置生产环境变量
export DATABASE_URL="mysql+aiomysql://inland_user:your_password@mysql-host:3306/inland_shipping?charset=utf8mb4"

# ④ 标记 Alembic 迁移状态（表已由 SQL 脚本创建，跳过重复执行）
alembic stamp head

# ⑤ 启动应用
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

### 12.6 常见问题

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| `Access denied for user` | 数据库用户权限不足 | 确认 GRANT 授权 |
| `Unknown character set: 'utf8mb4'` | MySQL 版本过低 | 升级到 MySQL 5.7+ |
| `Table already exists` | 重复执行 SQL 脚本 | SQL 脚本已使用 `CREATE TABLE IF NOT EXISTS`，可安全重复执行 |
| `asyncmy.errors.OperationalError: (1045, ...)` | 密码错误 | 检查 DATABASE_URL 中的密码 |
| `JSON column type not supported` | MySQL 版本 < 5.7 | 升级到 MySQL 5.7+，或将 JSON 改为 TEXT |
| `ModuleNotFoundError: No module named 'aiomysql'` | 驱动未安装 | `pip install aiomysql` |
