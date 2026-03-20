"""
中国内河航运数据采集与分析平台 — 应用主入口
AI Native Architecture · V2.0

架构分层：
  API Layer → Service Layer → Repository Layer → Domain Model
  AI Layer: Agent → Tool → Workflow（独立于业务层）

启动方式:
    uvicorn main:app --reload --host 0.0.0.0 --port 8000

文档地址:
    http://localhost:8000/docs
    http://localhost:8000/redoc
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging import setup_logging, get_logger
from app.core.exceptions import AppException
from app.api.v1 import api_router

# 初始化日志（必须在其他模块导入前）
setup_logging()
logger = get_logger("inland.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("=== 内河航运平台 V2.0 启动中 ===")

    # 数据库结构统一由 Alembic 迁移维护，不在应用启动时 create_all
    logger.info("数据库初始化策略：Alembic（请先执行 alembic upgrade head）")

    # 首次启动种子数据（从独立脚本调用）
    # 生产环境：通过 `python -m scripts.seed_data` 手动执行
    # 开发环境：自动执行
    if settings.DEBUG:
        from scripts.seed_data import seed_all
        await seed_all()
        logger.info("开发环境种子数据初始化完成")

    # 开发环境使用APScheduler（生产环境使用Celery Beat）
    if settings.DEBUG:
        from app.tasks.scheduler import setup_scheduler, shutdown_scheduler
        setup_scheduler()
        logger.info("APScheduler调度器已启动（开发模式）")

    logger.info("=== 平台启动完成，开始接受请求 ===")
    yield

    if settings.DEBUG:
        from app.tasks.scheduler import shutdown_scheduler
        shutdown_scheduler()
    logger.info("=== 内河航运平台已停止 ===")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
## 中国内河航运数据采集与分析平台 API V2.0

### AI Native Architecture
- **AI Agent驱动**：CargoAgent / AnalysisAgent
- **标准化Tool体系**：cargo_parse / entity_match / geo_distance
- **Workflow编排**：cargo_parse_workflow / cargo_match_workflow
- **Clean Architecture**：API → Service → Repository → Domain Model

### 用户角色
| 角色 | 代码 | 权限 |
|------|------|------|
| 超级管理员 | SUPER_ADMIN | 全部权限，可自审 |
| 管理员 | ADMIN | 审核权限 + 数据管理 |
| 运营人员 | OPERATOR | 数据录入 + 部分管理 |
| 数据采集员 | COLLECTOR | 货源采集 + 数据查看 |
    """,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ─────────────────────────────────────────────────
# 中间件
# ─────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────
# 全局异常处理
# ─────────────────────────────────────────────────

@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    """统一处理所有业务异常，返回标准格式"""
    logger.warning(
        f"AppException: {exc.code} {exc.message} "
        f"[{request.method} {request.url.path}]"
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.code,
            "message": exc.message,
            "data": exc.detail,
        },
    )

# ─────────────────────────────────────────────────
# 路由注册
# ─────────────────────────────────────────────────

app.include_router(api_router, prefix="/api/v1")

# ─────────────────────────────────────────────────
# 基础端点
# ─────────────────────────────────────────────────

@app.get("/", tags=["系统"])
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "architecture": "AI Native Clean Architecture V2.0",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health", tags=["系统"])
async def health():
    return {"status": "ok", "version": settings.APP_VERSION}


# ─────────────────────────────────────────────────
# IDE调试入口
# ─────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
    )
