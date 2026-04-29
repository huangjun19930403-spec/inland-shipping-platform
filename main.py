"""非 AI 模块化单体后端入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import api_router
from app.core.config import settings
from app.core.exceptions import AppException
from app.core.logging import get_logger, setup_logging
from app.integrations.http import close_shared_http_clients

setup_logging()
logger = get_logger("backend.main")


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("backend starting")
    yield
    await close_shared_http_clients()
    logger.info("backend stopped")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Non-AI modular monolith backend baseline",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id.strip():
        return request_id.strip()
    header_request_id = request.headers.get("X-Request-ID")
    if header_request_id and header_request_id.strip():
        return header_request_id.strip()
    return uuid.uuid4().hex


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    request_id = _get_request_id(request)
    logger.warning(
        "app exception: code=%s status=%s request_id=%s path=%s method=%s message=%s",
        exc.code,
        exc.status_code,
        request_id,
        request.url.path,
        request.method,
        exc.message,
    )
    response = JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.code,
            "message": exc.message,
            "data": exc.detail,
            "request_id": request_id,
        },
    )
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = _get_request_id(request)
    logger.warning(
        "request validation failed: request_id=%s method=%s path=%s errors=%s",
        request_id,
        request.method,
        request.url.path,
        exc.errors(),
    )
    response = JSONResponse(
        status_code=422,
        content={
            "code": "422000",
            "message": "request validation failed",
            "data": exc.errors(),
            "request_id": request_id,
        },
    )
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = _get_request_id(request)
    client_ip = request.client.host if request.client else None
    logger.exception(
        "unhandled exception: request_id=%s method=%s path=%s client_ip=%s",
        request_id,
        request.method,
        request.url.path,
        client_ip,
    )
    data = None
    if settings.DEBUG:
        data = {
            "exception_type": exc.__class__.__name__,
            "exception_message": str(exc),
        }
    response = JSONResponse(
        status_code=500,
        content={
            "code": "500000",
            "message": "internal server error",
            "data": data,
            "request_id": request_id,
        },
    )
    response.headers["X-Request-ID"] = request_id
    return response


app.include_router(api_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {"name": settings.APP_NAME, "version": settings.APP_VERSION, "status": "running"}


@app.get("/health")
async def health():
    return {"status": "ok"}
