from pydantic import BaseModel
from typing import Optional, Generic, TypeVar, List

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    total: int
    items: List[T]
    page: int
    page_size: int


class ApiResponse(BaseModel, Generic[T]):
    code: int = 200
    message: str = "success"
    data: Optional[T] = None


def success(data=None, message: str = "success") -> dict:
    return {"code": 200, "message": message, "data": data}


def error(message: str = "error", code: int = 400) -> dict:
    return {"code": code, "message": message, "data": None}
