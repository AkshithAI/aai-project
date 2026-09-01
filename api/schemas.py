"""Request/response schemas for the API layer."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class CreateRunRequest(BaseModel):
    """Request to submit a task for the agent."""
    task: str = Field(..., description="The task for the agent to execute")
    ttl_seconds: int = Field(
        default=3600,
        ge=1,
        le=604800,  # max 7 days
        description="Time-to-live for the approval window in seconds",
    )


class ApprovalRequest(BaseModel):
    """Request to approve a pending action."""
    approver: str = Field(default="anonymous", description="Who is approving")
    note: str = Field(default="", description="Optional note about the approval")


class RejectionRequest(BaseModel):
    """Request to reject a pending action."""
    approver: str = Field(default="anonymous", description="Who is rejecting")
    reason: str = Field(default="", description="Reason for rejection")


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class RunStatusResponse(BaseModel):
    """Full status of an agent run."""
    thread_id: str
    status: str  # planning | executing | suspended | completed | expired | rejected | failed
    task: str
    plan: list[dict[str, Any]] = Field(default_factory=list)
    current_step: int = 0
    completed_steps: list[dict[str, Any]] = Field(default_factory=list)
    pending_action: dict[str, Any] | None = None
    approval_decision: str | None = None
    final_result: str | None = None
    time_remaining: float | None = None
    error: str | None = None


class RunCreatedResponse(BaseModel):
    """Response when a new run is created."""
    thread_id: str
    status: str
    task: str
    plan: list[dict[str, Any]] = Field(default_factory=list)
    pending_action: dict[str, Any] | None = None
    time_remaining: float | None = None


class ApprovalResponse(BaseModel):
    """Response after approving/rejecting a run."""
    thread_id: str
    status: str
    decision: str
    final_result: str | None = None


class ErrorResponse(BaseModel):
    """Error response body."""
    error: str
    code: str
    message: str
    thread_id: str | None = None
