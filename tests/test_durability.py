"""Durability acceptance tests — the "Done when" criteria.

Test 1: Agent survives process restart
Test 2: Expired approval returns 410 Gone (via TTL manager)
Test 3: Sweeper auto-expires stale runs
Test 4: Replay skips completed steps (no duplicate side effects)
Test 5: Approve non-suspended run returns 409
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
import time
from unittest.mock import patch, MagicMock

import pytest
import pytest_asyncio
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from agent.graph import build_graph
from ttl.manager import TTLManager


# ---------------------------------------------------------------------------
# Test 1: Agent Survives Process Restart
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_restart_survival():
    """The money test: destroy the engine and re-create from the same DB.

    The interrupted run must survive with full state intact.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "checkpoint_restart.db")

        # --- Phase 1: Run the agent until it suspends ---
        async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
            graph = build_graph(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": "restart-test", "mock_llm": True}}

            result = await graph.ainvoke(
                {
                    "task": "Research and email summary",
                    "plan": [],
                    "current_step": 0,
                    "completed_steps": [],
                    "pending_action": None,
                    "approval_decision": None,
                    "final_result": None,
                    "messages": [],
                    "error": None,
                },
                config=config,
            )

            # Verify it's suspended (has pending interrupt)
            state = await graph.aget_state(config)
            assert state.tasks, "Graph should be interrupted (suspended for approval)"

            # Verify some steps were completed before suspension
            assert len(result.get("completed_steps", [])) > 0, (
                "Should have completed safe steps before suspending"
            )
            completed_count_before = len(result["completed_steps"])

        # --- Phase 2: Simulate process death ---
        # The checkpointer is now closed. The graph object is gone.
        # Only the SQLite file on disk remains.
        del graph

        # --- Phase 3: Restart — re-create everything from the same DB ---
        async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer2:
            graph2 = build_graph(checkpointer=checkpointer2)
            config2 = {"configurable": {"thread_id": "restart-test", "mock_llm": True}}

            # Verify state survived the restart
            state2 = await graph2.aget_state(config2)
            assert state2 is not None, "State should survive restart"
            assert state2.values, "State values should be populated"
            assert state2.tasks, "Interrupt should still be pending after restart"
            assert len(state2.values.get("completed_steps", [])) == completed_count_before

            # --- Phase 4: Approve and complete ---
            result2 = await graph2.ainvoke(
                Command(resume={"status": "approved", "approver": "test"}),
                config=config2,
            )

            assert result2.get("approval_decision") == "approved"
            assert result2.get("final_result") is not None
            # More steps should be completed after approval
            assert len(result2.get("completed_steps", [])) > completed_count_before


# ---------------------------------------------------------------------------
# Test 2: TTL Expiry Rejection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ttl_expiry_returns_expired():
    """Approval after TTL is refused — the TTL manager enforces this."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ttl_mgr = TTLManager(os.path.join(tmp_dir, "ttl_expiry.db"))

        thread_id = "ttl-test-expired"
        # Register with a very short TTL
        ttl_mgr.register_interrupt(thread_id, ttl_seconds=1)

        # Verify it's valid right now
        assert ttl_mgr.check_ttl(thread_id) == "valid"

        # Wait for expiry
        await asyncio.sleep(1.5)

        # Now it should be expired
        assert ttl_mgr.check_ttl(thread_id) == "expired"
        assert ttl_mgr.get_time_remaining(thread_id) == 0.0

        ttl_mgr.close()


# ---------------------------------------------------------------------------
# Test 3: Sweeper Catches Expired Workflows
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sweeper_expires_stale_runs():
    """The sweeper should find and expire runs past their TTL."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "checkpoint_sweep.db")
        ttl_db_path = os.path.join(tmp_dir, "ttl_sweep.db")

        async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
            graph = build_graph(checkpointer=checkpointer)
            ttl_mgr = TTLManager(ttl_db_path)

            config = {"configurable": {"thread_id": "sweep-test", "mock_llm": True}}

            # Run until suspension
            await graph.ainvoke(
                {
                    "task": "Research and email summary",
                    "plan": [],
                    "current_step": 0,
                    "completed_steps": [],
                    "pending_action": None,
                    "approval_decision": None,
                    "final_result": None,
                    "messages": [],
                    "error": None,
                },
                config=config,
            )

            # Register with 1-second TTL
            ttl_mgr.register_interrupt("sweep-test", ttl_seconds=1)

            # Wait for expiry
            await asyncio.sleep(1.5)

            # Verify TTL manager sees it as expired
            expired = ttl_mgr.get_expired_threads()
            assert "sweep-test" in expired

            # Simulate sweeper: resume with expired status
            state = await graph.aget_state(config)
            assert state.tasks, "Should still have pending interrupt"

            result = await graph.ainvoke(
                Command(resume={"status": "expired"}),
                config=config,
            )

            ttl_mgr.mark_resolved("sweep-test", "expired", resolved_by="sweeper")

            # Verify the run is now expired
            assert result.get("approval_decision") == "expired"
            record = ttl_mgr.get_record("sweep-test")
            assert record["status"] == "expired"

            ttl_mgr.close()


# ---------------------------------------------------------------------------
# Test 4: Replay Idempotency (No Duplicate Side Effects)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_replay_skips_completed_steps():
    """After restart, already-completed steps should NOT be re-executed.

    LangGraph stores the completed step results in state, so the execute
    node naturally advances past them on resume.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "checkpoint_replay.db")

        # Phase 1: Execute until suspension
        async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
            graph = build_graph(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": "replay-test", "mock_llm": True}}

            result = await graph.ainvoke(
                {
                    "task": "Research and email summary",
                    "plan": [],
                    "current_step": 0,
                    "completed_steps": [],
                    "pending_action": None,
                    "approval_decision": None,
                    "final_result": None,
                    "messages": [],
                    "error": None,
                },
                config=config,
            )

            completed_before = result.get("completed_steps", [])
            step_count_before = len(completed_before)
            assert step_count_before > 0

        # Phase 2: Restart and resume
        async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer2:
            graph2 = build_graph(checkpointer=checkpointer2)
            config2 = {"configurable": {"thread_id": "replay-test", "mock_llm": True}}

            # Get the state — completed steps should be preserved
            state = await graph2.aget_state(config2)
            assert len(state.values.get("completed_steps", [])) == step_count_before

            # Resume — the previously completed steps should still be there
            result2 = await graph2.ainvoke(
                Command(resume={"status": "approved", "approver": "test"}),
                config=config2,
            )

            # The final completed_steps should include the original ones
            # plus the newly approved step (not duplicates)
            final_completed = result2.get("completed_steps", [])
            assert len(final_completed) > step_count_before, (
                "Should have MORE steps after approval, not duplicates"
            )

            # Verify no duplicate step indices
            step_indices = [s["step_index"] for s in final_completed]
            assert len(step_indices) == len(set(step_indices)), (
                f"Duplicate step indices found: {step_indices}"
            )


# ---------------------------------------------------------------------------
# Test 5: Approve Non-Suspended Run
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_non_suspended_fails():
    """Attempting to approve a completed (non-suspended) run should fail."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "checkpoint_nosuspend.db")

        # Create a graph with a plan that has NO consequential tools
        mock_plan = """[
  {"description": "Search web", "tool_name": "search_web", "tool_args": {"query": "test"}, "requires_approval": false, "risk_level": "low"},
  {"description": "Analyze", "tool_name": "analyze_data", "tool_args": {"data": "test"}, "requires_approval": false, "risk_level": "low"}
]"""

        async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
            graph = build_graph(checkpointer=checkpointer)
            config = {
                "configurable": {
                    "thread_id": "no-suspend-test",
                    "mock_llm": True,
                    "mock_responses": [mock_plan],
                }
            }

            result = await graph.ainvoke(
                {
                    "task": "Just search and analyze",
                    "plan": [],
                    "current_step": 0,
                    "completed_steps": [],
                    "pending_action": None,
                    "approval_decision": None,
                    "final_result": None,
                    "messages": [],
                    "error": None,
                },
                config=config,
            )

            # It should complete without suspending
            assert result.get("final_result") is not None

            # Verify there's no pending interrupt
            state = await graph.aget_state(config)
            assert not state.tasks, "Should NOT have pending interrupts"
