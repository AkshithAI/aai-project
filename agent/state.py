"""Agent state and model definitions."""

from __future__ import annotations

from typing import Annotated, Any

from langgraph.graph import add_messages
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# LangGraph State
# ---------------------------------------------------------------------------

class AgentState(dict):
    """State flowing through the LangGraph agent graph.

    Using TypedDict-style keys so LangGraph can checkpoint every field.
    """


# We define the state schema as annotations for StateGraph
AGENT_STATE_SCHEMA = {
    "task": str,
    "plan": list,                  # list[PlanStep dict]
    "current_step": int,
    "completed_steps": list,       # list[StepResult dict]
    "pending_action": dict | None, # the action awaiting approval
    "approval_decision": str | None,  # approved | rejected | expired
    "final_result": str | None,
    "messages": Annotated[list, add_messages],  # LLM message history
    "error": str | None,
}


# ---------------------------------------------------------------------------
# Pydantic models (for serialization / API use)
# ---------------------------------------------------------------------------

class PlanStep(BaseModel):
    """A single step in the agent's plan."""
    index: int
    description: str
    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = False
    risk_level: str = "low"  # low | medium | high | critical


class StepResult(BaseModel):
    """Result of executing a single step."""
    step_index: int
    tool_name: str
    output: str
    status: str = "completed"  # completed | failed


class ApprovalInfo(BaseModel):
    """Details of a pending approval request."""
    action: str
    args: dict[str, Any]
    description: str
    risk_level: str = "medium"
    message: str = "Human approval required for this action."
