"""
database/models.py — SQLAlchemy ORM models for task, task_step, and report tables.

Defines the database schema using SQLAlchemy declarative base.
Tables: task, task_step, report.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


class Task(Base):
    """Represents a testing task.

    Attributes:
        id: Auto-increment primary key.
        task_name: Human-readable task name.
        target_url: The URL under test.
        status: Current status (pending, running, paused_for_review,
            completed, failed, cancelled).
        config: JSONB with test rules, credentials, focus areas.
        started_at: Timestamp when the task started (nullable).
        completed_at: Timestamp when the task completed (nullable).
        created_at: Timestamp when the task was created.
        steps: Related TaskStep records.
        reports: Related Report records.
    """

    __tablename__ = "task"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    phase: Mapped[str | None] = mapped_column(String(50), nullable=True)
    report_status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    analysis_package: Mapped[dict | None] = mapped_column(JSONB, nullable=True, comment="L2 分析管道产出的完整 TestAssetPackage")
    checkpoints: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    resume_policy: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    steps: Mapped[list["TaskStep"]] = relationship("TaskStep", back_populates="task", cascade="all, delete-orphan")
    execution_runs: Mapped[list["ExecutionRunRecord"]] = relationship(
        "ExecutionRunRecord",
        back_populates="task",
        cascade="all, delete-orphan",
        foreign_keys="ExecutionRunRecord.task_id",
    )
    human_review_requests: Mapped[list["HumanReviewRequestRecord"]] = relationship(
        "HumanReviewRequestRecord",
        back_populates="task",
        cascade="all, delete-orphan",
        foreign_keys="HumanReviewRequestRecord.task_id",
    )
    reports: Mapped[list["Report"]] = relationship("Report", back_populates="task", cascade="all, delete-orphan")


class TaskStep(Base):
    """Represents a single step executed during a task.

    Attributes:
        id: Auto-increment primary key.
        task_id: Foreign key to task.id.
        test_case_id: Identifier like TC-001, TC-002.
        step_index: Step sequence number.
        action_type: Type of action (click, input_text, navigate, etc.).
        action_target: Target element or description.
        action_args: JSONB with action parameters.
        result: Result description.
        screenshot_path: Path to the screenshot file.
        change_report: JSONB with ChangeReport from change detector.
        assertion_result: JSONB with assertion status and reasoning.
        created_at: Timestamp when the step was recorded.
        task: Related Task record.
    """

    __tablename__ = "task_step"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "test_case_id",
            "attempt_no",
            "step_index",
            name="uq_task_step_run_case_attempt_step",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("task.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("execution_run.run_id", ondelete="CASCADE"), nullable=False
    )
    test_case_id: Mapped[str] = mapped_column(String(50), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    action_target: Mapped[str] = mapped_column(Text, nullable=False)
    action_args: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result: Mapped[str] = mapped_column(Text, nullable=False, default="")
    screenshot_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    change_report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tool_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    policy_decision: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    assertion_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    task: Mapped["Task"] = relationship("Task", back_populates="steps")
    execution_run: Mapped["ExecutionRunRecord"] = relationship("ExecutionRunRecord", back_populates="steps")


class ExecutionRunRecord(Base):
    """One immutable execution boundary for a task."""

    __tablename__ = "execution_run"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("task.id", ondelete="CASCADE"), nullable=False, index=True
    )
    schema_version: Mapped[str] = mapped_column(
        String(50), nullable=False, default="execution_run.v1"
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="running")
    candidate_case_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    resumed_from_run_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("execution_run.run_id", ondelete="SET NULL"), nullable=True
    )
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped["Task"] = relationship(
        "Task",
        back_populates="execution_runs",
        foreign_keys=[task_id],
    )
    results: Mapped[list["CaseResultRecord"]] = relationship(
        "CaseResultRecord", back_populates="execution_run", cascade="all, delete-orphan"
    )
    steps: Mapped[list["TaskStep"]] = relationship(
        "TaskStep", back_populates="execution_run", cascade="all, delete-orphan"
    )
    reports: Mapped[list["Report"]] = relationship("Report", back_populates="execution_run")
    human_review_requests: Mapped[list["HumanReviewRequestRecord"]] = relationship(
        "HumanReviewRequestRecord",
        back_populates="execution_run",
        foreign_keys="HumanReviewRequestRecord.run_id",
    )


class CaseResultRecord(Base):
    """Authoritative terminal result for one candidate case in one run."""

    __tablename__ = "case_result"
    __table_args__ = (
        UniqueConstraint("run_id", "candidate_case_id", name="uq_case_result_run_case"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("execution_run.run_id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_case_id: Mapped[str] = mapped_column(String(100), nullable=False)
    terminal_status: Mapped[str] = mapped_column(String(50), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)

    execution_run: Mapped["ExecutionRunRecord"] = relationship(
        "ExecutionRunRecord", back_populates="results"
    )


class HumanReviewRequestRecord(Base):
    """A durable request for human review before automation continues."""

    __tablename__ = "human_review_request"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("task.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("execution_run.run_id", ondelete="SET NULL"), nullable=True, index=True
    )
    candidate_case_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    phase: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    blocked_tool: Mapped[str | None] = mapped_column(String(100), nullable=True)
    requested_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)

    task: Mapped["Task"] = relationship(
        "Task",
        back_populates="human_review_requests",
        foreign_keys=[task_id],
    )
    execution_run: Mapped["ExecutionRunRecord | None"] = relationship(
        "ExecutionRunRecord",
        back_populates="human_review_requests",
        foreign_keys=[run_id],
    )
    decisions: Mapped[list["HumanReviewDecisionRecord"]] = relationship(
        "HumanReviewDecisionRecord",
        back_populates="request",
        cascade="all, delete-orphan",
    )


class HumanReviewDecisionRecord(Base):
    """A user's decision for a pending human review request."""

    __tablename__ = "human_review_decision"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("human_review_request.id", ondelete="CASCADE"), nullable=False, index=True
    )
    decision: Mapped[str] = mapped_column(String(50), nullable=False)
    edited_inputs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    approved_tools: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    request: Mapped["HumanReviewRequestRecord"] = relationship(
        "HumanReviewRequestRecord",
        back_populates="decisions",
    )


