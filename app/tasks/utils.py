"""Shared helpers for Celery task entrypoints."""

from __future__ import annotations

import asyncio
from threading import Thread
from typing import Any, Coroutine


async def _run_with_fresh_async_resources(coro: Coroutine[Any, Any, Any]) -> Any:
    try:
        from app.core.database import engine

        await engine.dispose(close=False)
    except Exception:
        pass
    try:
        return await coro
    finally:
        try:
            from app.core.database import engine

            await engine.dispose()
        except Exception:
            pass


def run_coro_sync(coro: Coroutine[Any, Any, Any]) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_run_with_fresh_async_resources(coro))

    result: Any = None
    error: BaseException | None = None

    def runner() -> None:
        nonlocal result, error
        try:
            result = asyncio.run(_run_with_fresh_async_resources(coro))
        except BaseException as exc:  # pragma: no cover - defensive bridge for eager mode
            error = exc

    thread = Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if error is not None:
        raise error
    return result
