"""LLM client wrapper.

Supports both real OpenAI API and a fake/mock mode for testing
without an API key.
"""

from __future__ import annotations

import os
from typing import Any

from langchain_core.language_models import BaseChatModel


def get_llm(config: dict | None = None) -> BaseChatModel:
    """Get an LLM instance based on configuration.

    If OPENAI_API_KEY is not set or config specifies mock mode,
    returns a FakeListChatModel for testing.
    """
    configurable = (config or {}).get("configurable", {})
    use_mock = configurable.get("mock_llm", False)

    api_key = os.getenv("GROQ_API_KEY", "")

    if use_mock or not api_key:
        return _get_mock_llm(configurable)

    from langchain_groq import ChatGroq
    import config as app_config

    return ChatGroq(
        model=configurable.get("model", app_config.LLM_MODEL),
        api_key=api_key,
        temperature=0,
    )


def _get_mock_llm(configurable: dict) -> BaseChatModel:
    """Return a deterministic mock LLM for testing."""
    from langchain_core.language_models import FakeListChatModel

    # Default mock plan — a realistic multi-step workflow
    default_plan = """[
  {
    "description": "Search the web for relevant information",
    "tool_name": "search_web",
    "tool_args": {"query": "requested topic"},
    "requires_approval": false,
    "risk_level": "low"
  },
  {
    "description": "Analyze the gathered data",
    "tool_name": "analyze_data",
    "tool_args": {"data": "search results"},
    "requires_approval": false,
    "risk_level": "low"
  },
  {
    "description": "Send summary email to the team",
    "tool_name": "send_email",
    "tool_args": {"to": "team@example.com", "subject": "Summary Report", "body": "Here are the findings..."},
    "requires_approval": true,
    "risk_level": "medium"
  }
]"""

    mock_responses = configurable.get("mock_responses", [default_plan])

    return FakeListChatModel(responses=mock_responses)