class Report(Base):
    """Represents a test report generated for a task.

    Attributes:
        id: Auto-increment primary key.
        task_id: Foreign key to task.id.
        report_path: Path to the generated report file.
        summary: AI-generated summary text.
        created_at: Timestamp when the report was created.
        task: Related Task record.
    """

    __tablename__ = "report"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("task.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("execution_run.run_id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="completed")
    report_path: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    task: Mapped["Task"] = relationship("Task", back_populates="reports")
    execution_run: Mapped["ExecutionRunRecord"] = relationship(
        "ExecutionRunRecord", back_populates="reports"
    )


class AgentMemory(Base):
    """Represents a piece of memory/knowledge learned by the agent.

    Attributes:
        id: Auto-increment primary key.
        scope_type: Memory scope type ('global' or 'domain').
        scope_value: Scope target (e.g., '*' for global, '192.168.31.155' for domain).
        memory_key: A short description/index for the memory.
        memory_value: The detailed knowledge or rule text.
        created_at: Timestamp when created.
        updated_at: Timestamp when last updated.
    """

    __tablename__ = "agent_memory"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scope_type: Mapped[str] = mapped_column(String(50), nullable=False)
    scope_value: Mapped[str] = mapped_column(Text, nullable=False)
    memory_key: Mapped[str] = mapped_column(Text, nullable=False)
    memory_value: Mapped[str] = mapped_column(Text, nullable=False)
    source_domain: Mapped[str | None] = mapped_column(Text, nullable=True, default="")
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
