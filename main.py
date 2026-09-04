"""FastAPI application entry point.

Startup:
  1. Initialize SQLite checkpointer (LangGraph)
  2. Build the agent graph
  3. Initialize TTL manager
  4. Start background sweeper
  5. Recover any runs that expired while we were down

Shutdown:
  1. Cancel the sweeper
  2. Close database connections
"""

from __future__ import annotations

import asyncio
import logging

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

import config as app_config
from agent.graph import build_graph
from api.routes import router as agent_router
from ttl.manager import TTLManager
from ttl.sweeper import run_sweeper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown logic."""
    logger.info("Starting durable agent server...")
    logger.info("Checkpoint DB: %s", app_config.CHECKPOINT_DB)
    logger.info("TTL DB: %s", app_config.TTL_DB)
    logger.info("Default TTL: %ds", app_config.DEFAULT_TTL_SECONDS)

    # 1. Initialize the checkpointer
    async with AsyncSqliteSaver.from_conn_string(app_config.CHECKPOINT_DB) as checkpointer:
        # 2. Build the graph with the checkpointer
        graph = build_graph(checkpointer=checkpointer)
        app.state.graph = graph

        # 3. Initialize TTL manager
        ttl_manager = TTLManager(app_config.TTL_DB)
        app.state.ttl_manager = ttl_manager

        # 4. Mock LLM flag (controlled via env for testing)
        app.state.mock_llm = not bool(app_config.GROQ_API_KEY)

        # 5. Start the background sweeper
        sweeper_task = asyncio.create_task(
            run_sweeper(app.state, interval=app_config.SWEEPER_INTERVAL_SECONDS)
        )
        logger.info("Sweeper started (interval=%ds)", app_config.SWEEPER_INTERVAL_SECONDS)

        logger.info("Server ready.")
        yield

        # Shutdown
        logger.info("Shutting down...")
        sweeper_task.cancel()
        try:
            await sweeper_task
        except asyncio.CancelledError:
            pass
        ttl_manager.close()
        logger.info("Shutdown complete.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Durable Agent — P27",
    description=(
        "AI agent with durable execution. Suspends for human approval, "
        "survives process restarts, enforces TTL-bounded approval windows."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(agent_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "durable-agent"}
