# 中国内河航运数据采集与分析平台

> **AI Native Clean Architecture · V2.0**
> 面向内河航运 / 水运物流行业的货源采集、船舶管理、运输节点维护、航运数据分析一体化平台

[![FastAPI](https://img.shields.io/badge/FastAPI-0.128-009688)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB)](https://www.python.org)
[![Claude AI](https://img.shields.io/badge/Claude-AI%20Engine-6B46C1)](https://anthropic.com)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0%20Async-red)](https://sqlalchemy.org)
[![Alembic](https://img.shields.io/badge/Alembic-Migration-blue)](https://alembic.sqlalchemy.org)

---

## 目录

1. [项目介绍](#1-项目介绍)
2. [系统整体架构](#2-系统整体架构)
3. [项目目录结构说明](#3-项目目录结构说明)
4. [数据库设计](#4-数据库设计)
5. [API 模块说明](#5-api-模块说明)
6. [API 接口详细说明](#6-api-接口详细说明)
7. [核心业务模块说明](#7-核心业务模块说明)
8. [本地开发环境部署](#8-本地开发环境部署)
9. [生产环境部署](#9-生产环境部署)
10. [数据库初始化](#10-数据库初始化)
11. [服务启动流程](#11-服务启动流程)
12. [系统运行流程](#12-系统运行流程)
13. [后续扩展方向](#13-后续扩展方向)

---

## 1. 项目介绍

### 1.1 项目名称

**中国内河航运数据采集与分析平台**（Inland Shipping Platform）

### 1.2 项目目标

为内河航运行业提供完整的数字化管理系统，覆盖货源信息采集与 AI 解析、船舶档案管理、运输节点与水系维护、商业区域管理、航线规划，以及多维航运数据统计分析。系统以 **AI Agent 为驱动核心**，实现从原始货运文本到结构化货源数据的自动化流程。

### 1.3 主要解决的问题

| 业务痛点 | 解决方案 |
|----------|----------|
| 货运信息以微信群自然语言文本传播，人工录入效率低、错误率高 | AI Agent（Claude）自动解析文本，提取货品、吨位、起止节点等结构化字段，附置信度评分 |
| 多人协作录入数据缺乏审核把关，数据质量差 | 统一审核体系，运输节点、船舶、区域等 10 类对象均需经过提交→审核→通过工作流 |
| 货源、船舶、区域等数据没有统计汇总，难以分析趋势 | 每日 ETL 任务将业务数据聚合到 8 张统计表，提供热力图、趋势、区域分布等分析接口 |
| 船舶频繁改名/更换 AIS，无历史追踪 | 船名变更、AIS/MMSI 变更均自动记录到历史表，支持全生命周期追溯 |
| 运输节点地名写法多样，AI 难以精准匹配 | 节点别名体系 + 模糊匹配工具，"龙潭码头"/"龙潭港"均可匹配到同一节点 |

### 1.4 系统适用行业

- 内河航运物流企业
- 水运货代平台
- 港口 / 码头管理机构
- 航运大数据服务商

---

## 2. 系统整体架构

### 2.1 技术栈

| 层次 | 技术选型 |
|------|----------|
| Web 框架 | FastAPI 0.128 + Uvicorn |
| ORM | SQLAlchemy 2.0（async） |
| 数据库（开发） | SQLite + aiosqlite |
| 数据库（生产） | MySQL 8.0+ / PostgreSQL 14+ |
| 数据库迁移 | Alembic（异步模式，SQLite batch 兼容） |
| 认证与授权 | JWT（python-jose）+ bcrypt + RBAC |
| AI 集成 | Anthropic Claude API（claude-sonnet-4-6） |
| 任务队列（生产） | Celery + Redis |
| 定时任务（开发） | APScheduler（AsyncIOScheduler） |
| 数据校验 | Pydantic v2 |

### 2.2 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│                      客户端 / 前端应用                       │
│           REST API · HTTP/JSON · JWT Bearer Token           │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│                    API 层（FastAPI Router）                   │
│  auth · system · address · cargo · vessel · route          │
│  analysis/cargo · analysis/ship · audit · ai                │
│  职责：参数校验、JWT 鉴权、角色验证、响应格式化              │
│  规则：禁止包含业务逻辑，禁止直接操作数据库                  │
└──────────────────────┬─────────────────────────────────────-┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                 Service 层（业务逻辑编排）                    │
│  CargoService · VesselService · AddressService              │
│  RouteService · AnalysisService · AuditService              │
│  职责：编排业务流程，调用 Repository，禁止直接写 SQL         │
└──────────┬──────────────────────────┬───────────────────────┘
           │                          │
┌──────────▼───────────┐  ┌───────────▼──────────────────────┐
│  Repository 层        │  │     AI 层（异步 Agent 编排）       │
│  *Repository classes  │  │  Agent → Tool → Workflow         │
│  职责：封装全部 SQL   │  │  CargoAgent · AnalysisAgent      │
│  查询，返回 ORM 对象  │  │  cargo_tools · entity_match       │
└──────────┬────────────┘  └───────────┬──────────────────────┘
           │                           │
┌──────────▼───────────────────────────▼──────────────────────┐
│                    数据库层（SQLAlchemy Models）               │
│  SQLite（开发）  /  MySQL · PostgreSQL（生产）               │
│  32 张业务表 + 8 张统计表 · 3 次 Alembic 增量迁移          │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│               后台任务层（Tasks / Scheduler）                  │
│  stat_tasks.py ── 每日 02:00 ETL → 8 张统计表              │
│  ai_tasks.py   ── AI 货源解析（BackgroundTask / Celery）    │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 权限角色

| 角色代码 | 角色名称 | 权限范围 |
|----------|----------|----------|
| `SUPER_ADMIN` | 超级管理员 | 全部权限，可审核自己提交的内容 |
| `ADMIN` | 管理员 | 审核权限 + 数据管理，不可自审 |
| `OPERATOR` | 运营人员 | 数据录入 + 部分管理操作 |
| `COLLECTOR` | 数据采集员 | 货源采集 + 只读查看 |

---

## 3. 项目目录结构说明

```
inland-shipping-platform/
│
├── main.py                        # FastAPI 应用主入口，应用生命周期管理
├── requirements.txt               # Python 依赖列表（含版本锁定）
├── alembic.ini                    # Alembic 数据库迁移配置
├── Makefile                       # 常用命令快捷方式
├── start.sh                       # 生产环境一键启动脚本
├── inland_shipping.db             # SQLite 数据库文件（仅开发环境）
│
├── docs/                          # 项目文档目录
│   ├── ARCHITECTURE.md            # AI Native 系统架构详细说明
│   ├── DB_DESIGN.md               # 数据库设计文档（全部 32 张表）
│   ├── DEPLOYMENT.md              # 生产环境部署指南
│   ├── LOCAL_DEVELOPMENT.md       # 本地开发环境搭建指南
│   └── init_mysql.sql             # MySQL 生产环境完整建表脚本（含索引/外键）
│
├── alembic/                       # 数据库增量迁移管理
│   ├── env.py                     # 异步迁移配置（SQLite batch render 兼容）
│   ├── script.py.mako             # 迁移文件模板
│   └── versions/
│       ├── 0001_add_region_audit_fields.py        # 区域审核字段
│       ├── 0002_add_audit_task_and_unified_fields.py  # 统一审核体系重构
│       └── 0003_add_analysis_stat_tables.py       # 8 张统计分析日表
│
├── app/
│   │
│   ├── core/                      # 基础设施层（Cross-cutting concerns）
│   │   ├── config.py              # Pydantic Settings，从 .env 读取全部配置
│   │   ├── database.py            # SQLAlchemy 异步引擎 / Session 工厂 / init_db
│   │   ├── security.py            # JWT 生成校验 / bcrypt / RBAC 依赖函数
│   │   ├── dependencies.py        # FastAPI 依赖注入中心（所有 Repository/Service）
│   │   ├── logging.py             # 日志初始化与配置
│   │   └── exceptions.py          # 统一业务异常类 AppException（含 HTTP 状态码映射）
│   │
│   ├── models/                    # SQLAlchemy ORM 数据模型（32 张表）
│   │   ├── base.py                # DeclarativeBase + TimestampMixin（自动时间戳）
│   │   ├── system.py              # SysUser · SysRole · SysUserRole（用户权限体系）
│   │   ├── address.py             # Waterway · Region · AdminRegion · NodeType
│   │   │                          # TransportNode · NodeAlias · RegionAddressRelation
│   │   ├── cargo.py               # CommodityCategory · CommodityType · CommodityStandard
│   │   │                          # CommodityAlias · CargoRawMessage
│   │   │                          # CargoAiParseResult · CargoOpportunity
│   │   ├── vessel.py              # VesselTypeDict · Vessel · VesselNameHistory
│   │   │                          # VesselAisHistory · VesselDynamic
│   │   ├── route.py               # ShippingRoute · ShippingRoutePath
│   │   ├── analysis.py            # 8 张统计日表（HeatmapStatDaily + 新增7张）
│   │   └── audit.py               # AuditTask · AuditRecord（统一审核体系）
│   │
│   ├── schemas/                   # Pydantic 请求/响应数据模型（Schema Layer）
│   │   ├── common.py              # 统一响应格式 success() / ApiResponse
│   │   ├── auth.py                # TokenResponse · UserInfo
│   │   ├── system.py              # UserCreate / UserUpdate / UserResponse
│   │   ├── address.py             # Waterway/Region/Node 系列 Schema
│   │   ├── cargo.py               # 货源及商品分类系列 Schema
│   │   ├── vessel.py              # 船舶系列 Schema
│   │   ├── route.py               # 航线系列 Schema
│   │   ├── analysis.py            # 统计分析系列 Schema
│   │   └── audit.py               # 审核任务系列 Schema
│   │
│   ├── repositories/              # 数据访问层（Repository Pattern）
│   │   ├── base.py                # BaseRepository 基类（通用查询方法）
│   │   ├── address_repository.py  # 水系/区域/节点/别名 CRUD 查询
│   │   ├── cargo_repository.py    # 货源/商品分类 CRUD 查询
│   │   ├── vessel_repository.py   # 船舶 CRUD + 历史记录写入
│   │   ├── route_repository.py    # 航线及路径节点 CRUD
│   │   ├── analysis_repository.py # 统计表读取 + upsert（只读统计表）
│   │   ├── audit_repository.py    # 审核任务 CRUD + 历史记录
│   │   └── system_repository.py   # 用户/角色 CRUD
│   │
│   ├── services/                  # 业务逻辑层（Service Layer）
│   │   ├── address_service.py     # 地址业务（水系编码自动生成/区域质心/审核集成）
│   │   ├── cargo_service.py       # 货源业务（AI 解析触发/确认流程/手动录入）
│   │   ├── vessel_service.py      # 船舶业务（历史追踪/审核集成）
│   │   ├── route_service.py       # 航线管理业务
│   │   ├── analysis_service.py    # 统计分析（只读统计表，组装 API 响应数据）
│   │   └── audit_service.py       # 统一审核工作流（10 类对象通用审核逻辑）
│   │
│   ├── api/v1/                    # REST API 路由层（HTTP 接入层）
│   │   ├── __init__.py            # 总路由聚合，注册所有子路由到 api_router
│   │   ├── auth/router.py         # 认证接口（登录/登出/当前用户）
│   │   ├── system/router.py       # 用户与角色管理接口
│   │   ├── address/router.py      # 水系/区域/行政区/节点类型/运输节点接口
│   │   ├── cargo/router.py        # 商品分类/货运文本/AI解析/货源机会接口
│   │   ├── vessel/router.py       # 船舶类型/船舶档案/动态/历史接口
│   │   ├── route/router.py        # 航线及路径节点接口
│   │   ├── analysis/
│   │   │   ├── router.py          # 分析主路由（含旧版兼容接口）
│   │   │   ├── cargo_analysis.py  # 货源分析接口（热力图/趋势/排名/区域）
│   │   │   └── ship_analysis.py   # 船舶分析接口（热力图/类型/船龄/运力）
│   │   ├── audit/router.py        # 审核中心接口（任务列表/审批/驳回/历史）
│   │   └── ai/router.py           # AI 功能接口
│   │
│   ├── ai/                        # AI 基础框架层
│   │   ├── base.py                # BaseTool / BaseAgent / BaseWorkflow 抽象基类
│   │   ├── llm_client.py          # Anthropic Claude 异步客户端封装（含重试/限流处理）
│   │   └── prompt_templates.py    # 系统提示词模板管理
│   │
│   ├── agents/                    # AI Agent 实现
│   │   ├── cargo_agent.py         # 货源文本解析 Agent（调用 Claude API）
│   │   └── analysis_agent.py      # 数据分析 Agent（AI 趋势分析，可选）
│   │
│   ├── workflows/                 # AI 工作流编排
│   │   └── cargo_parse_workflow.py # 端到端货源解析工作流（Agent + Tool 组合）
│   │
│   ├── tools/                     # AI Tools（可复用工具函数）
│   │   ├── cargo_tools.py         # 货源信息提取工具
│   │   ├── entity_match_tools.py  # 实体模糊匹配（节点/货品别名库匹配）
│   │   ├── geo_tools.py           # 地理信息处理工具
│   │   └── database_tools.py      # 数据库查询工具（供 AI Tool 使用）
│   │
│   ├── tasks/                     # 后台异步任务
│   │   ├── scheduler.py           # APScheduler 配置（开发模式定时任务）
│   │   ├── celery_app.py          # Celery 实例定义（生产模式）
│   │   ├── stat_tasks.py          # 每日统计 ETL（8 张统计表聚合，唯一读业务表的统计代码）
│   │   ├── ai_tasks.py            # AI 解析异步任务（BackgroundTask/Celery 双模式）
│   │   ├── analysis_tasks.py      # 统计聚合 Celery 任务封装
│   │   └── dispatch_tasks.py      # 货船匹配调度（框架预留，V2 实现）
│   │
│   └── utils/                     # 工具函数库
│       ├── text_utils.py          # 文本处理工具
│       ├── waterway_code_generator.py  # 水系编码自动生成算法
│       └── region_helpers.py      # 区域质心计算 / 城市圈定等地理辅助函数
│
└── scripts/
    └── seed_data.py               # 数据库初始种子数据（角色/用户/货品分类/水系/节点）
```

---

## 4. 数据库设计

### 4.1 设计理念

系统数据库采用 **ETL 双表分离架构**：

- **业务表**（32 张）：存储实时操作数据，通过 Alembic 增量迁移管理，读写并发
- **统计表**（8 张）：每日凌晨 02:00 由 ETL 任务从业务表聚合写入，分析 API **仅读统计表**，响应时间 < 200ms

所有业务表均包含 `created_at` / `updated_at` 自动时间戳。涉及多角色协作的对象还包含 `audit_status`（0=待审核 / 1=已通过 / 2=已驳回）、`submitter_id`、`audit_task_id` 等审核字段。

### 4.2 核心表说明

#### 系统管理（3 张表）

| 表名 | 说明 |
|------|------|
| `sys_user` | 系统用户，含用户名/密码哈希/手机/邮箱/部门/微信 OpenID/状态 |
| `sys_role` | 角色字典，预定义 4 种角色（SUPER_ADMIN / ADMIN / OPERATOR / COLLECTOR） |
| `sys_user_role` | 用户-角色多对多关联表 |

#### 审核中心（2 张表）

| 表名 | 说明 |
|------|------|
| `audit_task` | 审核任务，记录待审核对象类型（target_type）、对象 ID（target_id）、提交人、状态 |
| `audit_record` | 审核操作历史，记录审核人/审核结果/意见/时间，供审计追溯 |

#### 地址与节点（7 张表）

| 表名 | 说明 |
|------|------|
| `waterway` | 水系，支持父子层级（parent_id），编码由系统自动生成 |
| `region` | 商业区域，含边界多边形坐标（boundary_geojson），质心坐标自动计算，关联水系 / 城市，需审核 |
| `admin_region` | 行政区划，省市县三级，标准行政编码体系 |
| `node_type` | 运输节点类型字典（港口 / 码头 / 锚地 / 水闸等） |
| `transport_node` | 运输节点，内河航运的核心地理单元，含经纬度/所属水系/所属区域，需审核 |
| `node_alias` | 节点别名，同一节点可有多个俗称，供 AI 实体匹配使用 |
| `region_address_relation` | 商业区域与运输节点的从属关系 |

#### 货源管理（7 张表）

| 表名 | 说明 |
|------|------|
| `commodity_category` | 货品大类（煤炭 / 矿石 / 粮食 / 建材 / 化工品等） |
| `commodity_type` | 货品类型，归属大类，细分品种 |
| `commodity_standard` | 货品标准规格，如"无烟煤 5500 大卡" |
| `commodity_alias` | 货品别名，支持 AI 模糊匹配 |
| `cargo_raw_message` | 原始货运文本（采集员粘贴的微信群消息），含解析状态 |
| `cargo_ai_parse_result` | AI 解析结果，含结构化字段与置信度分数（0-100），等待人工确认 |
| `cargo_opportunity` | 正式货源记录，包含起止节点/货品/吨位/装货日期/联系方式/运价，是货源分析的数据来源 |

#### 船舶管理（5 张表）

| 表名 | 说明 |
|------|------|
| `vessel_type_dict` | 船舶类型字典（散货船 / 集装箱船 / 油轮等），需审核 |
| `vessel` | 船舶主档案，含船名/证书号/MMSI/建造年份/总吨/载重吨/所有人 |
| `vessel_name_history` | 船名变更历史，更新船名时自动写入 |
| `vessel_ais_history` | AIS/MMSI 变更历史，更新 MMSI 时自动写入 |
| `vessel_dynamic` | 船舶实时动态，含当前节点/状态/航速/AIS 上报时间 |

#### 航线管理（2 张表）

| 表名 | 说明 |
|------|------|
| `shipping_route` | 商业航线，含起止区域/名称/距离/参考航行时间 |
| `shipping_route_path` | 航线路径节点，有序记录途经的运输节点 |

#### 统计分析（8 张表）

| 表名 | ETL 数据来源 | 说明 |
|------|-------------|------|
| `cargo_heatmap_daily` | cargo_opportunity | 各节点货源数量 + 总吨位（区分装货节点 ORIGIN / 卸货节点 DEST） |
| `ship_heatmap_daily` | vessel_dynamic | 各节点在港 / 在途船舶数量 + 总载重吨 |
| `cargo_stat_daily` | cargo_opportunity | 每日货源汇总（总量/活跃/待确认/总吨位） |
| `cargo_commodity_stat_daily` | cargo_opportunity + join | 各货品大类货源数量 + 吨位 |
| `cargo_region_stat_daily` | cargo_opportunity | 各区域货源分布（区分 ORIGIN/DEST） |
| `ship_capacity_region_daily` | vessel + vessel_dynamic | 各区域船舶数量 + 总载重吨 |
| `ship_type_stat_daily` | vessel | 各船型数量 + 总载重吨 |
| `ship_age_stat_daily` | vessel.build_year | 船龄分布（0-5 / 5-10 / 10-15 / 15-20 / 20+ 年） |

### 4.3 完整 MySQL 建表脚本

生产环境建表脚本位于 `docs/init_mysql.sql`，包含全部 32 张表的字段定义、索引、外键约束及注释。

---

## 5. API 模块说明

系统共 **10 个 API 模块**，全部挂载在 `/api/v1/` 前缀下，当前共约 **106+ 个接口端点**：

| 模块 | 路径前缀 | 主要职责 | 文件路径 |
|------|----------|----------|----------|
| 认证 | `/api/v1/auth` | 登录/登出/当前用户信息 | `app/api/v1/auth/router.py` |
| 系统管理 | `/api/v1/system` | 用户 CRUD、角色查询、密码重置 | `app/api/v1/system/router.py` |
| 地址管理 | `/api/v1/address` | 水系、商业区域、行政区划、节点类型、运输节点及别名 | `app/api/v1/address/router.py` |
| 货源管理 | `/api/v1/cargo` | 商品体系维护、货运文本 AI 解析、货源机会管理 | `app/api/v1/cargo/router.py` |
| 船舶管理 | `/api/v1/vessel` | 船舶类型、船舶档案、动态更新、历史查询 | `app/api/v1/vessel/router.py` |
| 航线管理 | `/api/v1/route` | 航线 CRUD、路径节点管理 | `app/api/v1/route/router.py` |
| 货源分析 | `/api/v1/analysis/cargo` | 热力图、趋势、商品排名、区域分布（只读统计表） | `app/api/v1/analysis/cargo_analysis.py` |
| 船舶分析 | `/api/v1/analysis/ship` | 热力图、类型占比、船龄分布、区域运力（只读统计表） | `app/api/v1/analysis/ship_analysis.py` |
| 审核中心 | `/api/v1/audit` | 统一审核任务列表、审批/驳回操作、审核历史、统计 | `app/api/v1/audit/router.py` |
| AI 功能 | `/api/v1/ai` | AI 功能直接调用 | `app/api/v1/ai/router.py` |

---

## 6. API 接口详细说明

> **鉴权说明：** 所有接口（除 `/auth/login`）均需在请求头携带 JWT Token：
> `Authorization: Bearer <your_token>`
>
> **完整交互文档：** 启动服务后访问 `http://localhost:8000/docs`

---

### 6.1 认证模块（`/api/v1/auth`）

#### `POST /api/v1/auth/login` — 用户登录

| 项 | 说明 |
|----|------|
| Content-Type | `application/x-www-form-urlencoded` |
| 请求参数 | `username`（用户名）、`password`（密码） |
| 返回 | `access_token`、`token_type: bearer`、`user_id`、`username`、`real_name`、`roles[]` |
| 权限 | 无需鉴权 |

**调用链路：**
```
auth/router.py → SysUser（DB 直查） → verify_password → create_access_token → 更新 last_login_at
```

#### `GET /api/v1/auth/me` — 获取当前用户信息

返回当前登录用户的基本信息与角色列表。

#### `POST /api/v1/auth/logout` — 登出

服务端无状态，客户端清除本地 Token 即可。

---

### 6.2 系统管理模块（`/api/v1/system`）

| 方法 | 路径 | 功能 | 所需角色 |
|------|------|------|----------|
| GET | `/users` | 用户列表（分页 + 关键词搜索 + 状态筛选） | ADMIN+ |
| POST | `/users` | 创建用户（含角色分配） | ADMIN+ |
| PUT | `/users/{id}` | 更新用户信息及角色 | ADMIN+ |
| DELETE | `/users/{id}` | 删除用户 | SUPER_ADMIN |
| POST | `/users/{id}/disable` | 禁用用户 | ADMIN+ |
| POST | `/users/{id}/enable` | 启用用户 | ADMIN+ |
| POST | `/users/{id}/reset-password` | 重置用户密码 | ADMIN+ |
| GET | `/roles` | 获取角色列表 | ADMIN+ |

**调用链路：**
```
system/router.py → AsyncSession（直接 DB） → SysUser / SysRole / SysUserRole 表
```

---

### 6.3 地址管理模块（`/api/v1/address`）

#### 水系管理

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/waterway` | 获取水系列表（可按状态过滤） |
| GET | `/waterway/list` | 分页查询（名称模糊 / 编码精确 / 状态） |
| POST | `/waterway` | 创建水系（**编码自动生成**） |
| PUT | `/waterway/{id}` | 更新水系 |
| DELETE | `/waterway/{id}` | 删除水系 |
| POST | `/waterway/{id}/toggle-status` | 启用 / 停用（自动取反当前状态） |

#### 商业区域管理

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/region` | 获取区域列表（不分页） |
| GET | `/region/list` | 分页查询（展开水系 / 城市详情） |
| POST | `/region` | 创建区域（**编码/质心/城市自动计算**，提交待审核） |
| PUT | `/region/{id}` | 更新区域（仅限停用状态，修改后需重新审核） |
| DELETE | `/region/{id}` | 删除区域 |
| POST | `/region/{id}/toggle-status` | 启用 / 停用 |
| POST | `/region/{id}/approve` | 审批通过（提交人不可自审） |
| POST | `/region/{id}/reject` | 驳回审批（必须填写驳回意见） |
| GET | `/region/{id}/nodes` | 获取区域内的运输节点 |

#### 行政区划管理

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/admin-region` | 行政区划列表（可按级别 / 父编码过滤） |
| POST | `/admin-region` | 创建行政区划 |
| PUT | `/admin-region/{id}` | 更新行政区划 |

#### 节点类型管理

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/node-type` | 节点类型列表 |
| POST | `/node-type` | 创建节点类型 |
| PUT | `/node-type/{id}` | 更新节点类型 |
| DELETE | `/node-type/{id}` | 删除节点类型 |

#### 运输节点管理

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/transport-node/search` | **按名称或别名模糊搜索节点**（AI 实体匹配入口） |
| GET | `/transport-node` | 节点列表（分页 + 多条件过滤） |
| POST | `/transport-node` | 创建节点（提交待审核） |
| GET | `/transport-node/{id}` | 节点详情 |
| PUT | `/transport-node/{id}` | 更新节点 |
| DELETE | `/transport-node/{id}` | 删除节点 |
| POST | `/transport-node/{id}/aliases` | 添加节点别名 |
| DELETE | `/transport-node/{id}/aliases/{alias_id}` | 删除节点别名 |
| POST | `/transport-node/{id}/approve` | 审批通过节点（提交人不可自审） |
| POST | `/transport-node/{id}/reject` | 驳回节点（必须填写意见） |

**调用链路：**
```
address/router.py
  → AddressService（address_service.py）
    → AddressRepository（address_repository.py）
      → waterway / region / admin_region / node_type / transport_node / node_alias 表
```

---

### 6.4 货源管理模块（`/api/v1/cargo`）

#### 商品体系管理

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/commodity-category` | 获取货品大类列表 |
| POST | `/commodity-category` | 创建货品大类 |
| GET | `/commodity-category/{id}/types` | 获取商品类型列表 |
| POST | `/commodity-category/{id}/types` | 创建商品类型 |
| GET | `/commodity-type/{id}/standards` | 获取商品标准列表 |
| POST | `/commodity-type/{id}/standards` | 创建商品标准 |

#### AI 货源解析（核心流程）

| 方法 | 路径 | 功能 | 所需角色 |
|------|------|------|----------|
| POST | `/cargo/text` | **提交原始货运文本（触发 AI 后台解析）** | OPERATOR/COLLECTOR |
| GET | `/cargo/text` | 货运文本列表（分页 + 状态过滤） | 任意 |
| GET | `/cargo/text/{id}` | 获取单条货运文本详情 | 任意 |
| GET | `/cargo/parse-result/{msg_id}` | 获取 AI 解析结果（含置信度） | 任意 |
| POST | `/cargo/parse-result/{id}/confirm` | **确认 AI 解析结果（生成正式货源记录）** | OPERATOR/ADMIN |

#### 货源机会

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/cargo/opportunity` | 手动录入货源机会（直接创建，无需 AI 解析） |
| GET | `/cargo/opportunity` | 货源机会列表（状态/起止节点/商品/分页过滤） |

**AI 解析调用链路：**
```
cargo/router.py
  └─ POST /cargo/text
       ├── CargoService.submit_cargo_text()
       │     └── CargoRepository.save_raw_message()  # 保存原始文本，status=PENDING
       └── BackgroundTasks.add_task(trigger_cargo_parse, msg_id)
             └── ai_tasks.trigger_cargo_parse()
                   └── CargoParseWorkflow.run()
                         ├── CargoAgent → Claude API
                         │     ├── cargo_tools：提取货品/吨位/运价/时间字段
                         │     └── entity_match_tools：地名/货品别名模糊匹配
                         └── CargoRepository.save_parse_result()  # 存置信度+结构化结果

# 操作员确认：
POST /cargo/parse-result/{id}/confirm
  → CargoService.confirm_parse_result()
    → CargoRepository.create_opportunity()  # 生成 cargo_opportunity 正式记录
```

---

### 6.5 船舶管理模块（`/api/v1/vessel`）

#### 船舶类型管理

| 方法 | 路径 | 功能 | 所需角色 |
|------|------|------|----------|
| GET | `/vessel-type` | 船舶类型列表 | 任意 |
| POST | `/vessel-type` | 创建船舶类型（待审核） | ADMIN/OPERATOR |
| PUT | `/vessel-type/{id}` | 更新船舶类型 | ADMIN/OPERATOR |
| DELETE | `/vessel-type/{id}` | 删除船舶类型 | ADMIN |
| POST | `/vessel-type/{id}/approve` | 审批通过 | ADMIN/SUPER_ADMIN |
| POST | `/vessel-type/{id}/reject` | 驳回（必填意见） | ADMIN/SUPER_ADMIN |

#### 船舶档案管理

| 方法 | 路径 | 功能 | 所需角色 |
|------|------|------|----------|
| GET | `/vessel` | 船舶列表（分页 + 类型/状态/关键词过滤） | 任意 |
| POST | `/vessel` | 录入船舶（待审核） | ADMIN/OPERATOR/COLLECTOR |
| GET | `/vessel/{id}` | 船舶详情 | 任意 |
| PUT | `/vessel/{id}` | 更新船舶（**自动记录船名/AIS 变更历史**） | ADMIN/OPERATOR |
| DELETE | `/vessel/{id}` | 删除船舶 | ADMIN |
| POST | `/vessel/{id}/approve` | 审批通过（提交人不可自审） | ADMIN/SUPER_ADMIN |
| POST | `/vessel/{id}/reject` | 驳回（必填意见） | ADMIN/SUPER_ADMIN |
| GET | `/vessel/{id}/history` | 获取船名 + AIS 变更历史 | 任意 |
| PUT | `/vessel/{id}/dynamic` | 更新船舶动态（当前位置/状态） | ADMIN/OPERATOR/COLLECTOR |
| GET | `/vessel/{id}/dynamic` | 获取船舶最新动态 | 任意 |

**调用链路：**
```
vessel/router.py
  → VesselService（vessel_service.py）
    → VesselRepository（vessel_repository.py）
      → vessel / vessel_name_history / vessel_ais_history / vessel_dynamic 表
```

---

### 6.6 航线管理模块（`/api/v1/route`）

| 方法 | 路径 | 功能 | 所需角色 |
|------|------|------|----------|
| GET | `/route` | 航线列表（起止区域/状态/分页） | 任意 |
| POST | `/route` | 创建航线 | ADMIN/SUPER_ADMIN |
| GET | `/route/{id}` | 航线详情 | 任意 |
| PUT | `/route/{id}` | 更新航线 | ADMIN/SUPER_ADMIN |
| DELETE | `/route/{id}` | 删除航线 | ADMIN/SUPER_ADMIN |
| GET | `/route/{id}/path` | 获取航线路径节点（有序） | 任意 |
| POST | `/route/{id}/path` | 添加途经节点 | ADMIN/SUPER_ADMIN |
| DELETE | `/route/{id}/path/{path_id}` | 删除途经节点 | ADMIN/SUPER_ADMIN |

**调用链路：**
```
route/router.py → RouteService → RouteRepository → shipping_route / shipping_route_path 表
```

---

### 6.7 货源分析模块（`/api/v1/analysis/cargo`）

> **架构约束：** 所有分析接口**仅读统计表**，禁止直接查询业务表，响应目标 < 200ms

| 方法 | 路径 | 功能 | 核心参数 |
|------|------|------|----------|
| GET | `/cargo/heatmap` | 货源热力图（按节点聚合） | `stat_date`、`stat_type`（ORIGIN/DEST）、`region_id` |
| GET | `/cargo/trend` | 货源近 N 天趋势 | `days`（默认 30） |
| GET | `/cargo/commodity_rank` | 货品大类排名（含占比） | `stat_date` |
| GET | `/cargo/region_ratio` | 区域货源分布占比 | `stat_date`、`stat_type` |

**调用链路：**
```
cargo_analysis.py
  → AnalysisService.get_cargo_heatmap()
    → AnalysisRepository.get_cargo_heatmap()  # 只查 cargo_heatmap_daily 统计表
      → 关联 TransportNode（eager load）获取节点坐标/名称
```

---

### 6.8 船舶分析模块（`/api/v1/analysis/ship`）

| 方法 | 路径 | 功能 | 核心参数 |
|------|------|------|----------|
| GET | `/ship/heatmap` | 船舶分布热力图（按节点聚合） | `stat_date`、`region_id` |
| GET | `/ship/type_ratio` | 各船型数量占比（饼图数据） | `stat_date` |
| GET | `/ship/age_distribution` | 船龄分布直方图 | `stat_date` |
| GET | `/ship/capacity_region` | 区域运力分布（船数 + 总载重吨） | `stat_date` |

**调用链路：**
```
ship_analysis.py
  → AnalysisService.get_ship_type_ratio()
    → AnalysisRepository.get_ship_type_stat()  # 只查 ship_type_stat_daily 统计表
```

**兼容旧版接口（`/api/v1/analysis`）：**

| 路径 | 功能 |
|------|------|
| `/analysis/dashboard` | 仪表盘汇总数据（货源总量 / 活跃数 / 船舶数 / 7 天趋势） |
| `/analysis/cargo-heatmap` | 旧版货源热力图接口（向后兼容） |
| `/analysis/vessel-heatmap` | 旧版船舶热力图接口（向后兼容） |
| `/analysis/cargo-trends` | 旧版货源趋势接口（向后兼容） |
| `/analysis/top-nodes` | 旧版 Top 节点排名（向后兼容） |
| `/analysis/run-stats` | 手动触发每日统计聚合（管理员专用） |

---

### 6.9 审核中心模块（`/api/v1/audit`）

| 方法 | 路径 | 功能 | 所需角色 |
|------|------|------|----------|
| GET | `/audit/tasks` | 审核任务列表（全状态分页，支持类型/提交人筛选） | ADMIN/OPERATOR/SUPER_ADMIN |
| GET | `/audit/tasks/pending` | 待审核任务列表（分页） | ADMIN/SUPER_ADMIN |
| POST | `/audit/tasks/{id}/approve` | 审批通过任务 | ADMIN/SUPER_ADMIN |
| POST | `/audit/tasks/{id}/reject` | 驳回任务（必须填写意见） | ADMIN/SUPER_ADMIN |
| GET | `/audit/history` | 审核操作历史（分页） | ADMIN/OPERATOR/SUPER_ADMIN |
| GET | `/audit/stats` | 各类对象待审核数量统计 | ADMIN/OPERATOR/SUPER_ADMIN |

**调用链路：**
```
audit/router.py
  → AuditService（audit_service.py）
    → AuditRepository（audit_repository.py）
      → audit_task / audit_record 表
```

---

## 7. 核心业务模块说明

### 7.1 货源管理（AI 驱动全流程）

**模块功能：**
采集员将微信群中的货运文本粘贴提交，系统后台自动调用 Claude AI 解析出结构化字段，操作员对解析结果进行确认或修正后，生成正式货源记录。同时支持手动录入作为补充方式。

**主要代码位置：**

| 文件 | 职责 |
|------|------|
| `app/api/v1/cargo/router.py` | HTTP 接入，触发 BackgroundTask |
| `app/services/cargo_service.py` | 业务编排（解析触发 / 确认流程） |
| `app/repositories/cargo_repository.py` | 货源数据 CRUD |
| `app/agents/cargo_agent.py` | Claude 调用，字段提取 |
| `app/tools/cargo_tools.py` | 货源文本信息提取 Tool |
| `app/tools/entity_match_tools.py` | 地名/货品别名库模糊匹配 Tool |
| `app/workflows/cargo_parse_workflow.py` | 端到端解析工作流编排 |
| `app/tasks/ai_tasks.py` | BackgroundTask / Celery 异步触发器 |
| `app/models/cargo.py` | ORM 模型（7 张表） |

**核心流程：**
```
1. 采集员提交原始文本 → 保存到 cargo_raw_message（status=PENDING）
2. 后台 AI 任务触发 → CargoAgent 调用 Claude API
   ├── 提取：起止港口、货品名称、吨位、装货日期、联系方式、运价
   ├── 每字段附置信度分数（0-100）
   └── entity_match_tools：将文本地名模糊匹配到 transport_node
3. 解析结果存入 cargo_ai_parse_result，更新 raw_message.status=COMPLETED
4. 操作员查看解析结果 → 确认 → 生成 cargo_opportunity 正式货源记录
```

---

### 7.2 船舶管理（全生命周期追踪）

**模块功能：**
维护船舶完整档案，自动追踪船名变更历史和 AIS/MMSI 变更历史，实时更新船舶当前位置动态，新增/修改均需审核。

**主要代码位置：**

| 文件 | 职责 |
|------|------|
| `app/api/v1/vessel/router.py` | HTTP 接入 |
| `app/services/vessel_service.py` | 业务逻辑（历史追踪/审核集成） |
| `app/repositories/vessel_repository.py` | 船舶数据 CRUD（含历史写入） |
| `app/models/vessel.py` | ORM 模型（5 张表） |

**核心逻辑：**
- 修改船名时，旧船名自动写入 `vessel_name_history`
- 修改 MMSI 时，旧 MMSI 自动写入 `vessel_ais_history`
- `vessel_dynamic.current_node_id` 为船舶当前 AIS 位置节点，是船舶热力图统计来源

---

### 7.3 地址与节点管理（智能地理信息）

**模块功能：**
- 水系编码系统化（自动生成编码，支持父子层级）
- 商业区域智能化（边界多边形 → 自动计算质心坐标 → 自动圈定所属城市）
- 运输节点别名体系（每个港口可有多个俗称，为 AI 实体匹配提供基础数据）
- 全部业务对象均有审核工作流

**主要代码位置：**

| 文件 | 职责 |
|------|------|
| `app/api/v1/address/router.py` | HTTP 接入 |
| `app/services/address_service.py` | 业务逻辑（自动编码/质心计算/审核） |
| `app/repositories/address_repository.py` | 地址数据 CRUD |
| `app/utils/waterway_code_generator.py` | 水系编码自动生成算法 |
| `app/utils/region_helpers.py` | 区域质心计算/城市圈定辅助函数 |
| `app/models/address.py` | ORM 模型（7 张表） |

---

### 7.4 航运数据统计分析（ETL 双表分离）

**模块功能：**
每日凌晨 02:00 自动运行 8 个 ETL 函数，将业务表数据聚合到 8 张统计表。分析 API 仅读统计表，彻底隔离分析读取与业务写入，保证分析接口响应时间 < 200ms。

**ETL 任务详情（`app/tasks/stat_tasks.py`）：**

```python
# daily_stat_job() 每日 02:00 执行，8 个函数依次运行
_stat_cargo_daily()          # cargo_opportunity → cargo_stat_daily（日汇总）
_stat_cargo_heatmap()        # cargo_opportunity → cargo_heatmap_daily（节点热力）
_stat_cargo_region()         # cargo_opportunity → cargo_region_stat_daily（区域分布）
_stat_cargo_commodity()      # cargo_opportunity+JOIN → cargo_commodity_stat_daily（品类排名）
_stat_ship_type()            # vessel → ship_type_stat_daily（船型统计）
_stat_ship_capacity_region() # vessel+vessel_dynamic → ship_capacity_region_daily（区域运力）
_stat_ship_age()             # vessel.build_year → ship_age_stat_daily（船龄分布）
_stat_ship_heatmap()         # vessel_dynamic → ship_heatmap_daily（船舶热力）
```

**主要代码位置：**

| 文件 | 职责 |
|------|------|
| `app/tasks/stat_tasks.py` | **唯一**读取业务表进行统计聚合的代码 |
| `app/tasks/scheduler.py` | APScheduler 定时触发（开发模式） |
| `app/tasks/celery_app.py` | Celery 生产模式任务注册 |
| `app/repositories/analysis_repository.py` | 统计表读取 + upsert 写入 |
| `app/services/analysis_service.py` | 统计数据组装为 API 响应格式 |
| `app/api/v1/analysis/` | 分析接口路由 |

---

### 7.5 统一审核体系

**模块功能：**
系统中 10 类业务对象（运输节点、商业区域、船舶、船舶类型等）均通过统一的 `audit_task` 表管理审核状态，`audit_record` 表记录完整操作历史。内置防自审机制：提交人不可审核自己提交的内容（SUPER_ADMIN 除外）。

**审核工作流：**
```
业务数据提交 → audit_task 记录创建（status=pending）
                     │
             审核人查看待审列表
                     │
         ┌───────────┴───────────┐
    审批通过                   驳回
    audit_task.status=approved  audit_task.status=rejected
    audit_record 写入           audit_record 写入（含驳回意见）
    业务表 audit_status=1       业务表 audit_status=2
```

**主要代码位置：**

| 文件 | 职责 |
|------|------|
| `app/api/v1/audit/router.py` | 审核中心 HTTP 接口 |
| `app/services/audit_service.py` | 审核业务逻辑（通用审核流程） |
| `app/repositories/audit_repository.py` | 审核数据 CRUD |
| `app/models/audit.py` | AuditTask / AuditRecord ORM 模型 |

---

## 8. 本地开发环境部署

### 8.1 前置要求

- Python 3.11+
- Git

### 8.2 克隆项目

```bash
git clone <repository-url>
cd inland-shipping-platform
```

### 8.3 创建虚拟环境并安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

### 8.4 配置环境变量

创建 `.env` 文件（所有配置均有默认值，最低限度只需配置 AI Key）：

```dotenv
# AI 解析功能（货运文本解析需要，无 Key 时 AI 解析降级）
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxx

# 可选覆盖（以下均有默认值）
DEBUG=True
DATABASE_URL=sqlite+aiosqlite:///./inland_shipping.db
SECRET_KEY=inland-shipping-platform-secret-key-2026
```

> **说明：** 本地开发默认使用 **SQLite**（零配置）。`DEBUG=True` 时系统启动时自动执行：
> - `init_db()` 创建所有数据库表
> - `seed_all()` 导入种子数据（角色、初始用户、货品分类、示例水系节点）
> - 启动 APScheduler 定时任务（每日 02:00 统计 ETL）

### 8.5 执行数据库迁移（可选）

```bash
alembic upgrade head
```

> 开发环境可跳过此步骤（`init_db()` 在启动时通过 `create_all()` 自动建表）。
> Alembic 迁移主要用于生产环境的增量变更管理。

### 8.6 启动服务

```bash
uvicorn main:app --reload
```

### 8.7 访问地址

| 地址 | 说明 |
|------|------|
| `http://localhost:8000/docs` | **Swagger 交互文档（推荐）** |
| `http://localhost:8000/redoc` | ReDoc API 文档 |
| `http://localhost:8000` | 系统状态信息 |
| `http://localhost:8000/health` | 健康检查 |

### 8.8 默认账号

| 用户名 | 密码 | 角色 |
|--------|------|------|
| `admin` | `Admin@2026` | SUPER_ADMIN（超级管理员） |
| `collector1` | `Test@2026` | COLLECTOR（数据采集员） |

---

## 9. 生产环境部署

### 9.1 为什么生产环境不能使用 SQLite

SQLite 是单文件数据库，**不支持多进程并发写入**。生产环境通常使用多个 Uvicorn Worker 进程，并发写入会导致文件锁竞争甚至数据损坏。生产环境必须切换为支持网络访问和并发的数据库：

- **推荐：MySQL 8.0+**（与 `docs/init_mysql.sql` 配套，建表脚本完整）
- 备选：PostgreSQL 14+

### 9.2 服务器环境要求

| 组件 | 版本要求 | 说明 |
|------|----------|------|
| Python | 3.11+ | 运行 FastAPI 服务 |
| MySQL | 8.0+ | 主数据库（字符集 utf8mb4） |
| Redis | 7.0+ | Celery 任务队列 + 结果存储 |
| 内存 | ≥ 4 GB | API 服务 + Celery Worker |
| 磁盘 | ≥ 50 GB | 数据库存储 |

### 9.3 配置生产数据库连接

**安装 MySQL 异步驱动：**

```bash
pip install aiomysql
```

**生产环境 `.env` 配置：**

```dotenv
DEBUG=False

# 生产数据库（MySQL）
DATABASE_URL=mysql+aiomysql://inland:your-password@db-host:3306/inland_shipping

# 安全密钥（请使用随机生成的强密钥）
SECRET_KEY=your-64-char-random-secret-key-here

# AI 集成
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxx

# Celery（生产模式定时任务）
CELERY_BROKER_URL=redis://redis-host:6379/0
CELERY_RESULT_BACKEND=redis://redis-host:6379/1

# CORS（限制前端域名）
ALLOWED_ORIGINS=["https://your-frontend-domain.com"]
```

> **PostgreSQL 配置示例：**
> ```bash
> pip install asyncpg
> DATABASE_URL=postgresql+asyncpg://inland:password@db-host:5432/inland_shipping
> ```

---

## 10. 数据库初始化

### 10.1 创建 MySQL 数据库

```sql
-- 以 root 身份执行
CREATE DATABASE inland_shipping
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER 'inland'@'%' IDENTIFIED BY 'your-strong-password';
GRANT ALL PRIVILEGES ON inland_shipping.* TO 'inland'@'%';
FLUSH PRIVILEGES;
```

### 10.2 执行建表脚本

**方式一：使用 init_mysql.sql（首次部署推荐）**

```bash
mysql -h db-host -u inland -p inland_shipping < docs/init_mysql.sql
```

**方式二：使用 Alembic 迁移管理（后续增量变更推荐）**

```bash
# 确认 .env 中 DATABASE_URL 已指向 MySQL
alembic upgrade head
```

Alembic 迁移版本说明：

| 版本 | 文件名 | 变更内容 |
|------|--------|----------|
| `0001` | `0001_add_region_audit_fields.py` | 区域表新增审核相关字段 |
| `0002` | `0002_add_audit_task_and_unified_fields.py` | 新增 audit_task 表，10 类对象统一审核字段 |
| `0003` | `0003_add_analysis_stat_tables.py` | 新增 8 张统计分析日表 |

### 10.3 初始化种子数据

```bash
# 生产环境手动执行（DEBUG=False 时不自动执行）
python -m scripts.seed_data
```

种子数据内容：
- 系统角色（4 种：SUPER_ADMIN / ADMIN / OPERATOR / COLLECTOR）
- 初始管理员账号（用户名 `admin`，密码 `Admin@2026`）
- 基础商品大类（煤炭、矿石、粮食、建材、化工品等）
- 基础水系数据（长江、黄河、淮河、珠江等）
- 示例区域与运输节点

---

## 11. 服务启动流程

### 11.1 开发环境（单进程热重载）

```bash
source .venv/bin/activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 11.2 生产环境 — API 服务

```bash
# 方式一：多进程 Uvicorn（推荐，Worker 数 = CPU 核心数 × 2 + 1）
uvicorn main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 4

# 方式二：Gunicorn 管理 Uvicorn Worker（更稳定的进程管理）
gunicorn main:app \
  -w 4 \
  -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --access-logfile /var/log/inland/access.log \
  --error-logfile /var/log/inland/error.log \
  --daemon
```

### 11.3 生产环境 — Celery 异步任务（AI 解析 + 定时统计）

```bash
# Celery Worker（处理 AI 解析任务，可多实例）
celery -A app.tasks.celery_app worker \
  --loglevel=info \
  --concurrency=4 \
  --logfile=/var/log/inland/celery-worker.log \
  --detach

# Celery Beat（定时调度，每日 02:00 触发 ETL 统计）
celery -A app.tasks.celery_app beat \
  --loglevel=info \
  --logfile=/var/log/inland/celery-beat.log \
  --detach
```

### 11.4 一键启动脚本

```bash
chmod +x start.sh
./start.sh
```

### 11.5 Docker Compose 部署（推荐）

```yaml
# docker-compose.yml
version: "3.9"
services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DEBUG=False
      - DATABASE_URL=mysql+aiomysql://inland:password@db:3306/inland_shipping
      - CELERY_BROKER_URL=redis://redis:6379/0
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    depends_on:
      - db
      - redis
    command: uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4

  celery_worker:
    build: .
    environment:
      - DATABASE_URL=mysql+aiomysql://inland:password@db:3306/inland_shipping
      - CELERY_BROKER_URL=redis://redis:6379/0
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    depends_on:
      - redis
      - db
    command: celery -A app.tasks.celery_app worker --loglevel=info --concurrency=4

  celery_beat:
    build: .
    environment:
      - DATABASE_URL=mysql+aiomysql://inland:password@db:3306/inland_shipping
      - CELERY_BROKER_URL=redis://redis:6379/0
    depends_on:
      - redis
    command: celery -A app.tasks.celery_app beat --loglevel=info

  db:
    image: mysql:8.0
    environment:
      MYSQL_DATABASE: inland_shipping
      MYSQL_USER: inland
      MYSQL_PASSWORD: password
      MYSQL_ROOT_PASSWORD: rootpassword
    volumes:
      - ./docs/init_mysql.sql:/docker-entrypoint-initdb.d/init.sql
      - mysql_data:/var/lib/mysql

  redis:
    image: redis:7.0-alpine
    volumes:
      - redis_data:/data

volumes:
  mysql_data:
  redis_data:
```

---

## 12. 系统运行流程

### 12.1 标准请求处理流程

```
客户端发起请求（携带 JWT Token）
       │
       ▼
FastAPI Router
  ├── Pydantic 参数校验
  ├── JWT 验证（get_current_user）
  ├── 角色鉴权（require_roles）
  └── 调用 Service 方法
       │
       ▼
Service Layer（业务逻辑编排）
  ├── 校验业务规则
  ├── 调用 Repository（不写 SQL）
  └── 组装返回数据
       │
       ▼
Repository Layer（数据访问）
  ├── SQLAlchemy 异步查询
  ├── ORM 对象映射
  └── 返回 Domain Model
       │
       ▼
数据库（SQLite / MySQL / PostgreSQL）
       │
       ▼
Router 格式化统一响应 → 客户端
  {"code": 0, "message": "success", "data": {...}}
```

### 12.2 AI 货源解析异步流程

```
POST /cargo/text
  │
  ├── 【同步返回】保存原始文本，返回 {id, status: "PENDING"}
  │
  └── 【后台异步】BackgroundTask / Celery
        │
        ▼
    trigger_cargo_parse(msg_id)
        │
        ▼
    CargoParseWorkflow.run()
        ├── CargoAgent 调用 Claude API
        │     ├── cargo_tools：提取起止港/货品/吨位/运价/时间
        │     └── entity_match_tools：地名→transport_node 模糊匹配
        └── 保存解析结果（含置信度）到 cargo_ai_parse_result
            更新 cargo_raw_message.status = COMPLETED

# 操作员确认：
POST /cargo/parse-result/{id}/confirm
  → 生成正式 cargo_opportunity 记录
```

### 12.3 每日统计 ETL 流程

```
凌晨 02:00
  └── APScheduler（开发）/ Celery Beat（生产）触发 daily_stat_job()
           │
           ▼
    为当日日期依次执行 8 个 ETL 函数
    （每个函数：读业务表 → 聚合计算 → upsert 写统计表，幂等可重跑）
           │
           ▼
    统计表数据更新完毕

# 分析 API 始终只读统计表，响应 < 200ms
GET /analysis/cargo/heatmap → cargo_heatmap_daily（不触碰 cargo_opportunity）
```

---

## 13. 后续扩展方向

| 方向 | 说明 | 预留代码位置 |
|------|------|-------------|
| **AIS 实时数据接入** | 接入 AIS 数据流，实时更新 `vessel_dynamic`，分析船舶轨迹 | `vessel_dynamic` 表已预留 AIS 字段 |
| **货船智能匹配调度** | 基于货源需求与可用运力进行智能调度撮合 | `app/tasks/dispatch_tasks.py` 框架已预留 |
| **AI 分析增强** | AI 自动生成航运趋势分析报告 | `app/agents/analysis_agent.py` 已有框架 |
| **运价指数预测** | 基于历史运价训练模型，提供运价参考预测 | 统计表可扩展运价维度 |
| **微信小程序集成** | 对接微信生态采集端（货代/船东） | `sys_user.wechat_openid` 字段已预留 |
| **月度/年度统计** | 扩展 ETL 任务，新增月度/季度/年度统计聚合表 | 仿照 `stat_tasks.py` 扩展 |
| **地图可视化** | 基于节点经纬度实现热力地图、航线轨迹渲染 | `transport_node.longitude/latitude` 已有坐标数据 |
| **多租户 SaaS** | 为多个航运企业提供独立数据隔离的 SaaS 服务 | 各表预留 `tenant_id` 扩展点 |

---

## 附录

### 统一响应格式

```json
// 成功响应
{"code": 0, "message": "success", "data": { ... }}

// 业务异常
{"code": 40001, "message": "货源记录不存在", "data": null}

// 未授权
{"code": 401, "message": "请先登录", "data": null}

// 权限不足
{"code": 403, "message": "权限不足", "data": null}
```

### 审核状态说明

| 值 | 常量 | 含义 |
|----|------|------|
| `0` | PENDING | 待审核 |
| `1` | APPROVED | 审核通过 |
| `2` | REJECTED | 审核驳回 |

### 开发文档索引

| 文档 | 路径 | 内容 |
|------|------|------|
| 架构说明 | `docs/ARCHITECTURE.md` | AI Native 架构详细设计与模块职责 |
| 数据库设计 | `docs/DB_DESIGN.md` | 全部 32 张表的字段说明与关系图 |
| 生产部署 | `docs/DEPLOYMENT.md` | 生产环境完整部署与运维指南 |
| 本地开发 | `docs/LOCAL_DEVELOPMENT.md` | 开发环境搭建与常见问题 |
| MySQL 建表 | `docs/init_mysql.sql` | 完整 MySQL DDL（含索引/外键/注释） |

---

*本文档基于源代码自动分析生成 · V2.0 · 2026-03-16*
