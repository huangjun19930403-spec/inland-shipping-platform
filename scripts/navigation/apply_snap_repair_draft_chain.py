"""Apply SNAP_REPAIR geometry drafts through the workbench publish/build flow."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

import app.models  # noqa: F401
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.exceptions import AppException
from app.models import NavigationGeometryDraft, NavigationGraphVersion
from app.modules.navigation.schemas import (
    NavigationGeometryDraftValidateRequest,
    NavigationGraphBuildRequest,
)
from app.modules.navigation.workbench_service import NavigationWorkbenchService


OUTPUT_PATH = Path("runtime/navigation-production/reports/snap_repair_draft_chain_report.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate, publish, and rebuild graph for a SNAP_REPAIR boundary/centerline draft pair."
    )
    parser.add_argument("--centerline-draft-id", type=int, required=True)
    parser.add_argument("--boundary-draft-id", type=int, required=True)
    parser.add_argument("--publish-boundary", action="store_true")
    parser.add_argument("--publish-centerline", action="store_true")
    parser.add_argument("--build-graph", action="store_true")
    parser.add_argument("--activate-graph", action="store_true")
    parser.add_argument("--created-by", type=int, default=None)
    parser.add_argument("--scope-code", default="REAL-JS-YRD")
    parser.add_argument("--channel-code", action="append", dest="channel_codes")
    parser.add_argument("--version-code", default=None)
    parser.add_argument("--version-name", default=None)
    parser.add_argument("--allow-coverage-regression", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    report = _base_report(args)
    async with AsyncSessionLocal() as session:
        service = NavigationWorkbenchService(session)
        try:
            await _apply_chain(session=session, service=service, args=args, report=report)
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            _record_error(report, "chain", exc)
    _finalize_report(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report_path={args.output}")
    print(json.dumps(report["summary"], ensure_ascii=False))


async def _apply_chain(
    *,
    session,
    service: NavigationWorkbenchService,
    args: argparse.Namespace,
    report: dict[str, Any],
) -> None:
    boundary_draft = await _load_draft(session, args.boundary_draft_id)
    centerline_draft = await _load_draft(session, args.centerline_draft_id)
    report["drafts"]["boundary_before"] = _draft_snapshot(boundary_draft)
    report["drafts"]["centerline_before"] = _draft_snapshot(centerline_draft)
    report["graph"]["active_before"] = await _active_graph_snapshot(session)
    if boundary_draft.draft_type_code != "BOUNDARY":
        raise ValueError(f"boundary draft {boundary_draft.id} is {boundary_draft.draft_type_code}, expected BOUNDARY")
    if centerline_draft.draft_type_code != "CENTERLINE":
        raise ValueError(
            f"centerline draft {centerline_draft.id} is {centerline_draft.draft_type_code}, expected CENTERLINE"
        )
    if boundary_draft.channel_id != centerline_draft.channel_id:
        raise ValueError(
            f"draft channel mismatch: boundary={boundary_draft.channel_id}, centerline={centerline_draft.channel_id}"
        )

    boundary_validation = await _run_step(
        report,
        "validate_boundary",
        lambda: _validate_draft(service, boundary_draft),
    )
    if not _publishable(boundary_validation):
        report["summary"]["status"] = "NEED_REVIEW"
        return

    if args.publish_boundary:
        boundary_publish = await _run_step(
            report,
            "publish_boundary",
            lambda: _publish_or_existing(session, service, boundary_draft.id, args.created_by),
        )
        if boundary_publish is None:
            report["summary"]["status"] = "NEED_REVIEW"
            return
    else:
        _record_dry_run(report, "publish_boundary", "pass --publish-boundary to publish this boundary draft")

    centerline_draft = await _load_draft(session, args.centerline_draft_id)
    centerline_validation = await _run_step(
        report,
        "validate_centerline_after_boundary",
        lambda: _validate_draft(service, centerline_draft),
    )
    if not _publishable(centerline_validation):
        report["summary"]["status"] = "NEED_REVIEW"
        return

    if args.publish_centerline:
        centerline_publish = await _run_step(
            report,
            "publish_centerline",
            lambda: _publish_or_existing(session, service, centerline_draft.id, args.created_by),
        )
        if centerline_publish is None:
            report["summary"]["status"] = "NEED_REVIEW"
            return
    else:
        _record_dry_run(report, "publish_centerline", "pass --publish-centerline to publish this centerline draft")

    boundary_draft = await _load_draft(session, args.boundary_draft_id)
    centerline_draft = await _load_draft(session, args.centerline_draft_id)
    report["drafts"]["boundary_after"] = _draft_snapshot(boundary_draft)
    report["drafts"]["centerline_after"] = _draft_snapshot(centerline_draft)

    if args.build_graph:
        if centerline_draft.status_code != "PUBLISHED":
            _record_need_review(
                report,
                "build_graph",
                f"centerline draft {centerline_draft.id} is {centerline_draft.status_code}, expected PUBLISHED",
            )
            return
        graph_build = await _run_step(report, "build_graph", lambda: _build_graph(service, args))
        if graph_build is None:
            report["summary"]["status"] = "NEED_REVIEW"
            return
        report["graph"]["build"] = graph_build
        built_graph = await session.get(NavigationGraphVersion, int(graph_build["graph_version_id"]))
        report["graph"]["built_graph"] = _graph_snapshot(built_graph)
        if args.activate_graph:
            if graph_build.get("status_code") != "READY":
                _record_need_review(
                    report,
                    "activate_graph",
                    f"graph {graph_build.get('graph_version_id')} is {graph_build.get('status_code')}, expected READY",
                )
                return
            guard = _activation_guard(
                active_before=report["graph"].get("active_before"),
                built_graph=report["graph"].get("built_graph"),
                allow_coverage_regression=bool(args.allow_coverage_regression),
            )
            report["graph"]["activation_guard"] = guard
            if not guard["can_activate"]:
                _record_need_review(report, "activate_graph_coverage_guard", guard["message"])
                return
            graph_version_id = int(graph_build["graph_version_id"])
            activate = await _run_step(report, "activate_graph", lambda: _activate_graph(service, graph_version_id))
            if activate is None:
                report["summary"]["status"] = "NEED_REVIEW"
                return
            report["graph"]["activate"] = activate
    else:
        _record_dry_run(report, "build_graph", "pass --build-graph to rebuild from current published centerlines")


async def _load_draft(session, draft_id: int) -> NavigationGeometryDraft:
    draft = await session.get(NavigationGeometryDraft, draft_id)
    if draft is None:
        raise ValueError(f"NavigationGeometryDraft {draft_id} not found")
    return draft


async def _validate_draft(
    service: NavigationWorkbenchService,
    draft: NavigationGeometryDraft,
) -> dict[str, Any]:
    validation = await service.validate_geometry_draft(
        NavigationGeometryDraftValidateRequest(
            draft_type_code=draft.draft_type_code,
            channel_id=draft.channel_id,
            geometry_json=draft.geometry_json,
        )
    )
    return _compact_validation_payload(validation.model_dump(mode="json"))


async def _publish_draft(
    service: NavigationWorkbenchService,
    draft_id: int,
    published_by: int | None,
) -> dict[str, Any]:
    draft = await service.publish_geometry_draft(draft_id, published_by=published_by)
    return draft.model_dump(mode="json")


async def _publish_or_existing(
    session,
    service: NavigationWorkbenchService,
    draft_id: int,
    published_by: int | None,
) -> dict[str, Any]:
    draft = await _load_draft(session, draft_id)
    if draft.status_code == "PUBLISHED":
        return {"already_published": True, "draft": _draft_snapshot(draft)}
    return await _publish_draft(service, draft_id, published_by)


async def _build_graph(service: NavigationWorkbenchService, args: argparse.Namespace) -> dict[str, Any]:
    version_code = args.version_code or _default_version_code(args.scope_code, args.centerline_draft_id)
    response = await service.build_graph_version(
        NavigationGraphBuildRequest(
            version_code=version_code,
            version_name=args.version_name or version_code,
            scope_code=args.scope_code,
            channel_codes=args.channel_codes,
            activate=False,
        ),
        created_by=args.created_by,
    )
    return response.model_dump(mode="json")


async def _activate_graph(service: NavigationWorkbenchService, graph_version_id: int) -> dict[str, Any]:
    response = await service.activate_graph_version(graph_version_id)
    return response.model_dump(mode="json")


async def _run_step(
    report: dict[str, Any],
    step: str,
    fn: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any] | None:
    try:
        payload = await fn()
    except Exception as exc:  # noqa: BLE001
        _record_error(report, step, exc)
        return None
    report["steps"].append({"step": step, "status": "OK", "payload": payload})
    return payload


def _record_dry_run(report: dict[str, Any], step: str, message: str) -> None:
    report["steps"].append({"step": step, "status": "DRY_RUN", "message": message})


def _record_need_review(report: dict[str, Any], step: str, message: str) -> None:
    report["steps"].append({"step": step, "status": "NEED_REVIEW", "message": message})
    report["summary"]["status"] = "NEED_REVIEW"


def _record_error(report: dict[str, Any], step: str, exc: Exception) -> None:
    payload: dict[str, Any] = {
        "step": step,
        "status": "ERROR",
        "error_code": exc.__class__.__name__,
        "error_message": str(exc),
    }
    if isinstance(exc, AppException):
        payload["app_code"] = exc.code
        payload["detail"] = _jsonable(exc.detail)
    report["steps"].append(payload)
    report["summary"]["status"] = "ERROR"


def _publishable(validation: dict[str, Any] | None) -> bool:
    return bool(validation and validation.get("publishable") is True)


def _compact_validation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compacted = dict(payload)
    issues = []
    for issue in list(payload.get("issues") or []):
        item = dict(issue)
        if item.get("geometry_json") is not None:
            item["geometry_json"] = _geometry_summary(item["geometry_json"])
        issues.append(item)
    compacted["issues"] = issues
    return compacted


def _geometry_summary(geometry_json: Any) -> dict[str, Any]:
    if not isinstance(geometry_json, dict):
        return {"omitted": True, "reason": "non_dict_geometry"}
    coordinates = geometry_json.get("coordinates")
    return {
        "type": geometry_json.get("type"),
        "coordinate_group_count": len(coordinates) if isinstance(coordinates, list) else None,
        "omitted": True,
    }


def _draft_snapshot(draft: NavigationGeometryDraft) -> dict[str, Any]:
    validation_summary = None
    if isinstance(draft.source_trace_json, dict):
        validation_summary = draft.source_trace_json.get("validation_summary")
    return {
        "id": draft.id,
        "draft_no": draft.draft_no,
        "draft_type_code": draft.draft_type_code,
        "channel_id": draft.channel_id,
        "target_type_code": draft.target_type_code,
        "target_id": draft.target_id,
        "source_type_code": draft.source_type_code,
        "status_code": draft.status_code,
        "quality_code": draft.quality_code,
        "review_comment": draft.review_comment,
        "publish_target_type_code": draft.publish_target_type_code,
        "publish_target_id": draft.publish_target_id,
        "validation_summary": validation_summary,
    }


async def _active_graph_snapshot(session) -> dict[str, Any] | None:
    graph = (
        await session.execute(
            select(NavigationGraphVersion)
            .where(
                NavigationGraphVersion.is_active.is_(True),
                NavigationGraphVersion.status_code == "READY",
                NavigationGraphVersion.scope_code.not_like("MVP%"),
                NavigationGraphVersion.edge_count > 0,
            )
            .order_by(NavigationGraphVersion.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return _graph_snapshot(graph)


def _graph_snapshot(graph: NavigationGraphVersion | None) -> dict[str, Any] | None:
    if graph is None:
        return None
    return {
        "id": graph.id,
        "version_code": graph.version_code,
        "scope_code": graph.scope_code,
        "status_code": graph.status_code,
        "is_active": bool(graph.is_active),
        "node_count": int(graph.node_count or 0),
        "edge_count": int(graph.edge_count or 0),
        "channel_count": int(graph.channel_count or 0),
        "quality_score": graph.quality_score,
    }


def _activation_guard(
    *,
    active_before: dict[str, Any] | None,
    built_graph: dict[str, Any] | None,
    allow_coverage_regression: bool,
) -> dict[str, Any]:
    if allow_coverage_regression or not active_before or not built_graph:
        return {"can_activate": True, "message": "coverage regression guard bypassed or no prior active graph"}
    blockers: list[str] = []
    if active_before.get("scope_code") != built_graph.get("scope_code"):
        blockers.append("SCOPE_MISMATCH_WOULD_CREATE_COMPETING_ACTIVE_GRAPH")
    if int(built_graph.get("edge_count") or 0) < int(active_before.get("edge_count") or 0):
        blockers.append("EDGE_COUNT_REGRESSION")
    if int(built_graph.get("node_count") or 0) < int(active_before.get("node_count") or 0):
        blockers.append("NODE_COUNT_REGRESSION")
    if not blockers:
        return {"can_activate": True, "message": "coverage guard passed", "blockers": []}
    return {
        "can_activate": False,
        "blockers": blockers,
        "message": (
            "activation blocked because the new graph would reduce or shadow current production coverage: "
            f"active_before={active_before}, built_graph={built_graph}"
        ),
    }


def _base_report(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "report_version": "SNAP_REPAIR_DRAFT_CHAIN_V1",
        "generated_at": datetime.now(UTC).isoformat(),
        "args": {
            "centerline_draft_id": args.centerline_draft_id,
            "boundary_draft_id": args.boundary_draft_id,
            "publish_boundary": bool(args.publish_boundary),
            "publish_centerline": bool(args.publish_centerline),
            "build_graph": bool(args.build_graph),
            "activate_graph": bool(args.activate_graph),
            "scope_code": args.scope_code,
            "channel_codes": args.channel_codes,
            "version_code": args.version_code,
            "version_name": args.version_name,
            "allow_coverage_regression": bool(args.allow_coverage_regression),
        },
        "summary": {"status": "DRY_RUN"},
        "drafts": {},
        "graph": {},
        "steps": [],
    }


def _finalize_report(report: dict[str, Any]) -> None:
    if report["summary"].get("status") not in {"ERROR", "NEED_REVIEW"}:
        report["summary"]["status"] = "APPLIED" if _has_mutating_step(report) else "DRY_RUN"
    report["summary"]["step_counts"] = {
        status: sum(1 for step in report["steps"] if step.get("status") == status)
        for status in sorted({str(step.get("status")) for step in report["steps"]})
    }


def _has_mutating_step(report: dict[str, Any]) -> bool:
    mutating_steps = {"publish_boundary", "publish_centerline", "build_graph", "activate_graph"}
    return any(step.get("step") in mutating_steps and step.get("status") == "OK" for step in report["steps"])


def _default_version_code(scope_code: str, centerline_draft_id: int) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"{scope_code.upper()}-SNAP-REPAIR-CL{centerline_draft_id}-{stamp}"


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return str(value)


if __name__ == "__main__":
    asyncio.run(main())
