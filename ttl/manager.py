"""TTL (Time-To-Live) manager for agent approval windows.

LangGraph doesn't provide native TTL for interrupts, so we track
expiry deadlines in a separate SQLite table and enforce them at
the API layer + background sweeper.
"""

from __future__ import annotations

import sqlite3
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal

logger = logging.getLogger(__name__)

TTLStatus = Literal["valid", "expired", "not_found"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS interrupt_ttls (
    thread_id   TEXT PRIMARY KEY,
    ttl_seconds INTEGER NOT NULL,
    suspended_at TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    resolved_at TEXT,
    resolved_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_ttl_status
    ON interrupt_ttls(status) WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_ttl_expires
    ON interrupt_ttls(expires_at) WHERE status = 'pending';
"""


class TTLManager:
    """Tracks TTL for interrupted agent runs using a SQLite table."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_table()

    def _init_table(self):
        """Create the TTL tracking table if it doesn't exist."""
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def register_interrupt(self, thread_id: str, ttl_seconds: int) -> datetime:
        """Record that a thread is suspended and compute its expiry time.

        Returns the computed expires_at datetime.
        """
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)

        self.conn.execute(
            """INSERT OR REPLACE INTO interrupt_ttls
               (thread_id, ttl_seconds, suspended_at, expires_at, status, resolved_at, resolved_by)
               VALUES (?, ?, ?, ?, 'pending', NULL, NULL)""",
            (thread_id, ttl_seconds, now.isoformat(), expires_at.isoformat()),
        )
        self.conn.commit()

        logger.info(
            "Registered interrupt TTL: thread=%s ttl=%ds expires_at=%s",
            thread_id, ttl_seconds, expires_at.isoformat(),
        )
        return expires_at

    def check_ttl(self, thread_id: str) -> TTLStatus:
        """Check if a thread's approval window is still open.

        Returns:
            'valid'     — the window is still open
            'expired'   — the TTL has been exceeded
            'not_found' — no record for this thread
        """
        row = self.conn.execute(
            "SELECT expires_at, status FROM interrupt_ttls WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()

        if row is None:
            return "not_found"

        # If already resolved (approved/rejected/expired), check the status
        if row["status"] != "pending":
            return "expired" if row["status"] == "expired" else "not_found"

        expires_at = datetime.fromisoformat(row["expires_at"])
        # Ensure timezone-aware comparison
        now = datetime.now(timezone.utc)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if now >= expires_at:
            return "expired"

        return "valid"

    def get_time_remaining(self, thread_id: str) -> float | None:
        """Get seconds remaining in the approval window, or None if not found."""
        row = self.conn.execute(
            "SELECT expires_at, status FROM interrupt_ttls WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()

        if row is None or row["status"] != "pending":
            return None

        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        remaining = (expires_at - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, remaining)

    def get_expired_threads(self) -> list[str]:
        """Return thread_ids where status='pending' AND expires_at has passed."""
        now = datetime.now(timezone.utc).isoformat()
        rows = self.conn.execute(
            "SELECT thread_id FROM interrupt_ttls WHERE status = 'pending' AND expires_at < ?",
            (now,),
        ).fetchall()
        return [row["thread_id"] for row in rows]

    def mark_resolved(self, thread_id: str, resolution: str, resolved_by: str = "system"):
        """Mark a thread's TTL as resolved (approved/rejected/expired)."""
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE interrupt_ttls SET status = ?, resolved_at = ?, resolved_by = ? WHERE thread_id = ?",
            (resolution, now, resolved_by, thread_id),
        )
        self.conn.commit()
        logger.info("TTL resolved: thread=%s resolution=%s by=%s", thread_id, resolution, resolved_by)

    def get_record(self, thread_id: str) -> dict | None:
        """Get the full TTL record for a thread."""
        row = self.conn.execute(
            "SELECT * FROM interrupt_ttls WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def close(self):
        """Close the database connection."""
        self.conn.close()
