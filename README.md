# 中国内河航运数据采集与分析平台

> **AI融合架构** · China Inland Waterway Shipping Data Collection & Analysis Platform

[![FastAPI](https://img.shields.io/badge/FastAPI-0.128-009688)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.9+-3776AB)](https://www.python.org)
[![Claude AI](https://img.shields.io/badge/Claude-AI%20Engine-6B46C1)](https://anthropic.com)
[![SQLite](https://img.shields.io/badge/SQLite-Local%20Dev-003B57)](https://sqlite.org)

---

## 核心特性

本平台以 **AI 为核心驱动力**，不是单纯的AI助手，而是将AI深度融合到数据采集、解析、分析全链路中：

| AI能力 | 说明 |
|--------|------|
| 🤖 **智能货源解析** | 粘贴微信群原始文本，Claude自动提取起点、终点、货品、吨位、时间等字段 |
| 🔍 **模糊地址匹配** | AI提取文本 + 别名库模糊匹配，支持"龙潭码头"→"龙潭港"等多种写法识别 |
| 📊 **置信度评分** | 每个解析字段附带置信度分数(0-100)和候选列表，辅助人工确认 |
| ⏰ **自动统计聚合** | APScheduler定时任务，每日凌晨自动生成热力统计数据 |
| 🔄 **AI版本演进设计** | 架构预留AI调度、预测分析、智能运价等未来扩展接口 |

---

## 项目结构

```
inland-data/
├── main.py                      # FastAPI 主入口 + 应用生命周期 + 数据初始化
├── requirements.txt             # 依赖清单
├── start.sh                     # 一键启动脚本
├── .env                         # 环境配置（AI API Key等）
├── app/
│   ├── core/
│   │   ├── config.py            # 配置管理（pydantic-settings）
│   │   ├── database.py          # 异步数据库引擎（SQLAlchemy Async）
│   │   └── security.py          # JWT认证 + bcrypt密码 + RBAC权限
│   ├── models/                  # SQLAlchemy 数据模型（32张表）
│   │   ├── address.py           # 地址体系：水系/区域/行政区/节点/别名
│   │   ├── cargo.py             # 货品+货源：分类/标准/别名/原始/解析/货源
│   │   ├── vessel.py            # 船舶体系：档案/历史船名/AIS/动态
│   │   ├── route.py             # 航线体系：商业航线/路径节点
│   │   ├── analysis.py          # 热力统计日表
│   │   ├── audit.py             # 审核记录表（全链路审核历史）
│   │   └── system.py            # 系统：用户/角色/关联
│   ├── schemas/                 # Pydantic 请求/响应模型
│   ├── services/                # 业务逻辑服务层
│   │   ├── audit_service.py     # 统一审核服务（含自动建别名）
│   │   ├── address_service.py   # 地址CRUD + 审核集成
│   │   ├── cargo_service.py     # 货品/货源CRUD + AI解析集成
│   │   ├── vessel_service.py    # 船舶CRUD + 历史记录自动追踪
│   │   ├── route_service.py     # 航线管理
│   │   └── analysis_service.py  # 热力统计 + 仪表盘数据
│   ├── ai_engine/
│   │   └── parser.py            # 🤖 Claude AI 货源解析引擎（核心AI模块）
│   ├── tasks/
│   │   └── scheduler.py         # APScheduler 定时任务（每日聚合+超时清理）
│   └── api/v1/                  # RESTful API 路由（106个端点）
│       ├── auth/                # 认证（登录/登出/当前用户）
│       ├── address/             # 地址管理（水系/区域/节点/别名）
│       ├── cargo/               # 货品+货源（手动录入/AI解析/确认）
│       ├── vessel/              # 船舶管理（档案/动态/历史）
│       ├── route/               # 航线管理（路线/路径节点）
│       ├── audit/               # 审核中心（待审/历史/通过/驳回）
│       ├── analysis/            # 数据分析（热力图/趋势/看板）
│       ├── ai/                  # AI管理（解析状态/重新解析）
│       └── system/              # 系统管理（用户/角色）
```

---

## 快速启动

### 环境要求
- Python 3.9+
- 网络连接（安装依赖）
- Anthropic API Key（可选，无Key时AI解析降级为规则匹配）

### 一键启动

```bash
# 1. 克隆项目
git clone https://github.com/YOUR_USERNAME/inland-shipping-platform.git
cd inland-shipping-platform

# 2. 配置 AI Key（可选但推荐）
echo "ANTHROPIC_API_KEY=your-key-here" >> .env

# 3. 启动
./start.sh
```

或者手动启动：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 访问

| 地址 | 说明 |
|------|------|
| `http://localhost:8000/docs` | Swagger API文档（推荐） |
| `http://localhost:8000/redoc` | ReDoc API文档 |
| `http://localhost:8000/health` | 健康检查 |

### 默认账号

| 用户名 | 密码 | 角色 |
|--------|------|------|
| `admin` | `Admin@2026` | 超级管理员 |
| `collector1` | `Test@2026` | 数据采集员 |

---

## 用户角色与权限

| 角色 | 代码 | 权限范围 |
|------|------|---------|
| 超级管理员 | `SUPER_ADMIN` | 全部权限，可自审核 |
| 管理员 | `ADMIN` | 数据审核、系统管理、全部数据操作 |
| 运营人员 | `OPERATOR` | 数据录入、货源管理、审核申请 |
| 数据采集员 | `COLLECTOR` | 货源采集、数据查看 |

---

## AI 货源解析流程

```
员工复制微信群文本
        │
        ▼
POST /api/v1/cargo/cargo/text
        │
        ├── 保存到 cargo_raw_message（原始文本）
        │
        ├── 后台触发 Claude AI 解析（BackgroundTask）
        │       │
        │       ├── 提取：起点/终点/货品/吨位/时间/运价/联系方式
        │       ├── 置信度评分（每字段0-100分）
        │       ├── 地址别名库模糊匹配（fuzzy score）
        │       └── 保存到 cargo_ai_parse_result
        │
GET /api/v1/ai/parse-status/{id}   ← 查看解析状态
        │
        ▼
POST /api/v1/cargo/cargo/ai-results/{id}/confirm
        │
        ├── 人工确认（可修正AI识别错误的字段）
        └── 写入 cargo_opportunity（正式货源数据）
```

---

## 主要API接口

### 认证
```
POST /api/v1/auth/login       用户登录，返回JWT Token
GET  /api/v1/auth/me          获取当前用户信息
```

### 地址管理
```
GET  /api/v1/address/transport-node         节点列表（支持多维度筛选）
POST /api/v1/address/transport-node         创建节点（自动进入审核流程）
GET  /api/v1/address/transport-node/search  模糊搜索（基于别名库）
```

### 货源采集（核心）
```
POST /api/v1/cargo/cargo/manual             手动录入货源（直接入库）
POST /api/v1/cargo/cargo/text               粘贴文本→AI解析（异步）
GET  /api/v1/cargo/cargo/ai-results         查看待确认的AI解析结果
POST /api/v1/cargo/cargo/ai-results/{id}/confirm   确认AI结果
POST /api/v1/cargo/cargo/ai-results/{id}/discard   废弃AI结果
```

### 数据分析
```
GET /api/v1/analysis/dashboard        仪表盘（核心指标统计）
GET /api/v1/analysis/cargo-heatmap    货源热力数据
GET /api/v1/analysis/vessel-heatmap   运力热力数据
GET /api/v1/analysis/cargo-trends     货源趋势（近N天）
POST /api/v1/analysis/run-stats       手动触发每日统计聚合
```

### 审核中心
```
GET  /api/v1/audit/pending          待审核列表（支持按类型筛选）
GET  /api/v1/audit/stats            各类型待审核数量统计
POST /api/v1/audit/{id}/approve     审批通过（自动更新实体状态+创建别名）
POST /api/v1/audit/{id}/reject      驳回（必须填写原因）
```

---

## 数据体系（32张表）

| 分层 | 表名 | 说明 |
|------|------|------|
| 地址体系 | waterway, region, admin_region, node_type, transport_node, node_alias, region_address_relation | 7张 |
| 货品体系 | commodity_category, commodity_type, commodity_standard, commodity_alias | 4张 |
| 船舶体系 | vessel_type_dict, vessel, vessel_name_history, vessel_ais_history, vessel_dynamic | 5张 |
| 航线体系 | shipping_route, shipping_route_path | 2张 |
| 货源体系 | cargo_raw_message, cargo_ai_parse_result, cargo_opportunity | 3张 |
| 统计分析 | heatmap_stat_daily | 1张 |
| 系统基础 | sys_user, sys_role, sys_user_role | 3张 |
| 审核记录 | audit_record | 1张 |

---

## 版本演进规划

| 版本 | 阶段目标 | 核心AI能力 |
|------|---------|-----------|
| **V1（当前）** | 数据采集与分析 | AI文本解析、模糊匹配、热力分析 |
| V2 | 数据资产深化 | AI数据清洗、运价预测雏形 |
| V3 | 智能分析 | 航运指数AI计算、异常检测、AI调度建议 |
| V4 | 交易平台 | AI货源撮合、智能询价、风险评估 |
| V5 | 生态平台 | 多式联运AI规划、开放API、数据服务 |

---

## 技术栈

- **Web框架**: FastAPI 0.128
- **ORM**: SQLAlchemy 2.0 Async
- **数据库**: SQLite（开发）/ PostgreSQL（生产）
- **AI引擎**: Anthropic Claude API
- **认证**: JWT (python-jose) + bcrypt
- **权限**: RBAC（4种角色）
- **定时任务**: APScheduler
- **文档**: Swagger UI / ReDoc
