"""Tool definitions for the AI agent.

Each tool declares whether it is *consequential* (requires human approval)
via the _APPROVAL_REGISTRY.  The agent graph reads this to decide whether
to suspend at an approval gate before executing the tool.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Registry: tool_name -> requires_approval
_APPROVAL_REGISTRY: dict[str, bool] = {}


def _register(name: str, requires_approval: bool):
    """Register a tool's approval requirement."""
    _APPROVAL_REGISTRY[name] = requires_approval


# ---------------------------------------------------------------------------
# Safe tools — no side effects, auto-executed
# ---------------------------------------------------------------------------

@tool
def search_web(query: str) -> str:
    """Search the web for information. Safe — no side effects."""
    logger.info("search_web called with query=%s", query)
    return json.dumps({
        "results": [
            {"title": f"Result for '{query}'", "snippet": f"Relevant information about {query}."},
            {"title": f"More on '{query}'", "snippet": f"Additional details regarding {query}."},
        ]
    })

_register("search_web", False)


@tool
def analyze_data(data: str) -> str:
    """Analyze the provided data and return insights. Safe — read-only."""
    logger.info("analyze_data called")
    return json.dumps({
        "analysis": f"Analysis of the provided data: {data[:200]}",
        "summary": "The data shows interesting patterns worth investigating.",
        "confidence": 0.85,
    })

_register("analyze_data", False)


@tool
def read_file(filepath: str) -> str:
    """Read a file and return its contents. Safe — read-only."""
    logger.info("read_file called with filepath=%s", filepath)
    return f"[Simulated] Contents of {filepath}: sample data..."

_register("read_file", False)


# ---------------------------------------------------------------------------
# Consequential tools — require human approval before execution
# ---------------------------------------------------------------------------

@tool
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email to the specified recipient. CONSEQUENTIAL — requires human approval."""
    logger.info("send_email called: to=%s subject=%s", to, subject)
    return json.dumps({
        "status": "sent",
        "to": to,
        "subject": subject,
        "message_id": "msg-sim-001",
    })

_register("send_email", True)


@tool
def execute_code(code: str, language: str = "python") -> str:
    """Execute code in the specified language. CONSEQUENTIAL — requires human approval."""
    logger.info("execute_code called: language=%s", language)
    return json.dumps({
        "status": "executed",
        "language": language,
        "output": f"[Simulated] Code execution result for {language} code.",
    })

_register("execute_code", True)


@tool
def modify_database(query: str, database: str = "main") -> str:
    """Run a mutation query on the database. CONSEQUENTIAL — requires human approval."""
    logger.info("modify_database called: db=%s", database)
    return json.dumps({
        "status": "executed",
        "database": database,
        "rows_affected": 42,
    })

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
