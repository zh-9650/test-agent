import asyncio
import importlib
import os
from unittest.mock import AsyncMock
from urllib.parse import urlparse

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text

os.environ["DATABASE_URL"] = (
    "postgresql://postgres:123456@localhost:5432/smart_test_test"
)

api_app = importlib.import_module("api.app")
from core.execution_store import (
    append_task_step,
    create_execution_run,
    finalize_execution_run,
    upsert_case_result,
)
from core.interfaces import (
    CandidateTestCase,
    CaseResult,
    ExecutionSelection,
    ExplorationGoal,
    ExplorationResult,
    GoalResult,
    PageMap,
    QualityGateReport,
    RequirementAssertion,
    RequirementFact,
    SystemMapEvid,
    TestAssetPackage as AssetPackage,
)
from database.connection import create_async_engine_instance
from database.models import Base

api_app._background_tasks_enabled = False


def _admin_urls() -> tuple[str, str]:
    parsed = urlparse(os.environ["DATABASE_URL"])
    name = parsed.path.lstrip("/")
    admin = (
        f"{parsed.scheme}://{parsed.username}:{parsed.password}"
        f"@{parsed.hostname}:{parsed.port or 5432}/postgres"
    )
    return admin, name


def setup_module():
    admin_url, db_name = _admin_urls()
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        exists = connection.execute(
            text("SELECT 1 FROM pg_database WHERE datname=:name"),
            {"name": db_name},
        ).scalar()
        if not exists:
            connection.execute(text(f'CREATE DATABASE "{db_name}"'))
    engine.dispose()

    async def prepare():
        async_engine = create_async_engine_instance(os.environ["DATABASE_URL"])
        async with async_engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
        await async_engine.dispose()

    asyncio.run(prepare())


def teardown_module():
    admin_url, db_name = _admin_urls()
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        connection.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname=:name AND pid <> pg_backend_pid()"
            ),
            {"name": db_name},
        )
        connection.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
    engine.dispose()


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=api_app.app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as value:
        yield value


async def create_task(client, suffix: str = "task") -> dict:
    response = await client.post(
        "/api/tasks",
        json={
            "target_url": f"https://example.com/{suffix}",
            "task_name": suffix,
            "config": {"rules": ["保持幂等"]},
        },
    )
    assert response.status_code == 201
    return response.json()


def result(run_id: str, case_id: str, status: str) -> CaseResult:
    return CaseResult(
        run_id=run_id,
        candidate_case_id=case_id,
        terminal_status=status,
        attempt_count=1,
        started_at="2026-06-11T00:00:00+00:00",
        completed_at="2026-06-11T00:00:01+00:00",
        summary=status,
    )


@pytest.mark.asyncio
async def test_task_contract_has_lifecycle_and_no_legacy_counts(client):
    task = await create_task(client, "contract")
    assert task["status"] == "pending"
    assert task["phase"] is None
    assert task["report_status"] == "pending"
    assert task["latest_run"] is None
    assert "total_tests" not in task
    assert "test_plan" not in task


