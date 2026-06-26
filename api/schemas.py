"""api/schemas.py — Pydantic request/response schemas for FastAPI routes.

Defines input validation and output serialization models for the REST API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from core.input_normalization import normalize_task_config


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class CreateTaskRequest(BaseModel):
    """Request body for creating a new test task."""

    target_url: str = Field(..., description="Target URL to test")
    task_name: str = Field(default="", description="Task name")
    config: dict[str, Any] = Field(default_factory=dict, description="Test config: accounts, rules, focus_areas")

    def model_post_init(self, __context: Any) -> None:
        self.config = normalize_task_config(self.config)
        profile = self.config.get("execution_profile", "balanced")
        if profile not in {"smoke", "balanced", "full"}:
            raise ValueError("execution_profile must be smoke, balanced, or full")
        target = self.config.get("execution_target")
        if target is not None and (not isinstance(target, int) or target <= 0):
            raise ValueError("execution_target must be a positive integer")
        self.config["execution_profile"] = profile


class AccountConfig(BaseModel):
    """Account configuration for test tasks."""

    role: str = ""
    username: str = ""
    password: str = ""


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class TaskResponse(BaseModel):
    """Response model for a single task."""

    id: int
    task_name: str
    target_url: str
    status: str
    phase: Optional[str] = None
    report_status: str = "pending"
    failure_reason: Optional[str] = None
    config: Optional[dict] = None
    analysis_package: Optional[dict] = None
    latest_run: Optional[dict] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskListResponse(BaseModel):
    """Response model for a paginated list of tasks."""

    tasks: list[TaskResponse]
    total: int


class StepResponse(BaseModel):
    """Response model for a single task step."""

    id: int
    run_id: str
    test_case_id: str
    attempt_no: int
    step_index: int
    action_type: str
    action_target: str
    action_args: Optional[dict] = None
    result: str
    screenshot_path: str
    change_report: Optional[dict] = None
    assertion_result: Optional[dict] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class StepListResponse(BaseModel):
    """Response model for a list of task steps."""

    steps: list[StepResponse]
    total: int


class ExecutionRunResponse(BaseModel):
    run_id: str
    task_id: int
    schema_version: str
    status: str
    candidate_case_ids: list[str]
    resumed_from_run_id: Optional[str] = None
    summary: dict[str, Any]
    started_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ExecutionRunListResponse(BaseModel):
    runs: list[ExecutionRunResponse]
    total: int


class CaseResultResponse(BaseModel):
    candidate_case_id: str
    terminal_status: str
    attempt_count: int
    summary: str
    evidence_refs: list[str]
    failure_reason: Optional[str] = None
    started_at: datetime
    completed_at: datetime

    model_config = {"from_attributes": True}


class CaseResultListResponse(BaseModel):
    results: list[CaseResultResponse]
    total: int


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str
    task_id: Optional[str] = None


class AgentMemoryItem(BaseModel):
    id: Optional[int] = None
    scope_type: str = Field(..., description="'global' or 'domain'")
    scope_value: str = Field(..., description="'*' or domain URL")
    memory_key: str
    memory_value: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class MemoryListResponse(BaseModel):
    memories: list[AgentMemoryItem]
    total: int
