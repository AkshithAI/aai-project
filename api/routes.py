"""FastAPI routes for the durable agent.

Endpoints:
    POST   /agent/runs              — Submit a task
    GET    /agent/runs              — List runs
    GET    /agent/runs/{thread_id}  — Get run status
    POST   /agent/runs/{id}/approve — Approve pending action
    POST   /agent/runs/{id}/reject  — Reject pending action
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from langgraph.types import Command

from api.schemas import (
    ApprovalRequest,
    ApprovalResponse,
    CreateRunRequest,
    ErrorResponse,
    RejectionRequest,
    RunCreatedResponse,
    RunStatusResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


# ---------------------------------------------------------------------------
# POST /agent/runs — Submit a task
# ---------------------------------------------------------------------------

@router.post("/runs", response_model=RunCreatedResponse, status_code=201)
async def create_run(body: CreateRunRequest, request: Request):
    """Submit a task for the agent to plan and execute.

    The agent will execute safe steps automatically and suspend
    when it reaches a consequential action requiring approval.
    """
    graph = request.app.state.graph
    ttl_manager = request.app.state.ttl_manager

    thread_id = str(uuid.uuid4())
    config = {
        "configurable": {
            "thread_id": thread_id,
            "mock_llm": getattr(request.app.state, "mock_llm", False),
        }
    }

    logger.info("Creating run: thread=%s task=%s ttl=%d", thread_id, body.task, body.ttl_seconds)

    # Invoke the graph — it will run until it hits an interrupt() or completes
    initial_state = {
        "task": body.task,
        "plan": [],
        "current_step": 0,
        "completed_steps": [],
        "pending_action": None,
        "approval_decision": None,
        "final_result": None,
        "messages": [],
        "error": None,
    }

    result = await graph.ainvoke(initial_state, config=config)

    # Check if the graph is interrupted (suspended for approval)
    state_snapshot = await graph.aget_state(config)
    is_interrupted = bool(state_snapshot.tasks)

    status = "suspended" if is_interrupted else "completed"

    # If suspended, register the TTL
    time_remaining = None
    if is_interrupted:
        ttl_manager.register_interrupt(thread_id, body.ttl_seconds)
        time_remaining = float(body.ttl_seconds)

    return RunCreatedResponse(
        thread_id=thread_id,
        status=status,
        task=body.task,
        plan=result.get("plan", []),
        pending_action=result.get("pending_action"),
        time_remaining=time_remaining,
    )


# ---------------------------------------------------------------------------
# GET /agent/runs — List runs
# ---------------------------------------------------------------------------

@router.get("/runs")
async def list_runs(request: Request, status: str | None = None):
    """List all tracked runs. Optionally filter by status."""
    ttl_manager = request.app.state.ttl_manager
    graph = request.app.state.graph

    # Get all TTL records as a starting point
    rows = ttl_manager.conn.execute(
        "SELECT thread_id, status, ttl_seconds, suspended_at, expires_at FROM interrupt_ttls"
    ).fetchall()

    runs = []
    for row in rows:
        record = dict(row)
        if status and record["status"] != status:
            continue
        record["time_remaining"] = ttl_manager.get_time_remaining(record["thread_id"])
        runs.append(record)

    return {"runs": runs, "count": len(runs)}


# ---------------------------------------------------------------------------
# GET /agent/runs/{thread_id} — Get run status
# ---------------------------------------------------------------------------

@router.get("/runs/{thread_id}", response_model=RunStatusResponse)
async def get_run(thread_id: str, request: Request):
    """Get the full status of an agent run."""
    graph = request.app.state.graph
    ttl_manager = request.app.state.ttl_manager

    config = {"configurable": {"thread_id": thread_id}}

    state_snapshot = await graph.aget_state(config)

    if not state_snapshot or not state_snapshot.values:
        raise HTTPException(status_code=404, detail={
            "error": "run_not_found",
            "code": "NOT_FOUND",
            "message": f"No run found with thread_id: {thread_id}",
        })

    values = state_snapshot.values
    is_interrupted = bool(state_snapshot.tasks)

    # Determine status
    if is_interrupted:
        ttl_status = ttl_manager.check_ttl(thread_id)
        run_status = "expired" if ttl_status == "expired" else "suspended"
    elif values.get("approval_decision") == "expired":
        run_status = "expired"
    elif values.get("approval_decision") == "rejected":
        run_status = "rejected"
    elif values.get("final_result"):
        run_status = "completed"
    elif values.get("error"):
        run_status = "failed"
    else:
        run_status = "executing"

    return RunStatusResponse(
        thread_id=thread_id,
        status=run_status,
        task=values.get("task", ""),
        plan=values.get("plan", []),
        current_step=values.get("current_step", 0),
        completed_steps=values.get("completed_steps", []),
        pending_action=values.get("pending_action"),
        approval_decision=values.get("approval_decision"),
        final_result=values.get("final_result"),
        time_remaining=ttl_manager.get_time_remaining(thread_id),
        error=values.get("error"),
    )


# ---------------------------------------------------------------------------
# POST /agent/runs/{thread_id}/approve — Approve pending action
# ---------------------------------------------------------------------------

@router.post("/runs/{thread_id}/approve", response_model=ApprovalResponse)
async def approve_run(thread_id: str, body: ApprovalRequest, request: Request):
    """Approve a pending consequential action.

    Returns:
        200 — approved and execution continued
        409 — run is not in a suspended state
        410 — approval window has expired (TTL exceeded)
    """
    graph = request.app.state.graph
    ttl_manager = request.app.state.ttl_manager

    # 1. Check TTL
    ttl_status = ttl_manager.check_ttl(thread_id)

    if ttl_status == "not_found":
        raise HTTPException(status_code=404, detail={
            "error": "run_not_found",
            "code": "NOT_FOUND",
            "message": f"No pending approval found for thread: {thread_id}",
        })

    if ttl_status == "expired":
        raise HTTPException(status_code=410, detail={
            "error": "approval_expired",
            "code": "TTL_EXCEEDED",
            "message": "The approval window has closed. This action will not be executed.",
            "thread_id": thread_id,
        })

    # 2. Check graph is actually interrupted
    config = {"configurable": {"thread_id": thread_id}}
    state_snapshot = await graph.aget_state(config)

    if not state_snapshot or not state_snapshot.tasks:
        raise HTTPException(status_code=409, detail={
            "error": "not_suspended",
            "code": "CONFLICT",
            "message": "This run is not currently waiting for approval.",
            "thread_id": thread_id,
        })

    # 3. Resume the graph with approval
    logger.info("Approving run: thread=%s approver=%s", thread_id, body.approver)
    result = await graph.ainvoke(
        Command(resume={"status": "approved", "approver": body.approver, "note": body.note}),
        config=config,
    )

    # 4. Mark TTL as resolved
    ttl_manager.mark_resolved(thread_id, "approved", resolved_by=body.approver)

    # Check if there's another interrupt (multi-step approval)
    new_state = await graph.aget_state(config)
    if new_state and new_state.tasks:
        # Re-register TTL for the new interrupt
        ttl_record = ttl_manager.get_record(thread_id)
        if ttl_record:
            ttl_manager.register_interrupt(thread_id, ttl_record["ttl_seconds"])
        return ApprovalResponse(
            thread_id=thread_id,
            status="suspended",
            decision="approved",
            final_result=None,
        )

    return ApprovalResponse(
        thread_id=thread_id,
        status="completed",
        decision="approved",
        final_result=result.get("final_result"),
    )


# ---------------------------------------------------------------------------
# POST /agent/runs/{thread_id}/reject — Reject pending action
# ---------------------------------------------------------------------------

@router.post("/runs/{thread_id}/reject", response_model=ApprovalResponse)
async def reject_run(thread_id: str, body: RejectionRequest, request: Request):
    """Reject a pending consequential action.

    Returns:
        200 — rejected, run terminated
        409 — run is not in a suspended state
        410 — approval window has expired (TTL exceeded)
    """
    graph = request.app.state.graph
    ttl_manager = request.app.state.ttl_manager

    # 1. Check TTL
    ttl_status = ttl_manager.check_ttl(thread_id)

    if ttl_status == "not_found":
        raise HTTPException(status_code=404, detail={
            "error": "run_not_found",
            "code": "NOT_FOUND",
            "message": f"No pending approval found for thread: {thread_id}",
        })

    if ttl_status == "expired":
        raise HTTPException(status_code=410, detail={
            "error": "approval_expired",
            "code": "TTL_EXCEEDED",
            "message": "The approval window has closed.",
            "thread_id": thread_id,
        })

    # 2. Check graph is interrupted
    config = {"configurable": {"thread_id": thread_id}}
    state_snapshot = await graph.aget_state(config)

    if not state_snapshot or not state_snapshot.tasks:
        raise HTTPException(status_code=409, detail={
            "error": "not_suspended",
            "code": "CONFLICT",
            "message": "This run is not currently waiting for approval.",
            "thread_id": thread_id,
        })

    # 3. Resume with rejection
    logger.info("Rejecting run: thread=%s approver=%s reason=%s", thread_id, body.approver, body.reason)
    result = await graph.ainvoke(
        Command(resume={"status": "rejected", "approver": body.approver, "reason": body.reason}),
        config=config,
    )

    # 4. Mark TTL as resolved
    ttl_manager.mark_resolved(thread_id, "rejected", resolved_by=body.approver)

    return ApprovalResponse(
        thread_id=thread_id,
        status="rejected",
        decision="rejected",
        final_result=result.get("final_result"),
    )
