from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import BigInteger

import app.models  # noqa: F401
from app.models.analysis import AnalysisJobDefinition, AnalysisJobRun
from app.models.base import Base
from app.tasks.celery_app import celery_app


@compiles(BigInteger, "sqlite")
def _compile_bigint_sqlite(element, compiler, **kw) -> str:
    _ = element, compiler, kw
    return "INTEGER"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


def test_celery_registry_contains_route_and_production_precompute_tasks() -> None:
    celery_app.loader.import_default_modules()
    registered = set(celery_app.tasks.keys())

    assert "route.generate_track_version" in registered
    assert "vessel.precompute_production_candidate_analyses" in registered
    assert "analysis.run_job" in registered
    assert "freight.parse_wechat_batch" in registered
    assert "vessel.recognize_certificate_image" in registered


def test_freight_ai_tracked_runner_uses_one_async_bridge(monkeypatch) -> None:
    from app.tasks import freight_ai_tasks

    events: list[object] = []
    run_calls = 0

    def run_once(coro):
        nonlocal run_calls
        run_calls += 1
        return asyncio.run(coro)

    async def track_start(task_run_id, celery_task_id, stage_name):  # noqa: ANN001
        events.append(("start", task_run_id, celery_task_id, stage_name))

    async def track_success(task_run_id, result):  # noqa: ANN001
        events.append(("success", task_run_id, result))

    async def track_failure(task_run_id, exc):  # noqa: ANN001
        events.append(("failure", task_run_id, str(exc)))

    async def business():
        events.append("business")
        return {"ok": True}

    monkeypatch.setattr(freight_ai_tasks, "run_coro_sync", run_once)
    monkeypatch.setattr(freight_ai_tasks, "_track_task_start", track_start)
    monkeypatch.setattr(freight_ai_tasks, "_track_task_success", track_success)
    monkeypatch.setattr(freight_ai_tasks, "_track_task_failure", track_failure)

    result = freight_ai_tasks._run_tracked("celery-1", 7, "微信货源解析中", business())

    assert result == {"ok": True}
    assert run_calls == 1
    assert events == [
        ("start", 7, "celery-1", "微信货源解析中"),
        "business",
        ("success", 7, {"ok": True}),
    ]


def test_analysis_run_job_uses_shared_async_bridge(monkeypatch) -> None:
    from app.tasks import analysis_tasks

    calls: list[tuple[str, str | None, str | None, bool, dict | None]] = []
    run_calls = 0

    async def fake_runner(job_code, date_from, date_to, force_rebuild, options):  # noqa: ANN001
        calls.append((job_code, date_from, date_to, force_rebuild, options))
        return {"job_code": job_code, "ok": True}

    def run_once(coro):
        nonlocal run_calls
        run_calls += 1
        return asyncio.run(coro)

    monkeypatch.setattr(analysis_tasks, "_run_analysis_job", fake_runner)
    monkeypatch.setattr(analysis_tasks, "run_coro_sync", run_once)

    result = analysis_tasks.run_analysis_job("ANALYSIS_FREIGHT_DAILY", "2026-01-01", "2026-01-02", False, {"k": "v"})

    assert result == {"job_code": "ANALYSIS_FREIGHT_DAILY", "ok": True}
    assert run_calls == 1
    assert calls == [("ANALYSIS_FREIGHT_DAILY", "2026-01-01", "2026-01-02", False, {"k": "v"})]


@pytest.mark.asyncio
async def test_analysis_job_detail_marks_celery_failed_runs(session, monkeypatch) -> None:
    from app.modules.analysis.job_views import AnalysisJobViewMixin

    now = datetime.now(UTC).replace(tzinfo=None)
    definition = AnalysisJobDefinition(
        job_code="ANALYSIS_FAKE",
        job_name="fake",
        module_code="SYSTEM",
        module_name="系统",
        enabled=True,
        created_at=now,
        updated_at=now,
    )
    run = AnalysisJobRun(
        job_code="ANALYSIS_FAKE",
        job_name="fake",
        module_code="SYSTEM",
        module_name="系统",
        stat_date_from=date(2026, 1, 1),
        stat_date_to=date(2026, 1, 2),
        status_code="QUEUED",
        status_name="排队中",
        celery_task_id="celery-failed-1",
        queued_at=now,
        created_at=now,
    )
    session.add_all([definition, run])
    await session.commit()
    await session.refresh(run)

    class FakeAsyncResult:
        def __init__(self, task_id, app=None):  # noqa: ANN001
            self.task_id = task_id
            self.app = app
            self.state = "FAILURE"
            self.info = "analysis worker failed"

    monkeypatch.setattr("app.modules.analysis.job_views.AsyncResult", FakeAsyncResult)

    class DummyService(AnalysisJobViewMixin):
        def __init__(self, db):
            self.db = db

    detail = await DummyService(session).get_job_detail(run.id)
    await session.refresh(run)
    await session.refresh(definition)

    assert detail.status_code == "FAILED"
    assert run.status_code == "FAILED"
    assert run.error_message == "analysis worker failed"
    assert definition.last_run_id == run.id
    assert definition.last_status_code == "FAILED"
