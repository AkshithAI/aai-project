"""Background sweeper that expires stale interrupted runs.

Runs on a configurable interval and:
1. Queries for threads past their TTL deadline
2. Resumes each with {"status": "expired"} via Command(resume=...)
3. Marks the TTL record as expired

Runs immediately on startup to catch anything that expired while
the process was down.
"""

from __future__ import annotations

import asyncio
import logging

from langgraph.types import Command

logger = logging.getLogger(__name__)


async def run_sweeper(app_state, interval: int | None = None):
    """Background task that periodically expires stale runs.

    Args:
        app_state: FastAPI app.state with .ttl_manager and .graph
        interval: sweep interval in seconds (defaults to config)
    """
    if interval is None:
        import config as app_config
        interval = app_config.SWEEPER_INTERVAL_SECONDS

    logger.info("Sweeper started (interval=%ds)", interval)

    # Run immediately on startup to catch expired runs
    await _sweep_once(app_state)

    while True:
        try:
            await asyncio.sleep(interval)
            await _sweep_once(app_state)
        except asyncio.CancelledError:
            logger.info("Sweeper cancelled — shutting down")
            break
        except Exception:
            logger.exception("Sweeper error — will retry next interval")


async def _sweep_once(app_state):
    """Single sweep pass: find and expire stale threads."""
    ttl_manager = app_state.ttl_manager
    graph = app_state.graph

    expired_threads = ttl_manager.get_expired_threads()

    if not expired_threads:
        return

    logger.info("Sweeper found %d expired thread(s)", len(expired_threads))

    for thread_id in expired_threads:
        try:
            config = {"configurable": {"thread_id": thread_id}}

            # Check if the graph actually has a pending interrupt
            state = await graph.aget_state(config)

            if state and state.tasks:
                # Resume the graph with an expired decision
                logger.info("Expiring thread %s via Command(resume=...)", thread_id)
                await graph.ainvoke(
                    Command(resume={"status": "expired"}),
                    config=config,
                )
            else:
                logger.info(
                    "Thread %s has no pending interrupt — marking expired anyway",
                    thread_id,
                )

            # Mark the TTL record as expired
            ttl_manager.mark_resolved(thread_id, "expired", resolved_by="sweeper")

        except Exception:
            logger.exception("Failed to expire thread %s", thread_id)
