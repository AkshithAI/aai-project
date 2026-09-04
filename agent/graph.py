"""LangGraph agent graph with human approval gates.

This graph implements a durable AI agent that:
1. Plans a multi-step approach to a task (via LLM)
2. Executes steps sequentially, checkpointing each
3. Suspends at approval gates for consequential actions (via interrupt())
4. Resumes after human approval/rejection
5. Survives process restarts (via SqliteSaver checkpointer)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal, TypedDict, Annotated

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END, add_messages
from langgraph.types import interrupt, Command

from agent.tools import ALL_TOOLS, TOOLS_BY_NAME, is_consequential

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    """State that flows through the graph. Every field is checkpointed."""
    task: str
    plan: list                     # list of step dicts
    current_step: int
    completed_steps: list          # list of result dicts
    pending_action: dict | None
    approval_decision: str | None  # approved | rejected | expired
    final_result: str | None
    messages: Annotated[list, add_messages]
    error: str | None


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def plan_node(state: AgentState, config: RunnableConfig) -> dict:
    """Use the LLM to create a step-by-step plan for the task.

    Each step is tagged as requiring approval or not based on the tool
    it will use.
    """
    from agent.llm import get_llm

    task = state["task"]
    llm = get_llm(config)

    tool_descriptions = "\n".join(
        f"- {t.name} (requires_approval={is_consequential(t.name)}): {t.description}"
        for t in ALL_TOOLS
    )


    system_prompt = f"""You are a planning agent. Given a task, create a step-by-step plan.

Available tools:
{tool_descriptions}

Return a JSON array of steps. Each step must have:
- "description": what this step does
- "tool_name": which tool to use
- "tool_args": dict of arguments for the tool
- "requires_approval": true if the tool is consequential
- "risk_level": "low", "medium", "high", or "critical"

