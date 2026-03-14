# 本地开发与IDE调试指南

**项目：中国内河航运数据采集与分析平台 V2.0**

---

## 目录

1. [环境要求](#1-环境要求)
2. [首次启动](#2-首次启动)
3. [环境变量配置](#3-环境变量配置)
4. [日常开发命令](#4-日常开发命令)
5. [PyCharm调试配置](#5-pycharm调试配置)
6. [VSCode调试配置](#6-vscode调试配置)
7. [数据库管理](#7-数据库管理)
8. [API测试](#8-api测试)
9. [运行测试](#9-运行测试)
10. [常见问题](#10-常见问题)

---

## 1. 环境要求

| 工具 | 最低版本 | 推荐版本 | 说明 |
|------|---------|---------|------|
| Python | 3.11 | 3.12 | 需要异步特性支持 |
| pip | 23.0 | latest | 依赖管理 |
| Git | 2.40 | latest | 版本控制 |
| Redis | 7.0 | 7.2 | 生产Celery必需，开发可选 |

> **开发环境说明：** 开发模式使用SQLite（无需单独安装数据库），使用APScheduler（无需Redis）。只需Python即可完整运行。

---

## 2. 首次启动

### Step 1：克隆项目

```bash
git clone https://github.com/huangjun19930403-spec/inland-shipping-platform.git
cd inland-shipping-platform
```

### Step 2：创建并激活虚拟环境

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate

# Windows
python -m venv .venv
.venv\Scripts\activate
```

### Step 3：安装依赖

```bash
# 开发环境（不包含Celery/Redis相关）
pip install fastapi uvicorn sqlalchemy aiosqlite pydantic pydantic-settings \
            python-jose passlib anthropic apscheduler httpx python-dotenv \
            python-multipart greenlet alembic

# 或安装全部依赖（包含生产依赖）
pip install -r requirements.txt
```

> **注意：** 如果不需要Celery，可以跳过 `celery[redis]` 和 `redis` 的安装，开发环境的任务调度由APScheduler处理。

### Step 4：配置环境变量

```bash
# 复制模板
cp .env.example .env

# 编辑 .env，至少配置 ANTHROPIC_API_KEY
# 开发环境其他配置保持默认即可
```

`.env` 最简配置：

```env
ANTHROPIC_API_KEY=sk-ant-xxxx   # 必填：AI功能需要
DEBUG=true
DATABASE_URL=sqlite+aiosqlite:///./inland_shipping.db
SECRET_KEY=dev-secret-key-change-in-production
```

### Step 5：初始化数据库

```bash
# 方式一：通过Alembic迁移（推荐）
make migrate

# 方式二：直接创建（跳过迁移历史）
python3 -c "import asyncio; from app.core.database import init_db; asyncio.run(init_db())"
```

### Step 6：初始化种子数据

```bash
make seed
# 或
python3 -m scripts.seed_data
```

初始化完成后将创建：
- 4个系统角色（SUPER_ADMIN / ADMIN / OPERATOR / COLLECTOR）
- 2个默认账号（admin/Admin@2026，collector1/Test@2026）
- 8条主要水系数据
- 13个商业区域
- 10个主要运输节点
- 5个商品大类

### Step 7：启动开发服务器

```bash
# 方式一：Makefile命令
make dev

# 方式二：直接uvicorn
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 方式三：Python模块（IDE调试时用）
python3 main.py
```

启动成功后访问：
- **Swagger UI**：http://localhost:8000/docs
- **ReDoc**：http://localhost:8000/redoc
- **健康检查**：http://localhost:8000/health

---

## 3. 环境变量配置

完整的 `.env` 配置说明：

```env
# ─── 应用 ───────────────────────────────────────────
APP_NAME=中国内河航运数据采集与分析平台
APP_VERSION=2.0.0
DEBUG=true                          # 开启调试模式

# ─── 数据库 ─────────────────────────────────────────
# 开发环境（SQLite）
DATABASE_URL=sqlite+aiosqlite:///./inland_shipping.db

# 生产环境（PostgreSQL，在DEPLOYMENT.md中配置）
# DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname

# ─── 认证 ───────────────────────────────────────────
SECRET_KEY=inland-shipping-platform-secret-key-dev   # 生产环境必须更换！
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440    # 24小时

# ─── AI服务 ─────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx    # 从 console.anthropic.com 获取
AI_MODEL=claude-sonnet-4-6
AI_CONFIDENCE_THRESHOLD=60          # 匹配置信度阈值（0-100）

# ─── 任务调度 ────────────────────────────────────────
# 开发环境：APScheduler（无需Redis）
STATS_CRON_HOUR=2                   # 每日统计运行小时（本地时间）
STATS_CRON_MINUTE=0

# 生产环境：Celery（需要Redis）
# CELERY_BROKER_URL=redis://localhost:6379/0
# CELERY_RESULT_BACKEND=redis://localhost:6379/1

# ─── CORS ───────────────────────────────────────────
# 生产环境替换为实际前端域名
ALLOWED_ORIGINS=["http://localhost:3000","http://127.0.0.1:3000","*"]
```

---

## 4. 日常开发命令

项目提供 `Makefile` 统一管理常用命令：

```bash
make dev              # 启动开发服务器（热重载）
make seed             # 初始化种子数据
make migrate          # 执行待执行迁移
make migrate-create msg="描述"   # 生成新迁移文件
make migrate-rollback # 回滚最后一次迁移
make test             # 运行全部测试
make lint             # 代码格式检查与修复
make clean            # 清除Python缓存文件

# 生产环境相关（需要Redis）
make celery-worker    # 启动Celery Worker
make celery-beat      # 启动Celery Beat调度器
```

---

## 5. PyCharm调试配置

### 5.1 配置Run/Debug Configuration

1. 打开 `Run → Edit Configurations`
2. 点击 `+` 添加 `Python` 类型配置
3. 填写以下参数：

| 字段 | 值 |
|------|-----|
| Name | `FastAPI Dev` |
| Script path | `选择项目根目录下的 main.py` |
| Working directory | `项目根目录（inland-data/）` |
| Python interpreter | `选择 .venv 中的 Python` |
| Environment variables | `见下方` |

**Environment variables（点击右侧文件夹图标）：**

```
ANTHROPIC_API_KEY=sk-ant-xxxx
DEBUG=true
DATABASE_URL=sqlite+aiosqlite:///./inland_shipping.db
SECRET_KEY=dev-secret-key
```

> 或直接勾选 `Load from .env file`，选择项目根目录的 `.env` 文件。

### 5.2 启动调试

点击 `Debug` 按钮（虫子图标）或按 `Shift+F9`。

在任何代码行设置断点，FastAPI路由被触发时将自动中断在断点处。

### 5.3 在PyCharm中调试单个异步函数

```python
# 在 PyCharm Console 中调试异步函数
import asyncio
from app.tools.entity_match_tools import EntityMatchTool

tool = EntityMatchTool()
result = asyncio.run(tool.execute(
    text="南京",
    entities=[{"id": 1, "name": "南京港", "aliases": ["南京"]}]
))
print(result)
```

---

## 6. VSCode调试配置

项目已包含 `.vscode/launch.json`（如不存在则创建）：

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "FastAPI: Debug",
            "type": "debugpy",
            "request": "launch",
            "module": "uvicorn",
            "args": [
                "main:app",
                "--reload",
                "--host", "0.0.0.0",
                "--port", "8000"
            ],
            "jinja": true,
            "justMyCode": false,
            "envFile": "${workspaceFolder}/.env"
        },
        {
            "name": "Python: Current File",
            "type": "debugpy",
            "request": "launch",
            "program": "${file}",
            "console": "integratedTerminal",
            "envFile": "${workspaceFolder}/.env"
        },
        {
            "name": "Seed Data",
            "type": "debugpy",
            "request": "launch",
            "module": "scripts.seed_data",
            "cwd": "${workspaceFolder}",
            "envFile": "${workspaceFolder}/.env"
        }
    ]
}
```

**使用方法：**
1. 按 `F5` 或点击左侧运行图标
2. 从顶部下拉选择 `FastAPI: Debug`
3. 在代码中设置断点（点击行号左侧）
4. 访问任意API接口即可触发断点

**推荐VSCode扩展：**
- `Python` (Microsoft)
- `Pylance`（类型检查）
- `REST Client`（在IDE内测试API）
- `SQLite Viewer`（查看开发数据库）

---

## 7. 数据库管理

### 7.1 Alembic迁移工作流

```bash
# 1. 修改 app/models/ 中的模型
# 2. 生成迁移文件
make migrate-create msg="add vessel_speed field"

# 3. 检查生成的迁移文件（在 alembic/versions/ 目录下）
# 4. 执行迁移
make migrate

# 5. 查看当前迁移状态
source .venv/bin/activate && alembic current

# 6. 查看迁移历史
source .venv/bin/activate && alembic history
```

### 7.2 重置开发数据库

```bash
# 删除SQLite文件
rm -f inland_shipping.db

# 重新初始化
make migrate
make seed
```

### 7.3 在PyCharm中查看SQLite

1. 打开右侧 `Database` 面板
2. 点击 `+` → `Data Source` → `SQLite`
3. 文件路径选择 `inland_shipping.db`
4. 点击 `Test Connection` 验证连接

---

## 8. API测试

### 8.1 使用Swagger UI（推荐）

访问 http://localhost:8000/docs

**登录流程：**
1. 在 `/api/v1/auth/login` 接口中输入账号密码
2. 复制返回的 `access_token`
3. 点击右上角 `Authorize` 按钮
4. 在 `Bearer` 字段输入 token
5. 之后的接口请求会自动携带认证

**测试账号：**

| 账号 | 密码 | 角色 |
|------|------|------|
| admin | Admin@2026 | SUPER_ADMIN |
| collector1 | Test@2026 | COLLECTOR |

### 8.2 使用HTTPie（命令行）

```bash
# 登录
http POST localhost:8000/api/v1/auth/login \
    username=admin password=Admin@2026

# 提交货源文本
http POST localhost:8000/api/v1/cargo/cargo/text \
    Authorization:"Bearer <token>" \
    raw_text="武汉到上海，5000吨动力煤，联系13800138000"

# 查询节点列表
http GET localhost:8000/api/v1/address/nodes \
    Authorization:"Bearer <token>"
```

### 8.3 使用VSCode REST Client

在项目根目录创建 `test.http` 文件：

```http
### 登录
POST http://localhost:8000/api/v1/auth/login
Content-Type: application/json

{
    "username": "admin",
    "password": "Admin@2026"
}

### 提交货源文本
POST http://localhost:8000/api/v1/cargo/cargo/text
Authorization: Bearer {{token}}
Content-Type: application/json

{
    "raw_text": "武汉到上海，5000吨动力煤，联系13800138000",
    "source": "测试"
}
```

---

## 9. 运行测试

### 9.1 安装测试依赖

```bash
pip install pytest pytest-asyncio httpx
```

### 9.2 运行测试

```bash
# 运行全部测试
make test

# 运行特定测试文件
pytest tests/unit/test_tools/test_entity_match_tools.py -v

# 运行特定测试函数
pytest tests/unit/test_tools/test_entity_match_tools.py::test_exact_match -v

# 显示详细输出
pytest tests/ -v --tb=short
```

### 9.3 编写新测试

**Tool单元测试示例：**

```python
# tests/unit/test_tools/test_new_tool.py
import pytest
from app.tools.geo_tools import GeoDistanceTool

@pytest.fixture
def tool():
    return GeoDistanceTool()

@pytest.mark.asyncio
async def test_distance_nanjing_wuhan(tool):
    result = await tool.execute(
        origin_lat=32.06, origin_lng=118.78,
        dest_lat=30.59, dest_lng=114.31
    )
    assert result.success
    assert 700 < result.data["distance_km"] < 800  # 南京到武汉约750km
```

**Service单元测试示例（Mock Repository）：**

```python
# tests/unit/test_services/test_cargo_service.py
import pytest
from unittest.mock import AsyncMock
from app.services.cargo_service import CargoService

@pytest.fixture
def cargo_service():
    return CargoService(
        cargo_repo=AsyncMock(),
        address_repo=AsyncMock(),
        audit_repo=AsyncMock(),
    )

@pytest.mark.asyncio
async def test_get_raw_message_not_found(cargo_service):
    cargo_service._cargo.get_raw_message.return_value = None
    from app.core.exceptions import NotFoundError
    with pytest.raises(NotFoundError):
        await cargo_service.get_raw_message(9999)
```

---

## 10. 常见问题

### Q1：启动时报 `ModuleNotFoundError`

```bash
# 确保虚拟环境已激活
source .venv/bin/activate

# 确认依赖已安装
pip list | grep fastapi
```

### Q2：启动时报 `ANTHROPIC_API_KEY not found`

```bash
# 检查 .env 文件是否存在
ls -la .env

# 检查 KEY 是否已配置
grep ANTHROPIC_API_KEY .env
```

> 如果不需要AI功能，可以将 ANTHROPIC_API_KEY 设置为任意非空字符串，AI解析会降级为空结果。

### Q3：数据库初始化失败

```bash
# 删除损坏的数据库文件
rm -f inland_shipping.db

# 重新初始化
python3 -c "import asyncio; from app.core.database import init_db; asyncio.run(init_db())"
make seed
```

### Q4：端口被占用

```bash
# 查找占用8000端口的进程
lsof -i :8000

# 杀死进程
kill -9 <PID>

# 或使用其他端口启动
uvicorn main:app --reload --port 8001
```

### Q5：Celery任务不执行

开发环境下使用APScheduler，不需要Celery。AI解析通过FastAPI的`BackgroundTask`执行。

如需测试Celery，需要启动Redis：

```bash
# macOS
brew install redis && brew services start redis

# Docker
docker run -d -p 6379:6379 redis:7

# 然后启动Worker
make celery-worker
```

### Q6：如何查看AI解析的调用日志？

```bash
# 查看实时日志（DEBUG模式下有详细AI调用记录）
uvicorn main:app --reload --log-level debug

# 日志中查找AI相关信息
# [CargoAgent] complete origin=武汉→武汉港(95) dest=上海→上海港(90)
# [LLM] model=claude-sonnet-4-6 input_tokens=234 output_tokens=156
```

---

*文档版本：V2.0 | 最后更新：2026-03-14*
