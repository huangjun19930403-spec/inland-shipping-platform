"""Optional SpiffWorkflow adapter.

The approval center owns human tasks, persistence, snapshots, logs, and outbox
delivery. SpiffWorkflow is loaded only for BPMN flows and never imported on the
default CONFIG path.
"""

from __future__ import annotations

from typing import Any

from app.core.exceptions import ValidationError


class SpiffApprovalEngine:
    def __init__(self) -> None:
        try:
            import SpiffWorkflow  # noqa: F401
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise ValidationError("SpiffWorkflow is not installed or not enabled") from exc

    def start(self, *, spec_id: str | None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not spec_id:
            raise ValidationError("BPMN approval flow requires spiff_spec_id")
        return {"spiff_spec_id": spec_id, "payload": payload or {}, "state": "STARTED"}
