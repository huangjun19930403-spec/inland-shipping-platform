"""应用异常基类与通用业务异常。"""

from __future__ import annotations

from typing import Any


class AppException(Exception):
    """应用基础异常。"""

    def __init__(self, message: str, code: str = "500000", status_code: int = 500, detail: Any = None) -> None:
        self.message = message
        self.code = code
        self.status_code = status_code
        self.detail = detail
        super().__init__(message)


class NotFoundError(AppException):
    def __init__(self, resource: str, identifier: Any = None) -> None:
        msg = f"{resource} not found" if identifier is None else f"{resource} '{identifier}' not found"
        super().__init__(message=msg, code="404000", status_code=404)


class ValidationError(AppException):
    def __init__(self, message: str, detail: Any = None, code: str = "422000") -> None:
        super().__init__(message=message, code=code, status_code=422, detail=detail)


class ConflictError(AppException):
    def __init__(self, message: str, code: str = "409000", detail: Any = None) -> None:
        super().__init__(message=message, code=code, status_code=409, detail=detail)


class AuthenticationError(AppException):
    def __init__(self, message: str = "Authentication required") -> None:
        super().__init__(message=message, code="401000", status_code=401)


class PermissionError(AppException):
    def __init__(self, message: str = "Insufficient permissions") -> None:
        super().__init__(message=message, code="403000", status_code=403)


class BadRequestError(AppException):
    def __init__(self, message: str) -> None:
        super().__init__(message=message, code="400000", status_code=400)


class InternalError(AppException):
    def __init__(self, message: str = "Internal server error") -> None:
        super().__init__(message=message, code="500000", status_code=500)


class DatabaseError(AppException):
    def __init__(self, message: str = "Database operation failed") -> None:
        super().__init__(message=message, code="500001", status_code=500)
