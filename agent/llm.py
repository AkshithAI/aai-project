"""LLM client wrapper.

Supports real Groq API LLMs and an intelligent, task-aware mock mode
that parses the user's task to generate context-specific plans when
running without an API key or in offline testing.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, List, Optional

from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

logger = logging.getLogger(__name__)


def _extract_task_from_messages(messages: list[BaseMessage]) -> str:
    """Extract the user's task prompt from message history."""
    for msg in reversed(messages):
        content = str(msg.content)
        if "Task:" in content:
            # Extract content following "Task:"
            match = re.search(r"Task:\s*(.+)", content, re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(1).strip()
        elif msg.type == "human" or getattr(msg, "role", "") == "user":
            return content.strip()
    return ""


def _generate_dynamic_plan(task: str) -> list[dict[str, Any]]:
    """Generate a realistic, context-specific multi-step plan from the task string."""
    if not task:
        task = "Execute workflow"

    # 1. Extract email if present
    email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", task)
    email_to = email_match.group(0) if email_match else None

    # 2. Extract key topic/subject
    cleaned_task = task
    if email_to:
        cleaned_task = re.sub(rf"\b(?:to|email|send)\s+(?:the\s+summary\s+to\s+)?{re.escape(email_to)}\b", "", cleaned_task, flags=re.IGNORECASE)
    
    # Remove phrases like 'and email the summary', 'and send report'
    cleaned_task = re.sub(r"\b(?:and\s+)?(?:email|send|mail)\s+(?:the\s+)?(?:summary|report|results|findings)(?:\s+to)?\b.*$", "", cleaned_task, flags=re.IGNORECASE)

    # Remove common filler prefixes
    topic = re.sub(
        r"^(?:please\s+|can\s+you\s+|i\s+need\s+you\s+to\s+|research\s+|find\s+|look\s+up\s+|analyze\s+)",
        "",
        cleaned_task.strip(),
        flags=re.IGNORECASE,
    ).strip()

    # Clean up trailing punctuation or conjunctions
    topic = re.sub(r"\b(?:and|then|to|for|with)\s*$", "", topic, flags=re.IGNORECASE).strip()
    topic = re.sub(r"[\s,\.-]+$", "", topic).strip()

    if not topic:
        topic = task

    steps: list[dict[str, Any]] = []

    # Check for code execution tasks
    if any(k in task.lower() for k in ["execute code", "run script", "python code", "calculate", "algorithm"]):
        steps.append({
            "description": f"Prepare and execute code for: {task[:60]}",
            "tool_name": "execute_code",
            "tool_args": {"code": f"# Task: {task}\nprint('Executing algorithm for {task[:40]}...')", "language": "python"},
            "requires_approval": True,
            "risk_level": "high",
        })
    # Check for database tasks
    elif any(k in task.lower() for k in ["database", "sql", "update table", "insert into", "delete from", "modify db"]):
        steps.append({
            "description": f"Perform database operation for: {task[:60]}",
            "tool_name": "modify_database",
            "tool_args": {"query": f"UPDATE records SET status = 'updated' WHERE task LIKE '%{topic[:30]}%'", "database": "main"},
            "requires_approval": True,
            "risk_level": "high",
        })
    # Default research / analysis / communication flow
    else:
        # Step 1: Web search
        search_query = topic
        if "market trends" in task.lower() and "market trends" not in search_query.lower():
            search_query = f"{topic} market trends"

        steps.append({
            "description": f"Search web for '{search_query}'",
            "tool_name": "search_web",
            "tool_args": {"query": search_query},
            "requires_approval": False,
            "risk_level": "low",
        })

        # Step 2: Data analysis
        steps.append({
            "description": f"Analyze findings and market insights on {topic}",
            "tool_name": "analyze_data",
            "tool_args": {"data": f"Market research and competitive analysis data for {topic}"},
            "requires_approval": False,
            "risk_level": "low",
        })

        # Step 3: Send email if email address was provided or mentioned
        if email_to:
            steps.append({
                "description": f"Send comprehensive summary email to {email_to}",
                "tool_name": "send_email",
                "tool_args": {
                    "to": email_to,
                    "subject": f"Research Summary: {topic.title()}",
                    "body": f"Here is the synthesized summary and market trends report regarding {topic}.",
                },
                "requires_approval": True,
                "risk_level": "medium",
            })
        elif any(k in task.lower() for k in ["email", "send report", "notify", "mail"]):
            steps.append({
                "description": f"Send summary report regarding {topic}",
                "tool_name": "send_email",
                "tool_args": {
                    "to": "stakeholders@organization.com",
                    "subject": f"Summary Report: {topic.title()}",
                    "body": f"Here are the findings and key metrics regarding {topic}.",
                },
                "requires_approval": True,
                "risk_level": "medium",
            })

    return steps


class DynamicMockChatModel(BaseChatModel):
    """A context-aware mock LLM that generates tailored plans based on the user's task."""

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        task = _extract_task_from_messages(messages)
        plan_steps = _generate_dynamic_plan(task)
        json_output = json.dumps(plan_steps, indent=2)

        message = AIMessage(content=json_output)
        generation = ChatGeneration(message=message)
        return ChatResult(generations=[generation])

    @property
    def _llm_type(self) -> str:
        return "dynamic-mock-chat-model"


def get_llm(config: dict | None = None) -> BaseChatModel:
    """Get an LLM instance based on configuration.

    If GROQ_API_KEY is not set or config specifies mock mode,
    returns DynamicMockChatModel which dynamically tailors plans to user tasks.
    """
    configurable = (config or {}).get("configurable", {})
    use_mock = configurable.get("mock_llm", False)

    api_key = os.getenv("GROQ_API_KEY", "").strip()

    # If mock is explicitly requested or no valid key is provided
    if use_mock or not api_key or api_key.startswith("gsk_your_groq"):
        return DynamicMockChatModel()

    from langchain_groq import ChatGroq
    import config as app_config

    model_name = configurable.get("model") or getattr(app_config, "LLM_MODEL", "llama-3.3-70b-versatile")

    try:
        return ChatGroq(
            model=model_name,
            api_key=api_key,
            temperature=0,
        )
    except Exception as e:
        logger.warning("Failed to initialize ChatGroq (%s), falling back to dynamic mock: %s", model_name, e)
        return DynamicMockChatModel()