@pytest.mark.asyncio
async def test_create_task_normalizes_wrapped_document_inputs(client):
    response = await client.post(
        "/api/tasks",
        json={
            "target_url": "https://example.com/rich-config",
            "task_name": "rich-config",
            "config": {
                "prd": {"text": "# 登录\n支持账号密码登录"},
                "changelog": {
                    "value": "## 变更\n- 调整审批规则",
                    "PSPath": "C:\\temp\\change.md",
                },
                "rules": ["保持幂等", {"value": "覆盖权限校验"}],
            },
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["config"]["prd"] == "# 登录\n支持账号密码登录"
    assert body["config"]["changelog"] == "## 变更\n- 调整审批规则"
    assert body["config"]["rules"] == ["保持幂等", "覆盖权限校验"]


@pytest.mark.asyncio
async def test_run_detail_results_and_latest_summary(client):
    task = await create_task(client, "runs")
    run = await create_execution_run(task["id"], ["PASS", "FAIL"])
    await upsert_case_result(result(run.run_id, "PASS", "passed"))
    await upsert_case_result(result(run.run_id, "FAIL", "failed"))
    await finalize_execution_run(run.run_id, "completed")

    runs_response = await client.get(f"/api/tasks/{task['id']}/runs")
    detail_response = await client.get(
        f"/api/tasks/{task['id']}/runs/{run.run_id}"
    )
    results_response = await client.get(
        f"/api/tasks/{task['id']}/runs/{run.run_id}/results"
    )
    task_response = await client.get(f"/api/tasks/{task['id']}")

    assert runs_response.status_code == 200
    assert detail_response.json()["summary"]["planned"] == 2
    assert results_response.json()["total"] == 2
    assert task_response.json()["latest_run"]["summary"]["failed"] == 1


@pytest.mark.asyncio
async def test_steps_require_run_id_and_filter_attempt(client):
    task = await create_task(client, "steps")
    run = await create_execution_run(task["id"], ["CASE-1"])
    for attempt in (1, 2):
        await append_task_step(
            task_id=task["id"],
            run_id=run.run_id,
            candidate_case_id="CASE-1",
            attempt_no=attempt,
            step_index=0,
            action={"tool": "click", "args": {"selector": "#ok"}},
            result="clicked",
        )

    missing = await client.get(f"/api/tasks/{task['id']}/steps")
    filtered = await client.get(
        f"/api/tasks/{task['id']}/steps",
        params={
            "run_id": run.run_id,
            "test_case_id": "CASE-1",
            "attempt_no": 2,
        },
    )
    assert missing.status_code == 422
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["steps"][0]["attempt_no"] == 2


@pytest.mark.asyncio
async def test_resume_has_no_body_and_selects_only_non_passed(client, monkeypatch):
    task = await create_task(client, "resume")
    run = await create_execution_run(task["id"], ["PASS", "FAIL", "SKIP"])
    await upsert_case_result(result(run.run_id, "PASS", "passed"))
    await upsert_case_result(result(run.run_id, "FAIL", "failed"))
    await upsert_case_result(result(run.run_id, "SKIP", "skipped"))
    await finalize_execution_run(run.run_id, "completed")

    captured = {}

    async def capture_runner(task_id, target_url, config, **kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(api_app, "_run_test_session", capture_runner)
    response = await client.post(f"/api/tasks/{task['id']}/resume")
    await asyncio.sleep(0)
    assert response.status_code == 200
    assert captured["resume_case_ids"] == ["FAIL", "SKIP"]
    assert captured["resumed_from_run_id"] == run.run_id


@pytest.mark.asyncio
async def test_run_must_belong_to_task(client):
    first = await create_task(client, "first")
    second = await create_task(client, "second")
    run = await create_execution_run(first["id"], ["CASE-1"])
    response = await client.get(
        f"/api/tasks/{second['id']}/runs/{run.run_id}"
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_task_not_found(client):
    response = await client.get("/api/tasks/99999999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_run_session_keeps_partial_exploration_page_evidence(
    client,
    monkeypatch,
):
    task = await create_task(client, "exploration-partial")
    facts = [
        RequirementFact(
            id="FACT-1",
            source_type="prd",
            source_reference="PRD > Dashboard",
            quote="Dashboard shows summary widgets.",
            subject="dashboard",
            action="show",
            object="summary widgets",
            confidence=0.9,
        )
    ]
    assertions = [
        RequirementAssertion(
            id="ASSERT-1",
            fact_ids=["FACT-1"],
            assertion_text="Dashboard should expose summary widgets.",
            assertion_type="functional",
            risk_level="medium",
            source_references=["FACT-1"],
        )
    ]
    goals = [
        ExplorationGoal(
            id="GOAL-1",
            goal="Inspect dashboard widgets",
            assertion_refs=["ASSERT-1"],
            expected_evidence=["summary widgets"],
            stop_condition="The dashboard widgets are observable",
            priority="medium",
        )
    ]
    exploration = ExplorationResult(
        system_map=SystemMapEvid(
            pages=[
                PageMap(
                    name="Dashboard",
                    url_pattern="https://example.com/exploration-partial",
                    title="Dashboard",
                    elements=["Overview", "Widget summary"],
                    discovered_actions=["button:Refresh"],
                )
            ]
        ),
        goal_results=[
            GoalResult(
                goal_id="GOAL-1",
                status="insufficient",
                stop_reason="Need more proof for the assertion",
                observed_at="2026-06-16T00:00:00+00:00",
            )
        ],
    )
    captured: dict[str, object] = {}

    class FakeRuntimeSession:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def explore(self, incoming_goals):
            assert incoming_goals == goals
            return exploration

        async def execute(self, run_id, _cases):
            await upsert_case_result(result(run_id, "TC-1", "skipped"))
            return None

    async def fake_run_l2_pipeline(**kwargs):
        captured["system_map"] = kwargs.get("system_map")
        return AssetPackage(
            facts=facts,
            assertions=assertions,
            exploration_goals=goals,
            system_map=kwargs.get("system_map"),
            candidate_cases=[
                CandidateTestCase(
                    id="TC-1",
                    title="Dashboard widget smoke",
                    goal="Verify dashboard widget shell",
                    expected_result="The dashboard widget shell is visible.",
                    trace_references=["COV-1"],
                )
            ],
        )

    monkeypatch.setattr(
        "core.document_parser.parse_and_fetch_links",
        AsyncMock(return_value=task["config"]),
    )
    monkeypatch.setattr(
        "core.skills.l2_pipeline.generate_exploration_goals",
        AsyncMock(return_value=(goals, [], facts, assertions)),
    )
    monkeypatch.setattr(
        "core.skills.l2_pipeline.run_l2_pipeline",
        fake_run_l2_pipeline,
    )
    monkeypatch.setattr(
        "core.runtime_session.RuntimeSession",
        FakeRuntimeSession,
    )
    monkeypatch.setattr(
        "core.skills.execution_selector.select_execution_cases",
        lambda package, profile, target_count: ExecutionSelection(
            profile=profile,
            target_count=target_count,
            mandatory_count=1,
            selected_count=1,
            deferred_count=0,
            selected_case_ids=["TC-1"],
        ),
    )
    monkeypatch.setattr(
        "core.skills.case_adapter.adapt_executable_cases",
        lambda candidates: candidates,
    )
    monkeypatch.setattr(
        "core.skills.quality_gates.run_quality_gates",
        lambda _package: QualityGateReport(passed=True),
    )
    monkeypatch.setattr(
        "core.run_report.build_run_report",
        lambda *_args, **_kwargs: "<html></html>",
    )
    monkeypatch.setattr(
        "core.run_report.save_run_report",
        lambda run_id, _html: f"data/reports/report_{run_id}.html",
    )
    monkeypatch.setattr(
        api_app.websocket_manager,
        "send_message",
        AsyncMock(return_value=None),
    )

    await api_app._run_test_session(
        task["id"],
        task["target_url"],
        task["config"],
    )

    response = await client.get(f"/api/tasks/{task['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["report_status"] == "completed"
    assert body["failure_reason"] is None
    assert len(body["analysis_package"]["system_map"]["pages"]) == 1
    assert (
        body["analysis_package"]["system_map"]["pages"][0]["title"]
        == "Dashboard"
    )
    exploration_evidence = body["analysis_package"]["exploration_evidence"]
    assert exploration_evidence["summary"] == {
        "total": 1,
        "found": 0,
        "not_found": 0,
        "blocked": 0,
        "insufficient": 1,
        "pages": 1,
        "actions": 0,
        "forms": 0,
        "navigations": 0,
        "evidence_ref_count": 0,
    }
    assert exploration_evidence["goal_results"][0]["goal_id"] == "GOAL-1"
    assert exploration_evidence["goal_results"][0]["status"] == "insufficient"
    assert isinstance(captured["system_map"], SystemMapEvid)
    assert captured["system_map"].pages[0].title == "Dashboard"
