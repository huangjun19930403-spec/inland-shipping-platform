# 中国内河航运数据采集与分析平台 — 技术开发指南

> 版本：V1.0 · 适合人群：需要二次开发、调试或扩展本项目的后端工程师

---

## 目录

1. [项目总览](#1-项目总览)
2. [技术栈与框架版本](#2-技术栈与框架版本)
3. [项目目录结构详解](#3-项目目录结构详解)
4. [核心架构设计思路](#4-核心架构设计思路)
5. [启动流程全链路分析](#5-启动流程全链路分析)
6. [数据库层详解](#6-数据库层详解)
7. [认证与权限系统](#7-认证与权限系统)
8. [AI 货源解析引擎](#8-ai-货源解析引擎)
9. [审核工作流设计](#9-审核工作流设计)
10. [定时任务系统](#10-定时任务系统)
11. [API 路由层设计](#11-api-路由层设计)
12. [服务层设计模式](#12-服务层设计模式)
13. [数据模型详解（32 张表）](#13-数据模型详解32-张表)
14. [常见调试场景与方法](#14-常见调试场景与方法)
15. [如何扩展新功能](#15-如何扩展新功能)
16. [关键坑点与解决方案](#16-关键坑点与解决方案)

---

## 1. 项目总览

本项目是一个以 **AI 为核心驱动力** 的内河航运数据采集与分析平台后端。区别于"AI 只是一个助手"的设计理念，本项目将 AI（Anthropic Claude API）深度融合到数据处理的核心链路中：

```
微信群原始文本
     │
     ▼
[Claude AI 解析] ← 核心AI节点
     │  提取：起点/终点/货品/吨位/时间/运价/联系方式
     │  输出：结构化JSON + 每字段置信度(0-100)
     ▼
[模糊地址匹配]  ← AI提取文本 + 别名库 difflib 算法
     │  "龙潭码头" → 匹配到「龙潭港（节点ID=5）」
     ▼
[人工确认界面]  ← 人机协作
     │  人工可修正AI识别错误的字段
     ▼
[正式货源数据库] → heatmap_stat_daily（定时聚合）
```

**系统规模**：
- 32 张数据库表
- 106 个 RESTful API 端点
- 4 级 RBAC 权限体系
- 2 个后台定时任务

---

## 2. 技术栈与框架版本

以下是 `requirements.txt` 中所有依赖的作用说明：

| 包名 | 版本 | 用途 |
|------|------|------|
| `fastapi` | 0.128.8 | Web 框架主体，提供路由、依赖注入、自动文档 |
| `uvicorn[standard]` | 0.39.0 | ASGI 服务器，运行 FastAPI 应用 |
| `sqlalchemy` | 2.0.48 | ORM + 异步数据库引擎 |
| `aiosqlite` | 0.22.1 | SQLite 异步驱动（SQLAlchemy async 底层依赖） |
| `greenlet` | ≥3.0.0 | SQLAlchemy 异步模式必须的协程切换库 |
| `pydantic` | 2.12.5 | 数据验证/序列化，V2 API |
| `pydantic-settings` | ≥2.0.0 | 从 `.env` 文件读取配置 |
| `python-jose[cryptography]` | 3.5.0 | JWT Token 生成与验证 |
| `bcrypt` | （无版本锁定） | 密码哈希（不用 passlib，直接用 bcrypt 库） |
| `python-multipart` | 0.0.20 | 支持 Form 表单提交（OAuth2 登录需要） |
| `anthropic` | 0.84.0 | Anthropic Claude API 官方 SDK |
| `apscheduler` | 3.11.2 | 定时任务调度器 |
| `httpx` | 0.28.1 | 异步 HTTP 客户端（测试/内部请求使用） |
| `python-dotenv` | ≥1.0.0 | 加载 `.env` 环境变量 |

### 版本选择关键点

**为什么不用 passlib？**
passlib 1.7.4 与高版本 bcrypt（≥4.0）存在兼容性 Bug，会在启动时抛出
`ValueError: password cannot be longer than 72 bytes`。
本项目直接使用 `bcrypt` 库原生 API，彻底绕开此问题。

**为什么需要 greenlet？**
SQLAlchemy 2.0 异步模式内部用 greenlet 实现同步/异步桥接。
虽然 `sqlalchemy[asyncio]` 会提示需要 greenlet，但不会自动安装，
必须手动 `pip install greenlet`。

**为什么用 aiosqlite 而不是普通 sqlite3？**
FastAPI 是异步框架，所有 I/O 操作必须是非阻塞的。
`sqlite3` 是同步驱动，在 async 上下文里调用会阻塞事件循环。
`aiosqlite` 提供了 SQLite 的异步接口，是 SQLAlchemy async + SQLite 的标准搭配。

---

## 3. 项目目录结构详解

```
inland-shipping-platform/
│
├── main.py                        # ① 应用入口：lifespan + FastAPI 实例 + 数据初始化
├── requirements.txt               # 依赖清单
├── start.sh                       # 一键启动脚本（生产/快速启动用）
├── .env                           # 环境配置（含 API Key，不提交到 Git）
├── .env.example                   # 环境配置模板
│
├── app/
│   ├── core/                      # ② 核心基础设施层
│   │   ├── config.py              #    全局配置（Settings 类，读 .env）
│   │   ├── database.py            #    数据库引擎 + Session 工厂 + init_db()
│   │   └── security.py            #    JWT 认证 + bcrypt 密码 + RBAC 权限装饰器
│   │
│   ├── models/                    # ③ 数据库模型层（SQLAlchemy ORM）
│   │   ├── __init__.py            #    空文件，使 models 成为 Python 包
│   │   ├── address.py             #    地址体系：水系/区域/节点/别名（7张表）
│   │   ├── cargo.py               #    货品+货源：分类/标准/别名/原始/AI解析/货源（9张表）
│   │   ├── vessel.py              #    船舶体系：类型/档案/历史名/AIS/动态（5张表）
│   │   ├── route.py               #    航线体系：商业航线/路径节点（2张表）
│   │   ├── analysis.py            #    统计分析：热力日统计表（1张表）
│   │   ├── audit.py               #    审核记录表（1张表）
│   │   └── system.py              #    系统：用户/角色/关联（3张表）
│   │
│   ├── schemas/                   # ④ Pydantic 模式层（请求/响应数据结构）
│   │   ├── common.py              #    公共：PageResult/分页/基础响应
│   │   ├── address.py             #    地址相关请求/响应模型
│   │   ├── cargo.py               #    货品/货源请求/响应模型
│   │   ├── vessel.py              #    船舶请求/响应模型
│   │   ├── route.py               #    航线请求/响应模型
│   │   ├── analysis.py            #    分析统计响应模型
│   │   └── system.py              #    用户/角色请求/响应模型
│   │
│   ├── services/                  # ⑤ 业务逻辑服务层（核心业务代码）
│   │   ├── audit_service.py       #    统一审核服务（创建/通过/驳回/自动建别名）
│   │   ├── address_service.py     #    地址 CRUD + 审核集成
│   │   ├── cargo_service.py       #    货品/货源 CRUD + AI 解析集成
│   │   ├── vessel_service.py      #    船舶 CRUD + 历史记录自动追踪
│   │   ├── route_service.py       #    航线管理
│   │   └── analysis_service.py    #    热力统计 + 仪表盘数据
│   │
│   ├── ai_engine/                 # ⑥ AI 引擎层（核心 AI 模块）
│   │   └── parser.py              #    Claude API 调用 + 模糊匹配 + 解析结果持久化
│   │
│   ├── tasks/                     # ⑦ 定时任务层
│   │   └── scheduler.py           #    APScheduler：每日统计聚合 + 超时清理
│   │
│   └── api/                       # ⑧ API 路由层
│       └── v1/
│           ├── __init__.py        #    聚合所有子路由到 api_router
│           ├── auth/router.py     #    认证：登录/登出/当前用户
│           ├── address/router.py  #    地址管理：水系/区域/节点/别名
│           ├── cargo/router.py    #    货品+货源：手动录入/AI解析/确认
│           ├── vessel/router.py   #    船舶管理
│           ├── route/router.py    #    航线管理
│           ├── analysis/router.py #    数据分析：热力图/趋势/看板
│           ├── ai/router.py       #    AI 管理：解析状态/重新解析
│           ├── audit/router.py    #    审核中心：待审/历史/通过/驳回
│           └── system/router.py   #    系统管理：用户/角色
```

### 理解各层的职责分工

```
请求进来 → api/v1/xxx/router.py（路由层）
               │ 验证请求参数（Pydantic Schema）
               │ 检查权限（security.require_roles）
               ▼
           services/xxx_service.py（服务层）
               │ 核心业务逻辑
               │ 调用 models（ORM 操作数据库）
               │ 可能调用 audit_service（触发审核流）
               │ 可能调用 ai_engine/parser.py（触发 AI 解析）
               ▼
           models/xxx.py（模型层）
               │ SQLAlchemy ORM 类定义
               │ 映射到数据库表
               ▼
           database（SQLite 文件）
```

---

## 4. 核心架构设计思路

### 4.1 全异步架构

整个项目采用 Python `async/await` 异步编程模型，核心原则：
- **所有数据库操作** 必须使用 `await` + `AsyncSession`
- **所有路由函数** 都是 `async def`
- **所有服务函数** 都是 `async def`
- HTTP 请求处理过程中不会阻塞事件循环

```python
# 正确写法（异步）
async def get_nodes(db: AsyncSession):
    result = await db.execute(select(TransportNode))
    return result.scalars().all()

# 错误写法（同步，会阻塞事件循环）
def get_nodes(db: Session):
    return db.query(TransportNode).all()
```

### 4.2 依赖注入模式

FastAPI 的依赖注入（`Depends`）是本项目的核心设计模式，贯穿认证、数据库会话、权限控制：

```python
# 依赖链路示例：一个需要管理员权限的接口
@router.get("/admin/data")
async def admin_endpoint(
    db: AsyncSession = Depends(get_db),                          # 注入数据库会话
    auth = Depends(require_roles("ADMIN", "SUPER_ADMIN")),       # 注入权限检查
):
    user, roles = auth   # auth 返回 (user对象, roles列表)
    # db 已经是一个可用的异步 Session
```

**依赖链完整路径**：
```
require_roles("ADMIN")
    └── get_current_user_roles(current_user=Depends(get_current_user), db=...)
            └── get_current_user(token=Depends(oauth2_scheme), db=...)
                    └── get_db()  ← 创建数据库会话
```

### 4.3 分层事务管理

数据库事务在路由层统一提交，服务层只调用 `flush()`（写入内存，不提交）：

```python
# router.py（路由层）：负责 commit 或 rollback
@router.post("/nodes")
async def create_node(data: ..., db: AsyncSession = Depends(get_db)):
    result = await address_service.create_node(db, data)  # 服务层只 flush
    await db.commit()   # ← 路由层统一提交
    return result

# address_service.py（服务层）：只 flush，不 commit
async def create_node(db: AsyncSession, data: ...):
    node = TransportNode(**data.model_dump())
    db.add(node)
    await db.flush()   # ← 写入内存（获得自增 ID），但不提交到磁盘
    # 创建审核记录（同一事务）
    await audit_service.create_audit_record(db, ...)
    return node
```

这样做的好处：如果服务层在 flush 之后出错，路由层不调用 commit，整个事务自动回滚。

---

## 5. 启动流程全链路分析

`main.py` 是整个项目的入口，启动时发生的事情：

```python
# main.py 执行顺序（简化）

# 1. 模块导入（Python 解释器加载时）
from app.core.config import settings    # 读取 .env，初始化 Settings 单例
from app.core.database import init_db  # 准备好数据库引擎（还没建表）
from app.api.v1 import api_router       # 注册所有 106 个路由
from app.tasks.scheduler import ...    # 导入定时任务函数（还没启动）

# 2. FastAPI 实例创建
app = FastAPI(title=..., lifespan=lifespan)
app.add_middleware(CORSMiddleware, ...)
app.include_router(api_router, prefix="/api/v1")

# 3. uvicorn 启动，触发 lifespan
@asynccontextmanager
async def lifespan(app):
    # ── 启动阶段 ──
    await init_db()              # 步骤A：建表（如果不存在）
    await _seed_initial_data()   # 步骤B：写入基础数据（幂等，已有则跳过）
    setup_scheduler()            # 步骤C：启动定时任务调度器

    yield  # ← 服务正常运行，接受请求

    # ── 关闭阶段（Ctrl+C 时执行）──
    shutdown_scheduler()         # 优雅关闭调度器
```

### 步骤A：`init_db()` 建表逻辑

```python
# app/core/database.py
async def init_db():
    # 关键：必须先 import 所有 model 文件，让 SQLAlchemy 知道有哪些表
    from app.models import address, cargo, vessel, route, analysis, system, audit

    async with engine.begin() as conn:
        # create_all 是幂等的：只创建不存在的表，不修改已有表
        await conn.run_sync(Base.metadata.create_all)
```

> ⚠️ **重要**：如果你新增了一个 model 文件，必须在这里 import，否则新表不会被创建。

### 步骤B：`_seed_initial_data()` 基础数据

系统内置了完整的基础数据，**首次运行自动写入，重复运行幂等（不重复插入）**：

| 函数 | 写入内容 |
|------|---------|
| `_seed_initial_data()` | 4个角色（SUPER_ADMIN/ADMIN/OPERATOR/COLLECTOR）+ 2个用户（admin/collector1） |
| `_seed_address_data()` | 8条水系 + 13个区域 + 8种节点类型 + 10个重要港口节点（含坐标和别名） |
| `_seed_commodity_data()` | 5个货品大类 + N个类型 + 19个标准货品 + 每个货品的别名列表 |
| `_seed_vessel_type_data()` | 13种船舶类型 |

幂等实现方式（以节点为例）：
```python
# 先查，有则跳过，无则插入
res = await db.execute(select(TransportNode).where(TransportNode.code == nd["code"]))
if not res.scalar_one_or_none():
    node = TransportNode(**nd, audit_status=1)
    db.add(node)
```

---

## 6. 数据库层详解

### 6.1 引擎配置

```python
# app/core/database.py
engine = create_async_engine(
    "sqlite+aiosqlite:///./inland_shipping.db",  # 文件存储在项目根目录
    echo=False,         # True 时会在终端打印所有 SQL，调试时可以改为 True
    connect_args={"check_same_thread": False},   # SQLite 必须加这个，允许多线程
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # commit 后不失效对象（避免二次查询）
)
```

### 6.2 Session 的两种使用方式

**方式一：HTTP 请求中（通过依赖注入）**
```python
# 每个 HTTP 请求自动获得一个独立的 Session，请求结束自动关闭
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
```

**方式二：后台任务/定时任务中（手动创建）**
```python
# 定时任务或 BackgroundTask 中，需要手动创建 Session
async def daily_stats_job():
    async with AsyncSessionLocal() as db:
        try:
            await run_daily_stats(db, date.today())
            await db.commit()
        except Exception as e:
            await db.rollback()
```

### 6.3 关系加载：selectinload 的使用

SQLAlchemy 默认使用「懒加载」（lazy loading），但在 async 模式下懒加载会报错（因为不能在 async 上下文外访问数据库）。

解决方案：使用 `selectinload` 预先加载关联数据。

```python
# 错误示例（会报 MissingGreenlet 错误）
result = await db.execute(select(TransportNode))
nodes = result.scalars().all()
for node in nodes:
    print(node.aliases)  # ← 触发懒加载，在 async 上下文外，报错！

# 正确示例（使用 selectinload 预加载）
from sqlalchemy.orm import selectinload

result = await db.execute(
    select(TransportNode).options(selectinload(TransportNode.aliases))
)
nodes = result.scalars().all()
for node in nodes:
    print(node.aliases)  # ← 已预加载，正常访问
```

---

## 7. 认证与权限系统

### 7.1 登录流程

```
POST /api/v1/auth/login
  body: { username: "admin", password: "Admin@2026" }
     │
     ▼
  查询 SysUser（by username）
     │ 用户不存在或 status=0 → 返回 401
     ▼
  bcrypt.checkpw(password, password_hash)
     │ 密码错误 → 返回 401
     ▼
  jwt.encode({ "sub": str(user.id), "exp": ... }, SECRET_KEY)
     │
     ▼
  返回 { "access_token": "eyJ...", "token_type": "bearer" }
```

### 7.2 请求认证流程

```
后续请求 Header: Authorization: Bearer eyJ...
     │
     ▼
  oauth2_scheme 提取 token
     │
     ▼
  get_current_user()
     │  jwt.decode(token, SECRET_KEY) → 获取 user_id
     │  查询 SysUser(id=user_id, status=1)
     ▼
  返回 user 对象
```

### 7.3 RBAC 权限装饰器

```python
# security.py 中的 require_roles 工厂函数
def require_roles(*allowed_roles):
    async def role_checker(user_roles=Depends(get_current_user_roles)):
        user, roles = user_roles
        if "SUPER_ADMIN" in roles:  # SUPER_ADMIN 拥有所有权限，直接放行
            return user, roles
        for role in allowed_roles:
            if role in roles:       # 命中任意一个角色，放行
                return user, roles
        raise HTTPException(403, "权限不足")
    return role_checker

# 使用示例
@router.post("/admin-only")
async def admin_endpoint(auth=Depends(require_roles("ADMIN"))):
    user, roles = auth
    ...

@router.post("/multi-role")
async def multi_role_endpoint(auth=Depends(require_roles("ADMIN", "OPERATOR"))):
    ...
```

### 7.4 密码哈希实现

直接使用 `bcrypt` 库（不经过 passlib）：

```python
import bcrypt

# 加密（注册/初始化时）
def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

# 验证（登录时）
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8")
    )
```

---

## 8. AI 货源解析引擎

文件位置：`app/ai_engine/parser.py`

这是整个系统最核心的模块，分为三个子系统协同工作：

### 8.1 Claude API 调用（`_call_claude`）

```python
async def _call_claude(raw_text: str) -> dict:
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-6",    # 使用 Claude Sonnet 模型
        max_tokens=1024,
        system=PARSE_SYSTEM_PROMPT,  # 系统提示词（专家身份设定 + 输出格式要求）
        messages=[{
            "role": "user",
            "content": f"今天日期：{today}\n\n请解析以下货源信息：\n\n{raw_text}"
        }],
    )
    # 提取 JSON（兼容 Claude 有时会加 ```json 代码块的情况）
    text = message.content[0].text.strip()
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    return json.loads(json_match.group())
```

**系统提示词设计要点**：
- 明确告知提取的 9 个字段（origin/destination/commodity/tonnage/loading_date/freight/price_type/contact_person/contact_phone）
- 强制 JSON 输出格式（避免自然语言回答）
- 要求每个字段附带置信度分数（0-100），以及整体置信度
- 处理"今天"/"明天"等相对日期（提示词里注入当前日期）

**降级处理**：当 `ANTHROPIC_API_KEY` 未配置或 API 调用失败时，返回空结构（所有字段为 null，置信度为 0），系统不会崩溃，人工可以手动填写。

### 8.2 模糊地址/货品匹配（`_fuzzy_score` + `_match_node`）

```python
def _fuzzy_score(query: str, target: str) -> float:
    # 精确匹配：得分 1.0
    if query == target: return 1.0
    # 包含关系：得分 0.85（"龙潭码头" in "龙潭码头港区" 或反之）
    if query in target or target in query: return 0.85
    # 序列相似度：difflib 算法（0.0~1.0）
    return difflib.SequenceMatcher(None, query, target).ratio()
```

`_match_node` 的完整流程：
```
Claude 提取文本（如"武汉阳逻"）
     │
     ▼
查询所有别名（node_alias 表）和标准名（transport_node 表）
     │
     ▼
对每条别名/标准名计算 _fuzzy_score
     │  得分 >= 0.5 才入候选
     ▼
去重（同一节点保留最高分）
     │
     ▼
按 score desc, priority desc 排序
     │
     ▼
返回 (top_node_id, confidence_0_100, top5_candidates)
```

### 8.3 主解析函数（`parse_cargo_text`）

```python
async def parse_cargo_text(db, raw_message_id):
    # 1. 读原始文本，标记状态为 PARSING
    raw_msg.status = "PARSING"

    # 2. 调 Claude API
    parsed = await _call_claude(raw_msg.raw_text)

    # 3. 模糊匹配地址和货品
    origin_node_id, origin_conf, origin_candidates = await _match_node(db, parsed["origin"])
    dest_node_id, dest_conf, dest_candidates = await _match_node(db, parsed["destination"])
    commodity_id, commodity_conf, commodity_candidates = await _match_commodity(db, parsed["commodity"])

    # 4. 置信度加权融合（AI置信度 + 匹配置信度 平均）
    final_origin_conf = int((ai_origin_conf + origin_conf) / 2) if origin_node_id else ai_origin_conf

    # 5. 持久化 CargoAiParseResult
    result = CargoAiParseResult(
        origin_node_id=origin_node_id,
        origin_confidence=final_origin_conf,
        origin_candidates=origin_candidates,  # JSON 存储候选列表
        ...
        parse_status="PENDING_CONFIRM",        # 等待人工确认
    )

    # 6. 更新原始消息状态为 PARSED
    raw_msg.status = "PARSED"
```

### 8.4 异步解析触发机制（BackgroundTasks）

AI 解析是耗时操作（需要调用外部 API），不能让 HTTP 请求等待：

```python
# app/api/v1/cargo/router.py

@router.post("/cargo/text")
async def create_cargo_text(
    data: CargoRawMessageCreate,
    background_tasks: BackgroundTasks,  # FastAPI 内置后台任务
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_roles("COLLECTOR", "OPERATOR")),
):
    # 1. 立即创建原始消息记录（同步返回）
    raw_msg = await cargo_service.create_cargo_text(db, data, user.id)
    await db.commit()
    raw_id = raw_msg.id

    # 2. 将 AI 解析加入后台任务队列（不阻塞 HTTP 响应）
    async def _run_ai_parse(raw_message_id):
        async with AsyncSessionLocal() as bg_db:  # 后台任务需要独立 Session！
            await parse_cargo_text(bg_db, raw_message_id)
            await bg_db.commit()

    background_tasks.add_task(_run_ai_parse, raw_id)

    # 3. 立即返回（AI 解析在后台进行）
    return {"id": raw_id, "status": "PARSING", "message": "AI解析已在后台启动"}
```

> ⚠️ **关键点**：后台任务必须创建独立的 `AsyncSession`，不能复用 HTTP 请求的 Session（因为 HTTP 请求的 Session 在响应返回后就关闭了）。

---

## 9. 审核工作流设计

所有「主数据」（运输节点、标准货品、船舶档案）在创建后都进入审核流程，未审核的数据不参与 AI 匹配。

### 9.1 审核状态机

```
创建数据
  │  audit_status = 0（待审核）
  ▼
[审核中心] → APPROVE（通过） → audit_status = 1（已通过）+ 自动建别名
           → REJECT（驳回）  → audit_status = 2（已驳回）
```

### 9.2 自动建别名逻辑

审核通过时，`_apply_approval` 会自动创建标准名别名：

```python
# audit_service.py → _apply_approval()

if target_type == "TRANSPORT_NODE":
    node.audit_status = 1
    # 检查是否已有标准名的别名
    existing_alias = await db.execute(
        select(NodeAlias).where(
            NodeAlias.node_id == target_id,
            NodeAlias.alias_name == node.name  # 标准名
        )
    )
    if not existing_alias.scalar_one_or_none():
        # 自动创建标准名别名（供 AI 模糊匹配使用）
        db.add(NodeAlias(
            node_id=target_id,
            alias_name=node.name,
            alias_type="SYSTEM",  # 系统自动创建
            priority=100,         # 最高优先级
        ))
```

这意味着：每个被批准的节点，其标准名自动成为可被 AI 匹配的别名。

### 9.3 自审限制

```python
async def check_can_audit(submitter_id, auditor_id, user_roles) -> bool:
    if "SUPER_ADMIN" in user_roles:
        return True   # 超级管理员可以自审
    if submitter_id == auditor_id:
        return False  # 普通用户不能审核自己提交的数据
    return True
```

---

## 10. 定时任务系统

文件位置：`app/tasks/scheduler.py`

使用 `APScheduler` 的 `AsyncIOScheduler`（兼容 asyncio 事件循环）：

### 10.1 两个定时任务

**任务一：每日统计聚合（`daily_stats_job`）**
- 触发器：`CronTrigger(hour=2, minute=0)`（每天凌晨 2:00）
- 允许延迟：`misfire_grace_time=300`（5分钟内的错过都会补跑）
- 执行内容：`run_daily_stats()` — 聚合当天货源数据到 `heatmap_stat_daily` 表

**任务二：超时解析清理（`cleanup_stale_parsing_job`）**
- 触发器：`IntervalTrigger(hours=1)`（每小时一次）
- 执行内容：将 `PARSING` 状态超过 1 小时的原始消息重置为 `PENDING`
- 作用：防止 AI 解析异常后消息永远卡在 `PARSING` 状态

### 10.2 统计聚合 UPSERT 逻辑

SQLite 对复合唯一键的 `ON CONFLICT` 支持有限，采用 Python 级别的 UPSERT：

```python
for row in origin_rows:
    # 先查是否已有当天该节点的统计记录
    existing = await db.execute(
        select(HeatmapStatDaily).where(
            HeatmapStatDaily.stat_date == target_date,
            HeatmapStatDaily.node_id == row.node_id,
            HeatmapStatDaily.stat_type == "CARGO_ORIGIN",
        )
    )
    if existing.scalar_one_or_none():
        existing.cargo_count = row.cargo_count  # 更新
    else:
        db.add(HeatmapStatDaily(...))            # 插入
```

---

## 11. API 路由层设计

### 11.1 路由聚合

所有子路由在 `app/api/v1/__init__.py` 中聚合：

```python
from fastapi import APIRouter
from .auth.router import router as auth_router
from .address.router import router as address_router
# ...

api_router = APIRouter()
api_router.include_router(auth_router,     prefix="/auth",     tags=["认证"])
api_router.include_router(address_router,  prefix="/address",  tags=["地址管理"])
# ...
```

在 `main.py` 中整体挂载到 `/api/v1`：
```python
app.include_router(api_router, prefix="/api/v1")
```

最终 URL 形如：`/api/v1/address/transport-node`

### 11.2 完整 API 端点列表（106个）

#### 认证（3个）
```
POST   /api/v1/auth/login           用户登录，返回 JWT Token
GET    /api/v1/auth/me              获取当前用户信息
POST   /api/v1/auth/logout          登出（客户端删 Token 即可）
```

#### 地址管理（24个）
```
# 水系
GET    /api/v1/address/waterway                    水系列表
POST   /api/v1/address/waterway                    创建水系
GET    /api/v1/address/waterway/{id}               水系详情
PUT    /api/v1/address/waterway/{id}               更新水系
DELETE /api/v1/address/waterway/{id}               删除水系

# 区域
GET    /api/v1/address/region                      区域列表
POST   /api/v1/address/region                      创建区域
PUT    /api/v1/address/region/{id}                 更新区域

# 节点类型
GET    /api/v1/address/node-type                   节点类型列表
POST   /api/v1/address/node-type                   创建节点类型

# 运输节点（核心）
GET    /api/v1/address/transport-node              节点列表（支持多维度筛选）
POST   /api/v1/address/transport-node              创建节点（→ 审核流）
GET    /api/v1/address/transport-node/search       模糊搜索（基于别名库）
GET    /api/v1/address/transport-node/{id}         节点详情
PUT    /api/v1/address/transport-node/{id}         更新节点
DELETE /api/v1/address/transport-node/{id}         删除节点
POST   /api/v1/address/transport-node/{id}/approve 直接审核通过
POST   /api/v1/address/transport-node/{id}/reject  直接审核驳回

# 节点别名
GET    /api/v1/address/transport-node/{id}/aliases 查看别名
POST   /api/v1/address/alias                       添加别名
DELETE /api/v1/address/alias/{alias_id}            删除别名
```

#### 货品与货源（26个）
```
# 货品体系
GET/POST       /api/v1/cargo/category               货品大类
GET/PUT/DELETE /api/v1/cargo/category/{id}
GET/POST       /api/v1/cargo/type                   货品类型
GET/PUT/DELETE /api/v1/cargo/type/{id}
GET/POST       /api/v1/cargo/standard               标准货品（支持分页/筛选/关键字）
GET/PUT/DELETE /api/v1/cargo/standard/{id}
POST           /api/v1/cargo/standard/{id}/approve  审批通过
POST           /api/v1/cargo/standard/{id}/reject   审批驳回
POST/DELETE    /api/v1/cargo/alias                  货品别名

# 货源（核心业务）
POST  /api/v1/cargo/cargo/manual                   手动录入货源
POST  /api/v1/cargo/cargo/text                     粘贴文本 → AI解析（异步）
GET   /api/v1/cargo/cargo                          货源列表（分页/多维筛选）
GET   /api/v1/cargo/cargo/{id}                     货源详情
POST  /api/v1/cargo/cargo/{id}/cancel              取消货源

# AI 解析结果
GET   /api/v1/cargo/cargo/ai-results               待确认AI解析结果列表
GET   /api/v1/cargo/cargo/ai-results/{id}          单条解析结果详情
POST  /api/v1/cargo/cargo/ai-results/{id}/confirm  确认AI结果（可修正）
POST  /api/v1/cargo/cargo/ai-results/{id}/discard  废弃AI结果
```

#### 数据分析（6个）
```
GET  /api/v1/analysis/dashboard        仪表盘统计
GET  /api/v1/analysis/cargo-heatmap    货源热力数据
GET  /api/v1/analysis/vessel-heatmap   运力热力数据
GET  /api/v1/analysis/cargo-trends     货源趋势（近N天）
GET  /api/v1/analysis/top-nodes        Top N 节点货源排行
POST /api/v1/analysis/run-stats        手动触发每日统计聚合
```

#### 审核中心（5个）
```
GET  /api/v1/audit/pending             待审核列表（按类型筛选）
GET  /api/v1/audit/history             审核历史
GET  /api/v1/audit/stats               各类型待审核数量
POST /api/v1/audit/{id}/approve        审批通过
POST /api/v1/audit/{id}/reject         审批驳回（必须填写原因）
```

---

## 12. 服务层设计模式

### 12.1 标准 CRUD 模式

```python
# 所有服务函数遵循相同模式

async def get_xxx(db: AsyncSession, xxx_id: int) -> ModelClass:
    result = await db.execute(select(ModelClass).where(ModelClass.id == xxx_id))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="xxx不存在")
    return obj

async def create_xxx(db: AsyncSession, data: CreateSchema) -> ModelClass:
    obj = ModelClass(**data.model_dump())  # Pydantic V2: model_dump() 替代 dict()
    db.add(obj)
    await db.flush()  # 获取自增 ID，但不提交
    return obj

async def update_xxx(db: AsyncSession, xxx_id: int, data: UpdateSchema) -> ModelClass:
    obj = await get_xxx(db, xxx_id)
    for field, value in data.model_dump(exclude_none=True).items():  # 只更新非空字段
        setattr(obj, field, value)
    await db.flush()
    return obj
```

### 12.2 分页查询模式

```python
# 所有列表接口统一使用 PageResult 返回分页数据
async def get_list(db, page=1, page_size=20, **filters) -> PageResult:
    query = select(Model)
    count_query = select(func.count(Model.id))

    # 动态添加过滤条件
    conditions = []
    if filters.get("keyword"):
        conditions.append(Model.name.ilike(f"%{keyword}%"))
    if conditions:
        query = query.where(and_(*conditions))
        count_query = count_query.where(and_(*conditions))

    # 先查总数（不分页）
    total = (await db.execute(count_query)).scalar_one()

    # 再查数据（分页）
    query = query.order_by(Model.created_at.desc())
                 .offset((page - 1) * page_size)
                 .limit(page_size)
    items = (await db.execute(query)).scalars().all()

    return PageResult(total=total, items=list(items), page=page, page_size=page_size)
```

---

## 13. 数据模型详解（32 张表）

### 13.1 地址体系（7张表）

```
waterway（水系）          code / name / length_km / status
    │ 1:N
region（区域）            code / name / waterway_id / sort_order
    │ 1:N
transport_node（运输节点） code / name / node_type_id / waterway_id / region_id
                           province / city / longitude / latitude（坐标，供热力图）
                           audit_status(0待审/1通过/2驳回) / submitter_id / auditor_id
    │ 1:N
node_alias（节点别名）     node_id / alias_name / alias_type(SYSTEM/COMMON/ABBR)
                           priority(优先级0-100) / status

node_type（节点类型）      code / name / transport_mode(WATERWAY/RAILWAY/HIGHWAY/MULTIMODAL)
admin_region（行政区）     code / name / parent_id / level
region_address_relation    region_id / node_id（区域-节点 M:N 关联）
```

**关键字段说明**：
- `audit_status`：0=待审，1=已通过，2=已驳回。只有 `audit_status=1` 的节点才参与 AI 模糊匹配。
- `longitude/latitude`：经纬度坐标，供前端热力图渲染使用。
- `node_alias.priority`：别名优先级，匹配时高优先级排在候选列表前面。`SYSTEM` 类型（标准名）优先级=100。

### 13.2 货品体系（4张主表 + 3张货源表 = 7张）

```
commodity_category（货品大类）   散货/液货/集装箱/件杂货/特种货
    │ 1:N
commodity_type（货品类型）       能源矿产/粮食/建材等
    │ 1:N
commodity_standard（标准货品）   动力煤/铁矿石/黄沙等
    │ 1:N               audit_status + submitter_id/auditor_id
commodity_alias（货品别名）      alias_name + priority

cargo_raw_message（原始文本）    raw_text / source_type / group_name / sender_name
                                  status: PENDING → PARSING → PARSED/INVALID
cargo_ai_parse_result（AI解析）  origin_text/dest_text/commodity_text（AI提取的原始文本）
                                  origin_node_id/dest_node_id/commodity_id（模糊匹配结果）
                                  origin_confidence/dest_confidence（0-100置信度）
                                  origin_candidates/dest_candidates（JSON候选列表）
                                  parse_status: PENDING_CONFIRM / CONFIRMED / DISCARDED
cargo_opportunity（正式货源）    opportunity_no(CO开头唯一编号) / origin_node_id / dest_node_id
                                  tonnage / loading_date / freight_price / price_type
                                  status: CONFIRMED / CANCELLED
                                  input_type: MANUAL / AI_PARSE
```

### 13.3 船舶体系（5张表）

```
vessel_type_dict（船型字典）  BC散货/TC油船/CC集装箱...
vessel（船舶档案）           vessel_name / vessel_type_id / mmsi / imo
                              deadweight（载重吨） / length / width
                              audit_status + is_deleted
vessel_name_history（历史船名）  vessel_id / old_name / changed_at
vessel_ais_history（AIS记录）   vessel_id / longitude / latitude / speed / report_time
vessel_dynamic（最新动态）       vessel_id / current_node_id / dynamic_status
                                  loading_status / arrival_time / departure_time
```

### 13.4 其他表

```
shipping_route（商业航线）       origin_region_id / dest_region_id / distance_km
shipping_route_path（路径节点）  route_id / node_id / sequence（顺序）

heatmap_stat_daily（热力日统计）  stat_date / node_id / stat_type(CARGO_ORIGIN/CARGO_DEST/VESSEL)
                                   cargo_count / total_tonnage / vessel_count / total_deadweight
                                   ⚠️ 唯一约束：(stat_date, node_id, stat_type)

audit_record（审核记录）          target_type / target_id / target_name
                                   action(CREATE/UPDATE/DELETE)
                                   before_data / after_data（JSON，变更前后快照）
                                   audit_result: PENDING / APPROVED / REJECTED
                                   submitter_id/name / auditor_id/name / audit_remark

sys_user（用户）                  username / real_name / password_hash
                                   wx_open_id / wx_bound（微信小程序绑定）
sys_role（角色）                  code / name（SUPER_ADMIN/ADMIN/OPERATOR/COLLECTOR）
sys_user_role（用户角色关联）      user_id + role_id（多对多）
```

---

## 14. 常见调试场景与方法

### 14.1 查看所有 SQL 语句

修改 `app/core/database.py`：
```python
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=True,   # ← 改为 True，终端会打印所有 SQL
    ...
)
```

### 14.2 在 PyCharm 中设置断点

推荐的断点位置：

| 场景 | 文件 | 函数 | 说明 |
|------|------|------|------|
| 调试登录 | `app/core/security.py` | `verify_password` | 查看密码验证过程 |
| 调试权限 | `app/core/security.py` | `role_checker` | 查看用户角色列表 |
| 调试 AI 解析 | `app/ai_engine/parser.py` | `parse_cargo_text` | 查看 Claude 返回的原始 JSON |
| 调试模糊匹配 | `app/ai_engine/parser.py` | `_match_node` | 查看匹配候选列表和得分 |
| 调试审核通过 | `app/services/audit_service.py` | `_apply_approval` | 查看别名自动创建逻辑 |
| 调试统计聚合 | `app/services/analysis_service.py` | `run_daily_stats` | 查看 UPSERT 逻辑 |
| 调试任何请求 | `app/api/v1/cargo/router.py` | 对应路由函数 | 查看请求参数和返回值 |

### 14.3 使用 Swagger UI 调试

启动后访问 `http://localhost:8000/docs`：

1. 先调用 `POST /api/v1/auth/login`，用 admin/Admin@2026 获取 Token
2. 点右上角 `Authorize`，输入 Token
3. 之后所有接口自动带上认证头

### 14.4 直接查看数据库

SQLite 数据库文件在项目根目录：`inland_shipping.db`

推荐工具：
- **DB Browser for SQLite**（免费 GUI 工具）
- **PyCharm Database 面板**（需要 PyCharm Professional）
- 命令行：`sqlite3 inland_shipping.db`

### 14.5 手动触发 AI 解析重试

如果 AI 解析失败（raw_message.status 卡在 PARSING），可以：

```bash
# 通过 API 手动重新解析
POST /api/v1/ai/reparse/{raw_message_id}
```

或直接修改数据库将状态改回 PENDING，等待下一次定时任务清理。

### 14.6 常见错误排查

| 错误信息 | 原因 | 解决方案 |
|---------|------|---------|
| `No module named 'greenlet'` | venv 缺少 greenlet | `pip install greenlet` |
| `MissingGreenlet` 在访问关系时 | 懒加载在 async 上下文外触发 | 使用 `selectinload` 预加载 |
| `NOT NULL constraint failed: sys_role.id` | SQLite 不支持 BigInteger 自增 | 主键改用 `Integer` 而非 `BigInteger` |
| `401 认证失败` | Token 过期或格式错误 | 重新登录获取 Token |
| `403 权限不足` | 用户角色不满足接口要求 | 用对应角色的用户调用 |
| `ValueError: password cannot be longer...` | passlib + 新版 bcrypt 兼容问题 | 改用直接 import bcrypt（本项目已修复） |
| AI 解析返回全空 | API Key 未配置 | 在 `.env` 设置 `ANTHROPIC_API_KEY` |

---

## 15. 如何扩展新功能

### 15.1 新增一张数据库表

**步骤**：

1. 在 `app/models/` 下创建或修改模型文件：
```python
# app/models/your_module.py
from sqlalchemy import Column, Integer, String
from app.core.database import Base

class YourModel(Base):
    __tablename__ = "your_table"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False)
```

2. 在 `app/core/database.py` 的 `init_db()` 中添加 import：
```python
async def init_db():
    from app.models import address, cargo, vessel, route, analysis, system, audit
    from app.models import your_module  # ← 新增这行
    ...
```

3. 重启服务，`create_all` 会自动建表。

> ⚠️ `create_all` 只能创建新表，不能修改已有表结构。如需修改已有表，最简单的方式是删掉 `.db` 文件重建（开发环境），生产环境需要使用 Alembic 数据库迁移工具。

### 15.2 新增一个 API 接口

**步骤**：

1. 在 `app/schemas/` 下定义请求/响应模型：
```python
# app/schemas/your_module.py
from pydantic import BaseModel

class YourCreate(BaseModel):
    name: str
    description: str | None = None

class YourResponse(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}  # Pydantic V2 ORM 模式
```

2. 在 `app/services/` 下实现业务逻辑：
```python
# app/services/your_service.py
async def create_your(db: AsyncSession, data: YourCreate) -> YourModel:
    obj = YourModel(**data.model_dump())
    db.add(obj)
    await db.flush()
    return obj
```

3. 在 `app/api/v1/` 下创建路由：
```python
# app/api/v1/your/router.py
from fastapi import APIRouter, Depends
from app.core.database import get_db
from app.core.security import require_roles

router = APIRouter()

@router.post("/", response_model=YourResponse)
async def create(
    data: YourCreate,
    db: AsyncSession = Depends(get_db),
    auth=Depends(require_roles("OPERATOR")),
):
    user, roles = auth
    result = await your_service.create_your(db, data)
    await db.commit()
    await db.refresh(result)
    return result
```

4. 在 `app/api/v1/__init__.py` 中注册路由：
```python
from .your.router import router as your_router
api_router.include_router(your_router, prefix="/your", tags=["你的模块"])
```

### 15.3 新增一个定时任务

在 `app/tasks/scheduler.py` 的 `setup_scheduler()` 中添加：

```python
scheduler.add_job(
    your_async_function,
    trigger=CronTrigger(hour=3, minute=0),  # 每天凌晨3点
    id="your_job_id",
    name="你的任务描述",
    replace_existing=True,
)
```

### 15.4 修改 AI 解析提示词

编辑 `app/ai_engine/parser.py` 中的 `PARSE_SYSTEM_PROMPT` 变量。

修改提示词后，新提交的文本会使用新的提示词解析，历史数据不受影响。

如果需要新增提取字段，还需要：
1. 在 `CargoAiParseResult` 模型中新增字段列
2. 在 `parse_cargo_text()` 中读取并存储新字段
3. 在 `CargoConfirmRequest` Schema 中加入新字段
4. 在 `confirm_cargo_ai()` 中传递新字段到 `CargoOpportunity`

---

## 16. 关键坑点与解决方案

### 坑点一：SQLite 主键类型

**问题**：`BigInteger` 在 SQLite 中无法自动递增，会报 `NOT NULL constraint failed`。

**原因**：SQLite 只对 `INTEGER PRIMARY KEY` 提供自动递增，BIGINT 被映射为不同的存储类型。

**解决方案**：所有主键一律使用 `Integer`，不用 `BigInteger`：
```python
# 错误
id = Column(BigInteger, primary_key=True, autoincrement=True)

# 正确
id = Column(Integer, primary_key=True, autoincrement=True)
```

### 坑点二：Pydantic V2 API 变化

Pydantic V2 与 V1 的 API 完全不同：

```python
# Pydantic V1（旧，不要用）
data.dict()
data.dict(exclude_none=True)
class Config:
    orm_mode = True

# Pydantic V2（新，本项目使用）
data.model_dump()
data.model_dump(exclude_none=True)
model_config = {"from_attributes": True}
```

### 坑点三：重复关键字参数

在 `_seed_address_data` 中初始化 `NodeType` 时，如果 dict 里已有 `transport_mode` 字段，直接 `NodeType(transport_mode="WATERWAY", **ntd)` 会报 `TypeError: got multiple values for keyword argument`。

**解决方案**：用字典合并，让后者覆盖前者：
```python
# 错误
nt = NodeType(transport_mode="WATERWAY", **ntd)

# 正确（ntd 中的 transport_mode 会覆盖默认值）
nt = NodeType(**{**{"transport_mode": "WATERWAY"}, **ntd, "status": 1})
```

### 坑点四：后台任务 Session 隔离

`BackgroundTasks` 在 HTTP 响应返回后才执行，此时 HTTP 请求的 `Session` 已关闭。

**解决方案**：后台任务必须自己创建 `Session`：
```python
# 错误（使用了已关闭的 HTTP Session）
async def my_bg_task(db: AsyncSession, raw_id: int):
    await parse_cargo_text(db, raw_id)  # db 已关闭，报错！

# 正确（独立 Session）
async def my_bg_task(raw_id: int):
    async with AsyncSessionLocal() as db:  # 创建新 Session
        await parse_cargo_text(db, raw_id)
        await db.commit()
```

### 坑点五：Pydantic Schema 需要 `model_config`

如果 Schema 的字段来自 SQLAlchemy ORM 对象，必须配置 `from_attributes = True`：

```python
class NodeResponse(BaseModel):
    id: int
    name: str
    aliases: List[AliasResponse]  # ← 关联数据

    model_config = {"from_attributes": True}  # ← 必须加，否则报 ValidationError
```

---

## 附录：默认账号与环境配置

### 默认账号

| 用户名 | 密码 | 角色 |
|--------|------|------|
| `admin` | `Admin@2026` | 超级管理员（全部权限） |
| `collector1` | `Test@2026` | 数据采集员 |

### 环境变量（`.env` 文件）

```env
# AI 配置（必填，否则 AI 解析降级为规则匹配）
ANTHROPIC_API_KEY=sk-ant-xxxxx

# 数据库（默认 SQLite，生产可改为 PostgreSQL）
DATABASE_URL=sqlite+aiosqlite:///./inland_shipping.db

# JWT 密钥（生产环境必须改为随机强密钥）
SECRET_KEY=inland-shipping-platform-secret-key-2026

# 调试模式
DEBUG=true

# 定时任务：每日统计聚合时间（默认凌晨2点）
STATS_CRON_HOUR=2
STATS_CRON_MINUTE=0
```

### 生产环境切换 PostgreSQL

只需修改 `.env` 中的 `DATABASE_URL`：

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/inland_shipping
```

同时需要安装 asyncpg 驱动：
```bash
pip install asyncpg
```

无需修改任何代码，SQLAlchemy 会自动适配。

---

*文档版本：V1.0 · 最后更新：2026-03-14*