Return ONLY the JSON array, no other text."""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Task: {task}"),
    ]

    response = llm.invoke(messages)
    content = response.content.strip()

    # Parse the plan from LLM response
    # Handle markdown code blocks
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1])

    try:
        plan_steps = json.loads(content)
    except json.JSONDecodeError:
        logger.error("Failed to parse plan from LLM: %s", content)
        plan_steps = [
            {
                "description": f"Execute the task: {task}",
                "tool_name": "search_web",
                "tool_args": {"query": task},
                "requires_approval": False,
                "risk_level": "low",
            }
        ]

    # Ensure indices
    for i, step in enumerate(plan_steps):
        step["index"] = i
        # Override requires_approval based on tool metadata
        step["requires_approval"] = is_consequential(step.get("tool_name", ""))

    logger.info("Plan created with %d steps", len(plan_steps))

    return {
        "plan": plan_steps,
        "current_step": 0,
        "completed_steps": [],
        "pending_action": None,
        "approval_decision": None,
        "final_result": None,
        "error": None,
        "messages": [
            SystemMessage(content="You are a helpful AI agent executing a plan step by step."),
            HumanMessage(content=f"Task: {task}"),
            AIMessage(content=f"Plan created with {len(plan_steps)} steps."),
        ],
    }


def execute_node(state: AgentState) -> dict | Command:
    """Execute the current step.

    If the step requires approval, route to the approval_gate node.
    Otherwise, execute the tool and advance.
    """
    plan = state["plan"]
    current = state["current_step"]

    if current >= len(plan):
        # All steps done — shouldn't normally reach here due to routing
        return {"final_result": "All steps completed."}

    step = plan[current]
    tool_name = step.get("tool_name", "")

    # If this tool requires approval, route to the gate
    if step.get("requires_approval", False):
        logger.info("Step %d (%s) requires approval — routing to gate", current, tool_name)
        return {
            "pending_action": {
                "step_index": current,
                "tool_name": tool_name,
                "tool_args": step.get("tool_args", {}),
                "description": step.get("description", ""),
                "risk_level": step.get("risk_level", "medium"),
            }
        }

    # Safe tool — execute directly
    logger.info("Executing safe step %d: %s", current, tool_name)
    result = _call_tool(tool_name, step.get("tool_args", {}))

    completed = list(state.get("completed_steps", []))
    completed.append({
        "step_index": current,
        "tool_name": tool_name,
        "output": result,
        "status": "completed",
    })

    return {
        "current_step": current + 1,
        "completed_steps": completed,
        "pending_action": None,
    }


def approval_gate_node(state: AgentState) -> dict:
    """Suspend execution and wait for human approval.

    The interrupt() call persists the graph state and blocks until
    the graph is resumed with Command(resume=...).
    """
    pending = state.get("pending_action")
    if not pending:
        return {"approval_decision": "rejected", "error": "No pending action"}

    logger.info(
        "Suspending for approval: step %d, tool=%s",
        pending["step_index"],
        pending["tool_name"],
    )

    # --- THIS IS THE SUSPENSION POINT ---
    # The graph state is saved to SQLite here.
    # The process can crash and restart — state survives.
    decision = interrupt({
        "action": pending["tool_name"],
        "args": pending["tool_args"],
        "description": pending["description"],
        "risk_level": pending.get("risk_level", "medium"),
        "message": "Human approval required for this action.",
    })

    # We reach here only after Command(resume=...) is called
    status = decision.get("status", "rejected") if isinstance(decision, dict) else str(decision)

    if status == "approved":
        logger.info("Action approved — executing %s", pending["tool_name"])
        result = _call_tool(pending["tool_name"], pending.get("tool_args", {}))
        completed = list(state.get("completed_steps", []))
        completed.append({
            "step_index": pending["step_index"],
            "tool_name": pending["tool_name"],
            "output": result,
            "status": "completed",
        })
        return {
            "current_step": state["current_step"] + 1,
            "completed_steps": completed,
            "pending_action": None,
            "approval_decision": "approved",
        }
    elif status == "expired":
        logger.warning("Approval expired for step %d", pending["step_index"])
        return {
            "approval_decision": "expired",
            "pending_action": None,
            "error": "Approval window expired (TTL exceeded).",
        }
    else:
        logger.info("Action rejected for step %d", pending["step_index"])
        return {
            "approval_decision": "rejected",
            "pending_action": None,
        }


def finalize_node(state: AgentState) -> dict:
    """Summarize the completed steps and produce a final result."""
    completed = state.get("completed_steps", [])
    decision = state.get("approval_decision")

    if decision in ("rejected", "expired"):
        summary = f"Agent run ended: {decision}. Completed {len(completed)} step(s) before stopping."
    else:
        summary = f"Agent run completed successfully. Executed {len(completed)} step(s)."

    step_summaries = []
    for s in completed:
        step_summaries.append(f"  Step {s['step_index']}: {s['tool_name']} -> {s['status']}")

    full_result = summary + "\n" + "\n".join(step_summaries) if step_summaries else summary

    logger.info("Finalized: %s", summary)
    return {"final_result": full_result}


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------

def route_after_execute(state: AgentState) -> Literal["execute", "approval_gate", "finalize"]:
    """Decide where to go after the execute node."""
    # If there's a pending action, go to approval gate
    if state.get("pending_action"):
        return "approval_gate"

    # If all steps are done, finalize
    plan = state.get("plan", [])
    current = state.get("current_step", 0)
    if current >= len(plan):
        return "finalize"

    # More steps to execute
    return "execute"


def route_after_approval(state: AgentState) -> Literal["execute", "finalize"]:
    """Decide where to go after the approval gate."""
    decision = state.get("approval_decision")

    if decision in ("rejected", "expired"):
        return "finalize"

    # Approved — continue executing remaining steps
    plan = state.get("plan", [])
    current = state.get("current_step", 0)
    if current >= len(plan):
        return "finalize"

    return "execute"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph(checkpointer=None):
    """Build and compile the LangGraph agent with optional checkpointer."""
    builder = StateGraph(AgentState)

    # Add nodes
    builder.add_node("plan", plan_node)
    builder.add_node("execute", execute_node)
    builder.add_node("approval_gate", approval_gate_node)
    builder.add_node("finalize", finalize_node)

    # Add edges
    builder.add_edge(START, "plan")
    builder.add_edge("plan", "execute")
    builder.add_conditional_edges("execute", route_after_execute)
    builder.add_conditional_edges("approval_gate", route_after_approval)
    builder.add_edge("finalize", END)

    # Compile with checkpointer for durable execution
    graph = builder.compile(checkpointer=checkpointer)
    return graph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _call_tool(tool_name: str, tool_args: dict[str, Any]) -> str:
    """Invoke a tool by name with the given arguments."""
    tool_fn = TOOLS_BY_NAME.get(tool_name)
    if tool_fn is None:
        logger.error("Unknown tool: %s", tool_name)
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    try:
        result = tool_fn.invoke(tool_args)
        return result if isinstance(result, str) else str(result)
    except Exception as e:
        logger.exception("Tool %s failed", tool_name)
        return json.dumps({"error": str(e)})
