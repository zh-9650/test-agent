"""api/schemas.py — Pydantic request/response schemas for FastAPI routes.

Defines input validation and output serialization models for the REST API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class CreateTaskRequest(BaseModel):
    """Request body for creating a new test task."""

    target_url: str = Field(..., description="Target URL to test")
    task_name: str = Field(default="", description="Task name")
    config: dict[str, Any] = Field(default_factory=dict, description="Test config: accounts, rules, focus_areas")


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
    config: Optional[dict] = None
    test_plan: Optional[list] = None
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
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
    test_case_id: str
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


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str
    task_id: Optional[str] = None
