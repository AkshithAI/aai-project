"""Tool definitions for the AI agent.

Each tool declares whether it is *consequential* (requires human approval)
via the _APPROVAL_REGISTRY.  The agent graph reads this to decide whether
to suspend at an approval gate before executing the tool.

Tools are REAL — they perform actual work (web search, code execution,
file I/O, email, database mutations).  Consequential tools require human
approval before the agent executes them.
"""

from __future__ import annotations

import io
import json
import logging
import os
import smtplib
import sqlite3
import traceback
from contextlib import redirect_stdout, redirect_stderr
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Registry: tool_name -> requires_approval
_APPROVAL_REGISTRY: dict[str, bool] = {}


def _register(name: str, requires_approval: bool):
    """Register a tool's approval requirement."""
    _APPROVAL_REGISTRY[name] = requires_approval


# ---------------------------------------------------------------------------
# Safe tools — no side effects, auto-executed (no human approval needed)
# ---------------------------------------------------------------------------

@tool
def search_web(query: str) -> str:
    """Search the web for real, up-to-date information using DuckDuckGo.

    Safe — read-only, no side effects.
    """
    logger.info("search_web called with query=%s", query)
    try:
        # Try the newer 'ddgs' package first, then fall back to 'duckduckgo_search'
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        ddgs = DDGS()
        raw_results = list(ddgs.text(query, max_results=5))

        if not raw_results:
            return json.dumps({"results": [], "message": f"No results found for '{query}'."})

        results = []
        for r in raw_results:
            results.append({
                "title": r.get("title", ""),
                "snippet": r.get("body", ""),
                "url": r.get("href", ""),
            })

        return json.dumps({"results": results, "query": query})

    except ImportError:
        logger.warning("Neither ddgs nor duckduckgo-search installed.")
        return json.dumps({
            "error": "Search package not installed. Run: pip install ddgs",
        })
    except Exception as e:
        logger.exception("search_web failed")
        return json.dumps({"error": str(e), "query": query})

_register("search_web", False)


@tool
def analyze_data(data: str) -> str:
    """Analyze the provided data and return computed insights.

    Performs real text/statistical analysis: word count, character count,
    line count, word frequency, and pattern detection.
    Safe — read-only computation.
    """
    logger.info("analyze_data called (data length=%d)", len(data))
    try:
        lines = data.strip().split("\n")
        words = data.split()
        chars = len(data)

        # Word frequency (top 10)
        freq: dict[str, int] = {}
        for w in words:
            cleaned = w.strip(".,!?;:\"'()[]{}").lower()
            if cleaned:
                freq[cleaned] = freq.get(cleaned, 0) + 1
        top_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:10]

        # Detect if data looks like CSV / JSON / plain text
        data_format = "plain_text"
        stripped = data.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                json.loads(stripped)
                data_format = "json"
            except json.JSONDecodeError:
                pass
        elif "," in lines[0] and len(lines) > 1:
            data_format = "csv_like"

        # Numeric detection
        numbers = []
        for w in words:
            try:
                numbers.append(float(w.strip(".,;:!?")))
            except ValueError:
                pass

        analysis: dict[str, Any] = {
            "data_format": data_format,
            "line_count": len(lines),
            "word_count": len(words),
            "character_count": chars,
            "top_words": [{"word": w, "count": c} for w, c in top_words],
            "unique_words": len(freq),
        }

        if numbers:
            analysis["numeric_summary"] = {
                "count": len(numbers),
                "min": min(numbers),
                "max": max(numbers),
                "mean": round(sum(numbers) / len(numbers), 4),
                "sum": round(sum(numbers), 4),
            }

        analysis["summary"] = (
            f"Analyzed {len(words)} words across {len(lines)} lines. "
            f"Format: {data_format}. {len(freq)} unique tokens detected."
        )

        return json.dumps(analysis)

    except Exception as e:
        logger.exception("analyze_data failed")
        return json.dumps({"error": str(e)})

_register("analyze_data", False)


@tool
def read_file(filepath: str) -> str:
    """Read a file and return its real contents.

    Safe — read-only.  Restricted to files under 50 KB for safety.
    """
    logger.info("read_file called with filepath=%s", filepath)
    try:
        path = Path(filepath).resolve()

        if not path.exists():
            return json.dumps({"error": f"File not found: {filepath}"})

        if not path.is_file():
            return json.dumps({"error": f"Not a file: {filepath}"})

        size = path.stat().st_size
        if size > 50 * 1024:  # 50 KB safety limit
            return json.dumps({
                "error": f"File too large ({size} bytes). Max 50 KB.",
                "filepath": str(path),
            })

        content = path.read_text(encoding="utf-8", errors="replace")
        return json.dumps({
            "filepath": str(path),
            "size_bytes": size,
            "lines": content.count("\n") + 1,
            "content": content,
        })

    except Exception as e:
        logger.exception("read_file failed")
        return json.dumps({"error": str(e), "filepath": filepath})

