# 系统架构设计说明

**项目：中国内河航运数据采集与分析平台 V2.0**
**架构模式：AI Native Clean Architecture + DDD-lite**

---

## 目录

1. [架构总览](#1-架构总览)
2. [分层架构详解](#2-分层架构详解)
3. [AI Native Architecture](#3-ai-native-architecture)
4. [目录结构说明](#4-目录结构说明)
5. [模块职责与边界](#5-模块职责与边界)
6. [数据流转说明](#6-数据流转说明)
7. [核心设计决策](#7-核心设计决策)
8. [依赖关系图](#8-依赖关系图)
9. [扩展指南](#9-扩展指南)

---

## 1. 架构总览

### 1.1 架构演进

| 版本 | 架构模式 | 主要问题 |
|------|---------|---------|
| V1.0 | 简单MVC | Service直接操作DB、AI单体文件、无Repository层 |
| V2.0 | AI Native Clean Architecture | 严格分层、AI模块独立、工程化完整 |

### 1.2 架构原则

本系统严格遵守以下原则：

- **单一职责（SRP）**：每个模块只负责一件事
- **依赖反转（DIP）**：高层模块通过接口依赖低层，不直接依赖实现
- **高内聚低耦合**：模块内部紧密，模块间通过清晰接口通信
- **可测试性**：每一层均可独立单元测试
- **AI First**：AI能力作为一等公民，拥有独立的架构层

### 1.3 系统架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CLIENT / FRONTEND                           │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ HTTP/REST
┌───────────────────────────────▼─────────────────────────────────────┐
│                         API LAYER (app/api/)                        │
│  职责：HTTP接入，参数验证，响应格式化                                │
│  禁止：业务逻辑，数据库访问，直接AI调用                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │   auth   │ │  cargo   │ │  vessel  │ │ address  │ │ analysis │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ calls Service
┌───────────────────────────────▼─────────────────────────────────────┐
│                      SERVICE LAYER (app/services/)                  │
│  职责：业务逻辑编排，业务规则校验                                    │
│  禁止：SQLAlchemy Session访问，HTTP处理，直接LLM调用                 │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐                │
│  │ CargoService │ │AddressService│ │VesselService │ ...            │
│  └──────────────┘ └──────────────┘ └──────────────┘                │
└──────────────┬────────────────────────────┬─────────────────────────┘
               │ calls Repository           │ triggers Workflow
┌──────────────▼────────────┐  ┌────────────▼──────────────────────────┐
│  REPOSITORY LAYER         │  │         AI LAYER                      │
│  (app/repositories/)      │  │                                       │
│  职责：数据访问，SQL封装   │  │  ┌──────────────────────────────────┐ │
│  禁止：业务逻辑            │  │  │        WORKFLOWS                  │ │
│  ┌────────────────────┐   │  │  │  cargo_parse_workflow             │ │
│  │  CargoRepository   │   │  │  │  cargo_match_workflow             │ │
│  │  AddressRepository │   │  │  └─────────────┬────────────────────┘ │
│  │  VesselRepository  │   │  │                │ orchestrates          │
│  │  AuditRepository   │   │  │  ┌─────────────▼────────────────────┐ │
│  └────────────────────┘   │  │  │         AGENTS                   │ │
└──────────────┬────────────┘  │  │  CargoAgent / AnalysisAgent      │ │
               │               │  └─────────────┬────────────────────┘ │
┌──────────────▼────────────┐  │                │ uses                  │
│  DOMAIN MODEL LAYER       │  │  ┌─────────────▼────────────────────┐ │
│  (app/models/)            │  │  │          TOOLS                   │ │
│  SQLAlchemy ORM实体        │  │  │  CargoParseTextTool              │ │
│  32张业务数据表            │  │  │  EntityMatchTool                 │ │
└───────────────────────────┘  │  │  NodeQueryTool (只读DB访问)       │ │
                               │  │  GeoDistanceTool                 │ │
┌──────────────────────────┐   │  └──────────────────────────────────┘ │
│  TASK LAYER (app/tasks/) │   │                                       │
│  Celery异步任务           │◄──┘  ┌──────────────────────────────────┐ │
│  ai_tasks                │      │       AI CORE (app/ai/)           │ │
│  analysis_tasks           │      │  LLMClient (Anthropic SDK封装)    │ │
│  dispatch_tasks           │      │  PromptTemplates                 │ │
└──────────────────────────┘      └──────────────────────────────────┘ │
                               └───────────────────────────────────────┘
```

---

## 2. 分层架构详解

### 2.1 API Layer（接入层）

**位置：** `app/api/v1/`

**职责（只能做这些）：**
- 接收HTTP请求，验证请求参数（Pydantic Schema）
- 调用对应Service方法
- 将Service返回值格式化为HTTP响应
- 鉴权检查（通过FastAPI依赖注入）

**禁止事项：**
- 编写任何业务逻辑
- 直接访问数据库（不能注入 `db: AsyncSession`）
- 直接调用AI/LLM
- 直接调用Repository

```python
# ✅ 正确的API层写法
@router.post("/cargo/text")
async def submit_cargo_text(
    data: CargoRawMessageCreate,
    background_tasks: BackgroundTasks,
    service: CargoService = Depends(get_cargo_service),  # 注入Service
    user_roles=Depends(require_roles("OPERATOR")),
):
    user, _ = user_roles
    saved = await service.submit_cargo_text(          # 调用Service
        raw_text=data.raw_text,
        source=data.source,
        operator_id=user.id,
    )
    background_tasks.add_task(trigger_cargo_parse, saved.id)
    return success(data={"id": saved.id})             # 格式化响应

# ❌ 错误写法（API层直接操作DB）
@router.post("/cargo/text")
async def submit_cargo_text(db: AsyncSession = Depends(get_db)):
    raw_msg = CargoRawMessage(...)
    db.add(raw_msg)          # 违规：API层不能访问DB
    await db.commit()
```

### 2.2 Service Layer（业务层）

**位置：** `app/services/`

**职责：**
- 编排Repository调用获取/存储数据
- 实施业务规则（如：同一MMSI不能重复注册）
- 触发Workflow（AI流程）
- 编排跨Repository的事务操作

**禁止事项：**
- 直接使用 `AsyncSession` 执行SQL
- 处理HTTP请求/响应
- 直接调用LLM API

```python
# ✅ 正确的Service层写法
class CargoService:
    def __init__(
        self,
        cargo_repo: CargoRepository,    # 注入Repository
        address_repo: AddressRepository,
        audit_repo: AuditRepository,
    ):
        self._cargo = cargo_repo
        ...

    async def submit_cargo_text(self, raw_text: str, ...) -> CargoRawMessage:
        raw_msg = CargoRawMessage(raw_text=raw_text, ...)
        saved = await self._cargo.create(raw_msg)    # 通过Repository访问DB
        await self._cargo.save()
        return saved

# ❌ 错误写法（Service直接使用Session）
async def submit_cargo_text(db: AsyncSession, raw_text: str):
    raw_msg = CargoRawMessage(...)
    db.add(raw_msg)        # 违规：Service不能直接访问DB
    await db.commit()
```

### 2.3 Repository Layer（数据访问层）

**位置：** `app/repositories/`

**职责：**
- 封装所有数据库操作（CRUD + 复杂查询）
- 提供业务语义化的查询方法（如 `list_nodes_with_aliases()`）
- 管理事务提交（通过 `save()` 方法）

**禁止事项：**
- 编写业务逻辑
- 调用其他Service
- 处理HTTP

```python
# ✅ 正确的Repository写法
class AddressRepository(BaseRepository):
    async def get_all_nodes_with_aliases(self) -> Sequence[TransportNode]:
        """业务语义化查询，封装JOIN逻辑"""
        result = await self._db.execute(
            select(TransportNode).options(selectinload(TransportNode.aliases))
        )
        return result.scalars().unique().all()
```

### 2.4 Domain Model Layer（领域模型层）

**位置：** `app/models/`

**职责：**
- 定义业务实体（SQLAlchemy ORM映射）
- 声明实体间关系（一对多、多对多）
- 定义数据库约束（唯一索引、外键）

**规则：** 模型类只包含字段定义和关系声明，不包含业务逻辑。

### 2.5 Schema Layer（DTO层）

**位置：** `app/schemas/`

**职责：**
- 定义API请求/响应的数据结构（Pydantic模型）
- 提供输入验证规则
- 屏蔽内部领域模型，防止API直接暴露数据库结构

---

## 3. AI Native Architecture

### 3.1 AI模块三层结构

```
WORKFLOWS（编排层）
    ↓ 编排
AGENTS（执行层）
    ↓ 使用
TOOLS（原子能力层）
    ↓ 调用
LLM Client / Database（底层资源）
```

### 3.2 Tool 规范

**位置：** `app/tools/`

Tool是AI系统中最小的原子能力单元，必须满足：

| 规范 | 说明 |
|------|------|
| 单一职责 | 一个Tool只做一件事 |
| 标准接口 | 继承`BaseTool`，实现`execute()`方法 |
| 返回`ToolResult` | 统一的结果结构（success, data, error） |
| 无状态 | Tool不维护内部状态 |
| 可独立测试 | 不依赖其他Tool或Agent |

**现有Tool清单：**

| Tool | 文件 | 职责 |
|------|------|------|
| `CargoParseTextTool` | `cargo_tools.py` | 调用LLM从原始文本提取结构化字段 |
| `EntityMatchTool` | `entity_match_tools.py` | 将文本模糊匹配到数据库实体 |
| `NodeQueryTool` | `database_tools.py` | 只读查询运输节点数据 |
| `CommodityQueryTool` | `database_tools.py` | 只读查询商品数据 |
| `GeoDistanceTool` | `geo_tools.py` | 计算两点间地理距离 |

### 3.3 Agent 规范

**位置：** `app/agents/`

Agent通过组合多个Tool完成复杂任务：

| 规范 | 说明 |
|------|------|
| 继承`BaseAgent` | 实现`run(input_data)`方法 |
| 只通过Tool交互 | 不直接访问数据库，不直接调用LLM |
| 返回`AgentResult` | 包含output、error、steps（执行轨迹） |
| 声明tools列表 | 明确Agent可使用的Tool集合 |

**现有Agent清单：**

| Agent | 职责 |
|-------|------|
| `CargoAgent` | 货运文本解析：文本提取→实体匹配→置信度计算 |
| `AnalysisAgent` | 市场分析：接收数据摘要→生成AI分析报告 |

### 3.4 Workflow 规范

**位置：** `app/workflows/`

Workflow编排Agent和Tool的执行流程，是AI与持久化层的唯一交汇点：

| 规范 | 说明 |
|------|------|
| 继承`BaseWorkflow` | 实现`execute(context)`方法 |
| 管理阶段状态 | 通过stage_results记录每阶段执行状态 |
| 负责持久化 | Workflow是唯一可以写入数据库的AI组件 |
| 返回`WorkflowResult` | 包含result、error、stage_results |

**货源解析工作流（CargoParseWorkflow）：**

```
Stage 1: 更新消息状态 → PARSING
Stage 2: CargoAgent执行（文本解析 + 实体匹配）
Stage 3: 持久化AI解析结果到 cargo_ai_parse_result
Stage 4: 更新消息状态 → PARSED
```

### 3.5 AI禁止事项

```
❌ Tool直接写数据库
❌ Agent调用Service
❌ Workflow包含HTTP处理逻辑
❌ Service直接调用LLM（应通过Workflow）
❌ AI模块与业务Service相互依赖
```

---

## 4. 目录结构说明

```
inland-data/
├── main.py                      # 应用入口（~70行，纯配置）
├── requirements.txt             # 依赖清单
├── alembic.ini                  # 数据库迁移配置
├── Makefile                     # 开发命令
├── .env                         # 环境变量（不提交）
├── .env.example                 # 环境变量模板
│
├── alembic/                     # 数据库迁移
│   ├── env.py                   # 迁移环境（异步SQLAlchemy支持）
│   ├── script.py.mako           # 迁移脚本模板
│   └── versions/                # 迁移历史文件
│
├── app/
│   ├── core/                    # 核心基础设施
│   │   ├── config.py            # 统一配置（Pydantic Settings）
│   │   ├── database.py          # DB引擎与Session工厂
│   │   ├── security.py          # JWT认证与RBAC
│   │   ├── logging.py           # 结构化日志配置
│   │   ├── exceptions.py        # 统一异常体系
│   │   └── dependencies.py      # FastAPI依赖注入中心
│   │
│   ├── models/                  # 领域模型（SQLAlchemy ORM）
│   │   ├── base.py              # DeclarativeBase + TimestampMixin
│   │   ├── system.py            # 用户、角色（3张表）
│   │   ├── address.py           # 水系、节点、别名（7张表）
│   │   ├── cargo.py             # 商品、货源（7张表）
│   │   ├── vessel.py            # 船舶、动态（5张表）
│   │   ├── route.py             # 航线（2张表）
│   │   ├── analysis.py          # 统计（1张表）
│   │   └── audit.py             # 审计（1张表）
│   │
│   ├── schemas/                 # DTO层（Pydantic）
│   │   └── ...                  # 各业务域Schema定义
│   │
│   ├── repositories/            # 数据访问层
│   │   ├── base.py              # GenericRepository（CRUD基类）
│   │   ├── cargo_repository.py  # 货物数据访问
│   │   ├── address_repository.py
│   │   ├── vessel_repository.py
│   │   ├── route_repository.py
│   │   ├── analysis_repository.py
│   │   ├── audit_repository.py
│   │   └── system_repository.py
│   │
│   ├── services/                # 业务逻辑层
│   │   ├── cargo_service.py     # 货物业务（无DB访问）
│   │   ├── address_service.py
│   │   ├── vessel_service.py
│   │   ├── route_service.py
│   │   ├── analysis_service.py
│   │   └── audit_service.py
│   │
│   ├── ai/                      # AI核心基础
│   │   ├── base.py              # BaseTool/BaseAgent/BaseWorkflow抽象类
│   │   ├── llm_client.py        # Anthropic Claude SDK封装
│   │   └── prompt_templates.py  # 提示词模板管理
│   │
│   ├── tools/                   # AI工具层（原子能力）
│   │   ├── cargo_tools.py       # 货运文本解析Tool
│   │   ├── entity_match_tools.py # 实体模糊匹配Tool
│   │   ├── database_tools.py    # 只读DB查询Tool
│   │   └── geo_tools.py         # 地理计算Tool
│   │
│   ├── agents/                  # AI Agent层
│   │   ├── cargo_agent.py       # 货源解析Agent
│   │   └── analysis_agent.py    # 数据分析Agent
│   │
│   ├── workflows/               # AI工作流编排
│   │   └── cargo_parse_workflow.py  # 货源解析端到端流程
│   │
│   ├── tasks/                   # 异步任务层
│   │   ├── celery_app.py        # Celery配置与Beat调度
│   │   ├── ai_tasks.py          # AI处理任务
│   │   ├── analysis_tasks.py    # 统计分析任务
│   │   ├── dispatch_tasks.py    # 调度匹配任务（V2预留）
│   │   └── scheduler.py         # APScheduler（开发环境兼容）
│   │
│   ├── api/v1/                  # REST API接入层
│   │   ├── auth/router.py       # 认证接口
│   │   ├── cargo/router.py      # 货物接口
│   │   ├── address/router.py    # 地址/节点接口
│   │   ├── vessel/router.py     # 船舶接口
│   │   ├── route/router.py      # 航线接口
│   │   ├── analysis/router.py   # 分析接口
│   │   ├── ai/router.py         # AI状态接口
│   │   ├── audit/router.py      # 审核接口
│   │   └── system/router.py     # 系统管理接口
│   │
│   └── utils/                   # 通用工具
│       └── text_utils.py        # 文本处理工具
│
├── scripts/
│   └── seed_data.py             # 数据库种子数据初始化
│
├── tests/
│   ├── conftest.py              # 测试公共Fixture
│   ├── unit/                    # 单元测试
│   │   ├── test_tools/          # Tool单元测试
│   │   ├── test_services/       # Service单元测试
│   │   └── test_repositories/   # Repository单元测试
│   └── integration/             # 集成测试
│       └── test_api/            # API端到端测试
│
└── docs/                        # 项目文档
    ├── ARCHITECTURE.md          # 本文档
    ├── LOCAL_DEVELOPMENT.md     # 本地开发指南
    └── DEPLOYMENT.md            # 生产部署指南
```

---

## 5. 模块职责与边界

### 5.1 依赖注入规则

所有依赖关系通过 `app/core/dependencies.py` 统一管理：

```
FastAPI Depends →  get_cargo_service()
                     ├── get_cargo_repo()  → CargoRepository(db)
                     ├── get_address_repo() → AddressRepository(db)
                     └── get_audit_repo()   → AuditRepository(db)
```

**规则：**
- Service通过构造函数接收Repository（依赖注入）
- Repository通过构造函数接收 `AsyncSession`
- 不允许Service之间直接相互调用（通过事件或Workflow解耦）

### 5.2 异常处理规则

```
app/core/exceptions.py 定义异常层次：

AppException (基类)
├── NotFoundError (404) — 资源不存在
├── ValidationError (422) — 业务校验失败
├── ConflictError (409) — 资源冲突
├── AuthenticationError (401) — 认证失败
├── PermissionError (403) — 权限不足
├── BadRequestError (400) — 请求参数错误
├── AIServiceError (503) — AI服务异常
├── DatabaseError (500) — 数据库异常
└── TaskError (500) — 异步任务异常
```

**规则：**
- Service层抛出 `AppException` 子类（业务异常）
- `main.py` 中的全局异常处理器统一转换为标准HTTP响应
- 不在API层捕获和转换异常

### 5.3 事务管理规则

```python
# Repository提供save()方法管理事务
# Service在业务操作完成后调用save()

async def create_node(self, ...) -> TransportNode:
    node = TransportNode(...)
    saved = await self._address.create_node(node)    # flush
    await self._record_audit(...)                     # flush
    await self._address.save()                        # commit
    return saved
```

---

## 6. 数据流转说明

### 6.1 货源AI解析完整流程

```
用户粘贴微信群文本
        ↓
POST /api/v1/cargo/cargo/text
        ↓ (API Layer)
CargoService.submit_cargo_text()
        ↓ (Service Layer)
CargoRepository.create(CargoRawMessage)  ←── 状态: PENDING
        ↓
BackgroundTask: trigger_cargo_parse(msg_id)
        ↓ (Task Layer)
CargoParseWorkflow.execute()
        ↓  Stage 1: 更新状态 → PARSING
        ↓  Stage 2: CargoAgent.run()
        │     ├── CargoParseTextTool → 调用Claude API提取字段
        │     ├── NodeQueryTool → 获取节点数据（只读）
        │     ├── EntityMatchTool → 匹配起点节点
        │     ├── EntityMatchTool → 匹配终点节点
        │     └── EntityMatchTool → 匹配商品实体
        ↓  Stage 3: 持久化 CargoAiParseResult  ←── 状态: PENDING_CONFIRM
        ↓  Stage 4: 更新消息状态 → PARSED
        ↓
GET /api/v1/cargo/cargo/parse-result/{msg_id}
        ↓ (用户查看解析结果 + 候选列表)
POST /api/v1/cargo/cargo/parse-result/{id}/confirm
        ↓
CargoService.confirm_parse_result()
        ↓
创建 CargoOpportunity  ←── 最终业务数据
```

### 6.2 响应统一格式

所有API响应使用统一格式：

```json
{
    "code": "000000",
    "message": "Success",
    "data": { ... }
}
```

业务异常响应：

```json
{
    "code": "404000",
    "message": "TransportNode '999' not found",
    "data": null
}
```

---

## 7. 核心设计决策

### 7.1 为什么Repository不能被API层直接调用？

API层直接调用Repository会导致：
- 业务规则分散在API层，无法复用
- 事务管理混乱（多个Repository操作不原子）
- 测试困难（无法mock业务逻辑层）

正确流向：`API → Service → Repository`

### 7.2 为什么AI模块不能直接写数据库？

AI模块直接写数据库会导致：
- 数据一致性问题（AI写了一半失败时回滚困难）
- 违反单一职责（AI不应关心数据怎么存储）
- 测试困难（AI测试需要依赖数据库）

正确设计：AI结果 → Workflow → Repository → 数据库

### 7.3 为什么选择Celery而不是仅用APScheduler？

| 维度 | APScheduler | Celery |
|------|-------------|--------|
| 分布式 | 单机 | 多Worker水平扩展 |
| 任务重试 | 手动实现 | 内置重试机制 |
| 监控 | 无 | Flower监控面板 |
| 任务优先级 | 不支持 | 支持队列优先级 |
| 生产适用性 | 不适合 | 生产级标准方案 |

开发模式保留APScheduler（无需Redis），生产环境切换Celery。

### 7.4 为什么使用Alembic而不是create_all？

`create_all()` 的问题：
- 无法处理字段变更（ALTER TABLE）
- 无法回滚数据库结构
- 无迁移历史记录

Alembic优势：
- 版本化迁移历史
- 支持升级（upgrade）和降级（downgrade）
- 团队协作安全

---

## 8. 依赖关系图

```
main.py
  ├── app.core.config
  ├── app.core.logging
  ├── app.core.database
  ├── app.api.v1 (路由聚合)
  └── app.core.exceptions (全局异常处理)

app/api/v1/cargo/router.py
  ├── app.core.dependencies (get_cargo_service)
  ├── app.core.security (require_roles)
  ├── app.schemas.cargo (请求/响应Schema)
  └── app.tasks.ai_tasks (trigger_cargo_parse)

app/services/cargo_service.py
  ├── app.repositories.cargo_repository
  ├── app.repositories.address_repository
  ├── app.repositories.audit_repository
  └── app.core.exceptions

app/workflows/cargo_parse_workflow.py
  ├── app.agents.cargo_agent
  └── app.repositories.cargo_repository

app/agents/cargo_agent.py
  ├── app.tools.cargo_tools
  ├── app.tools.entity_match_tools
  └── app.tools.database_tools

app/tools/cargo_tools.py
  ├── app.ai.llm_client
  └── app.ai.prompt_templates
```

---

## 9. 扩展指南

### 9.1 新增AI Agent

1. 在 `app/tools/` 创建所需Tool（如果现有Tool不够用）
2. 在 `app/agents/` 创建Agent类，继承 `BaseAgent`
3. 在 `app/workflows/` 创建对应Workflow
4. 在 `app/services/` 中的Service通过Workflow调用Agent

### 9.2 新增业务模块

1. 在 `app/models/` 添加领域模型
2. 执行 `make migrate-create msg="add new model"` 生成迁移
3. 在 `app/repositories/` 创建Repository
4. 在 `app/services/` 创建Service
5. 在 `app/schemas/` 创建Schema
6. 在 `app/api/v1/` 创建Router
7. 在 `app/core/dependencies.py` 注册依赖

### 9.3 新增AI分析能力

1. 在 `app/ai/prompt_templates.py` 添加新提示词模板
2. 创建对应Tool（如需新类型数据访问）
3. 扩展 `AnalysisAgent` 或创建新Agent
4. 在 `AnalysisService` 中调用新Agent

---

*文档版本：V2.0 | 最后更新：2026-03-14*
