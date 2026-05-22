"""Approval result outbox dispatcher."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import ApprovalOutbox

ApprovalEventHandler = Callable[[dict[str, Any], AsyncSession], Awaitable[None]]


class ApprovalServiceRegistry:
    _handlers: dict[str, ApprovalEventHandler] = {}

    @classmethod
    def register(cls, subject_type: str, handler: ApprovalEventHandler) -> None:
        cls._handlers[subject_type] = handler

    @classmethod
    def get(cls, subject_type: str) -> ApprovalEventHandler | None:
        return cls._handlers.get(subject_type)


async def dispatch_pending_outbox(db: AsyncSession, *, limit: int = 100) -> int:
    now = datetime.utcnow()
    rows = (
        await db.scalars(
            select(ApprovalOutbox)
            .where(
                ApprovalOutbox.status_code.in_(("PENDING", "FAILED")),
                (ApprovalOutbox.next_retry_at.is_(None) | (ApprovalOutbox.next_retry_at <= now)),
            )
            .order_by(ApprovalOutbox.created_at.asc(), ApprovalOutbox.id.asc())
            .limit(limit)
        )
    ).all()
    delivered = 0
    for row in rows:
        handler = ApprovalServiceRegistry.get(row.subject_type)
        if handler is None:
            row.status_code = "FAILED"
            row.retry_count += 1
            row.next_retry_at = now + timedelta(minutes=min(60, 2 ** min(row.retry_count, 6)))
            row.last_error = f"approval handler not registered for subject_type={row.subject_type}"
            continue
        try:
            await handler(row.payload_json or {}, db)
        except Exception as exc:  # pragma: no cover - handler-specific behavior
            row.status_code = "FAILED"
            row.retry_count += 1
            row.next_retry_at = now + timedelta(minutes=min(60, 2 ** min(row.retry_count, 6)))
            row.last_error = str(exc)
        else:
            row.status_code = "DELIVERED"
            row.last_error = None
            delivered += 1
    await db.commit()
    return delivered