_register("read_file", False)


# ---------------------------------------------------------------------------
# Consequential tools — require human approval before execution
# ---------------------------------------------------------------------------

@tool
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email to the specified recipient via SMTP.

    CONSEQUENTIAL — requires human approval.

    Uses SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD / SMTP_FROM
    from environment.  If SMTP is not configured, runs in dry-run mode
    (logs the email but does not actually send it).
    """
    logger.info("send_email called: to=%s subject=%s", to, subject)

    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
    smtp_from = os.getenv("SMTP_FROM", smtp_user).strip()

    if not smtp_host or not smtp_user:
        # Dry-run mode — SMTP not configured
        logger.warning("SMTP not configured — running send_email in DRY-RUN mode.")
        return json.dumps({
            "status": "dry_run",
            "message": "SMTP not configured. Email was NOT actually sent.",
            "to": to,
            "subject": subject,
            "body_preview": body[:200],
            "note": "Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD in .env to enable real sending.",
        })

    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = smtp_from
        msg["To"] = to

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_from, [to], msg.as_string())

        logger.info("Email sent successfully to %s", to)
        return json.dumps({
            "status": "sent",
            "to": to,
            "subject": subject,
            "message": "Email delivered successfully.",
        })

    except Exception as e:
        logger.exception("send_email failed")
        return json.dumps({"status": "failed", "error": str(e), "to": to, "subject": subject})

_register("send_email", True)


@tool
def execute_code(code: str, language: str = "python") -> str:
    """Execute Python code and return real stdout/stderr output.

    CONSEQUENTIAL — requires human approval.

    Only Python is supported. Code runs in the current process with
    captured stdout/stderr.
    """
    logger.info("execute_code called: language=%s", language)

    if language.lower() != "python":
        return json.dumps({
            "status": "error",
            "error": f"Only Python is supported. Got: {language}",
        })

    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            exec_globals: dict[str, Any] = {"__builtins__": __builtins__}
            exec(code, exec_globals)  # noqa: S102

        stdout_text = stdout_capture.getvalue()
        stderr_text = stderr_capture.getvalue()

        return json.dumps({
            "status": "executed",
            "language": "python",
            "stdout": stdout_text if stdout_text else "(no output)",
            "stderr": stderr_text if stderr_text else "",
        })

    except Exception as e:
        tb = traceback.format_exc()
        return json.dumps({
            "status": "error",
            "language": "python",
            "error": str(e),
            "traceback": tb,
            "stdout": stdout_capture.getvalue(),
            "stderr": stderr_capture.getvalue(),
        })

_register("execute_code", True)


# Sandboxed SQLite database path for agent operations
_SANDBOX_DB = os.getenv("AGENT_SANDBOX_DB", "agent_sandbox.db")


@tool
def modify_database(query: str, database: str = "main") -> str:
    """Execute a SQL query on a sandboxed SQLite database.

    CONSEQUENTIAL — requires human approval.

    The agent operates on a dedicated sandbox database (agent_sandbox.db)
    to prevent accidental mutation of the application's own databases.
    Supports SELECT (returns rows) and INSERT/UPDATE/DELETE (returns row count).
    """
    logger.info("modify_database called: db=%s query=%s", database, query[:100])

    db_path = _SANDBOX_DB
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(query)
        query_upper = query.strip().upper()

        if query_upper.startswith("SELECT"):
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            data = [dict(row) for row in rows]
            conn.close()
            return json.dumps({
                "status": "executed",
                "database": db_path,
                "query_type": "SELECT",
                "columns": columns,
                "row_count": len(data),
                "rows": data[:100],  # cap at 100 rows for safety
            })
        else:
            conn.commit()
            rows_affected = cursor.rowcount
            conn.close()
            return json.dumps({
                "status": "executed",
                "database": db_path,
                "query_type": query_upper.split()[0] if query_upper else "UNKNOWN",
                "rows_affected": rows_affected,
            })

    except Exception as e:
        logger.exception("modify_database failed")
        return json.dumps({"status": "error", "error": str(e), "query": query})

_register("modify_database", True)


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

ALL_TOOLS = [
    search_web,
    analyze_data,
    read_file,
    send_email,
    execute_code,
    modify_database,
]

SAFE_TOOLS = [t for t in ALL_TOOLS if not _APPROVAL_REGISTRY.get(t.name, True)]
CONSEQUENTIAL_TOOLS = [t for t in ALL_TOOLS if _APPROVAL_REGISTRY.get(t.name, True)]

TOOLS_BY_NAME: dict[str, Any] = {t.name: t for t in ALL_TOOLS}


def is_consequential(tool_name: str) -> bool:
    """Check if a tool requires human approval."""
    return _APPROVAL_REGISTRY.get(tool_name, True)  # unknown tools default to True
