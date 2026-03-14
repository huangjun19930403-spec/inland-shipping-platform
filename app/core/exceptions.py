"""
统一异常体系
所有业务异常必须继承自此模块定义的基类
"""
from typing import Any, Optional


class AppException(Exception):
    """应用基础异常"""

    def __init__(
        self,
        message: str,
        code: str = "500000",
        status_code: int = 500,
        detail: Optional[Any] = None,
    ) -> None:
        self.message = message
        self.code = code
        self.status_code = status_code
        self.detail = detail
        super().__init__(message)


# ─────────────────────────────────────────────────
# 4xx Client Errors
# ─────────────────────────────────────────────────

class NotFoundError(AppException):
    """资源不存在 — 404"""

    def __init__(self, resource: str, identifier: Any = None) -> None:
        msg = f"{resource} not found"
        if identifier is not None:
            msg = f"{resource} '{identifier}' not found"
        super().__init__(message=msg, code="404000", status_code=404)


class ValidationError(AppException):
    """业务校验失败 — 422"""

    def __init__(self, message: str, detail: Optional[Any] = None) -> None:
        super().__init__(
            message=message, code="422000", status_code=422, detail=detail
        )


class ConflictError(AppException):
    """资源冲突 — 409"""

    def __init__(self, message: str) -> None:
        super().__init__(message=message, code="409000", status_code=409)


class AuthenticationError(AppException):
    """认证失败 — 401"""

    def __init__(self, message: str = "Authentication required") -> None:
        super().__init__(message=message, code="401000", status_code=401)


class PermissionError(AppException):
    """权限不足 — 403"""

    def __init__(self, message: str = "Insufficient permissions") -> None:
        super().__init__(message=message, code="403000", status_code=403)


class BadRequestError(AppException):
    """请求参数错误 — 400"""

    def __init__(self, message: str) -> None:
        super().__init__(message=message, code="400000", status_code=400)


# ─────────────────────────────────────────────────
# 5xx Server Errors
# ─────────────────────────────────────────────────

class InternalError(AppException):
    """内部服务器错误 — 500"""

    def __init__(self, message: str = "Internal server error") -> None:
        super().__init__(message=message, code="500000", status_code=500)


class AIServiceError(AppException):
    """AI服务异常 — 503"""

    def __init__(self, message: str = "AI service unavailable") -> None:
        super().__init__(message=message, code="503001", status_code=503)


class DatabaseError(AppException):
    """数据库异常 — 500"""

    def __init__(self, message: str = "Database operation failed") -> None:
        super().__init__(message=message, code="500001", status_code=500)


class TaskError(AppException):
    """异步任务异常"""

    def __init__(self, message: str) -> None:
        super().__init__(message=message, code="500002", status_code=500)
