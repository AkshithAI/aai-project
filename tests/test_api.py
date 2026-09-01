"""Integration tests for the FastAPI API layer.

Uses FastAPI's TestClient with httpx for synchronous testing.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from agent.graph import build_graph
from ttl.manager import TTLManager


# ---------------------------------------------------------------------------
# App fixture (creates a fresh app per test)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def app_client():
    """Create a fresh FastAPI app with isolated databases."""
    from fastapi import FastAPI
    from api.routes import router

    tmp_dir = tempfile.mkdtemp()
    checkpoint_db = os.path.join(tmp_dir, "test_checkpoints.db")
    ttl_db = os.path.join(tmp_dir, "test_ttl.db")

    app = FastAPI()
    app.include_router(router)

    async with AsyncSqliteSaver.from_conn_string(checkpoint_db) as checkpointer:
        graph = build_graph(checkpointer=checkpointer)
        app.state.graph = graph
        app.state.ttl_manager = TTLManager(ttl_db)
        app.state.mock_llm = True

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

        app.state.ttl_manager.close()


# ---------------------------------------------------------------------------
# Test: Create a run
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_run(app_client):
    """POST /agent/runs should create a run and return its status."""
    resp = await app_client.post(
        "/agent/runs",
        json={"task": "Research and email summary", "ttl_seconds": 300},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "thread_id" in data
    assert data["status"] in ("suspended", "completed")
    assert data["task"] == "Research and email summary"


# ---------------------------------------------------------------------------
# Test: Get run status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_run_status(app_client):
    """GET /agent/runs/{thread_id} should return full run details."""
    # Create a run first
    create_resp = await app_client.post(
        "/agent/runs",
        json={"task": "Research and email summary", "ttl_seconds": 300},
    )
    thread_id = create_resp.json()["thread_id"]

    # Get status
    resp = await app_client.get(f"/agent/runs/{thread_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["thread_id"] == thread_id
    assert data["task"] == "Research and email summary"
    assert isinstance(data["plan"], list)
    assert isinstance(data["completed_steps"], list)


# ---------------------------------------------------------------------------
# Test: Approve a suspended run
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_suspended_run(app_client):
    """POST /agent/runs/{id}/approve on a suspended run should complete it."""
    # Create a run that will suspend
    create_resp = await app_client.post(
        "/agent/runs",
        json={"task": "Research and email summary", "ttl_seconds": 300},
    )
    data = create_resp.json()
    thread_id = data["thread_id"]

    if data["status"] != "suspended":
        pytest.skip("Run didn't suspend (no consequential tools in plan)")

    # Approve
    resp = await app_client.post(
        f"/agent/runs/{thread_id}/approve",
        json={"approver": "tester", "note": "looks good"},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["decision"] == "approved"
    assert result["status"] in ("completed", "suspended")  # might have more approvals


# ---------------------------------------------------------------------------
# Test: Approve after TTL → 410 Gone
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_expired_returns_410(app_client):
    """POST /approve after TTL expiry should return 410 Gone."""
    # Create a run with very short TTL
    create_resp = await app_client.post(
        "/agent/runs",
        json={"task": "Research and email summary", "ttl_seconds": 1},
    )
    data = create_resp.json()
    thread_id = data["thread_id"]

    if data["status"] != "suspended":
        pytest.skip("Run didn't suspend")

    # Wait for TTL to expire
    await asyncio.sleep(1.5)

    # Try to approve — should be 410
    resp = await app_client.post(
        f"/agent/runs/{thread_id}/approve",
        json={"approver": "tester"},
    )
    assert resp.status_code == 410
    error = resp.json()["detail"]
    assert error["code"] == "TTL_EXCEEDED"


# ---------------------------------------------------------------------------
# Test: Approve non-existent run → 404
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_nonexistent_returns_404(app_client):
    """POST /approve on a non-existent thread should return 404."""
    resp = await app_client.post(
        "/agent/runs/nonexistent-thread/approve",
        json={"approver": "tester"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test: Reject a suspended run
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reject_suspended_run(app_client):
    """POST /agent/runs/{id}/reject should terminate the run."""
    create_resp = await app_client.post(
        "/agent/runs",
        json={"task": "Research and email summary", "ttl_seconds": 300},
    )
    data = create_resp.json()
    thread_id = data["thread_id"]

    if data["status"] != "suspended":
        pytest.skip("Run didn't suspend")

    resp = await app_client.post(
        f"/agent/runs/{thread_id}/reject",
        json={"approver": "tester", "reason": "not appropriate"},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["decision"] == "rejected"
    assert result["status"] == "rejected"


# ---------------------------------------------------------------------------
# Test: Get non-existent run → 404
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_nonexistent_run_returns_404(app_client):
    """GET /agent/runs/{id} for a non-existent run should return 404."""
    resp = await app_client.get("/agent/runs/does-not-exist")
    assert resp.status_code == 404
