"""Shared test fixtures.

Provides:
- File-based SQLite checkpointer (tmp dir per test) for isolation
- Mock LLM returning deterministic plans
- TTL manager with fresh DB per test
- Compiled graph ready for testing
"""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest
import pytest_asyncio
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from agent.graph import build_graph
from ttl.manager import TTLManager


@pytest.fixture
def tmp_dir():
    """Provide a temporary directory for test databases."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def ttl_manager(tmp_dir):
    """Fresh TTL manager with an isolated database."""
    mgr = TTLManager(os.path.join(tmp_dir, "ttl_test.db"))
    yield mgr
    mgr.close()


@pytest_asyncio.fixture
async def checkpointer(tmp_dir):
    """Async SQLite checkpointer with a file-based DB for durability testing."""
    db_path = os.path.join(tmp_dir, "checkpoints_test.db")
    async with AsyncSqliteSaver.from_conn_string(db_path) as cp:
        yield cp


@pytest_asyncio.fixture
async def graph(checkpointer):
    """Compiled LangGraph agent with mock LLM and file-based checkpointer."""
    g = build_graph(checkpointer=checkpointer)
    yield g


@pytest.fixture
def mock_config():
    """Config dict that enables mock LLM mode."""
    return {
        "configurable": {
            "thread_id": "test-thread-1",
            "mock_llm": True,
        }
    }


@pytest.fixture
def mock_config_factory():
    """Factory that generates configs with unique thread IDs."""
    counter = 0

    def _make(thread_id: str | None = None, **kwargs):
        nonlocal counter
        counter += 1
        tid = thread_id or f"test-thread-{counter}"
        conf = {
            "configurable": {
                "thread_id": tid,
                "mock_llm": True,
                **kwargs,
            }
        }
        return conf, tid

    return _make
