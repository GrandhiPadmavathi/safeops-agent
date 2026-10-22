from __future__ import annotations

import json
import operator
from typing import Annotated, Any, Literal

from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.types import interrupt
from typing_extensions import TypedDict

from safeops.config import settings
from safeops.db import SessionFactory
from safeops.domains.base import Domain

REJECTED_MESSAGE = "Action rejected by the human reviewer. Nothing was changed."
BLOCKED_PREFIX = "Blocked by policy before approval: "


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    step_count: int
    approved_tool_call_ids: Annotated[list[str], operator.add]


def tool_args(tool_call: dict[str, Any]) -> dict[str, Any]:
    args = tool_call.get("args")
    if args is not None:
        return args
    raw = tool_call.get("function", {}).get("arguments", "{}")
    return json.loads(raw) if isinstance(raw, str) else raw


def _bind(llm: Any, tools: list) -> Any:
    try:
        return llm.bind_tools(tools)
    except NotImplementedError:
        return llm  # scripted fakes in tests emit tool calls without binding


def build_graph(
    domain: Domain,
    session_factory: SessionFactory,
    llm: Any,
    *,
    checkpointer: MemorySaver | None = None,
    max_steps: int | None = None,
    preflight: bool | None = None,
):
    tools = domain.langchain_tools(session_factory)
    tool_node = ToolNode(tools)
    model = _bind(llm, tools)
    risky = domain.risky_tool_names
    limit = max_steps or settings.agent_max_steps
    check_first = settings.agent_preflight if preflight is None else preflight

    def agent(state: AgentState, config: RunnableConfig):
        steps = state.get("step_count", 0)
        if steps >= limit:
            return {
                "messages": [AIMessage(content="I hit my step limit for this request. Please narrow it down.")],
                "step_count": steps + 1,
            }
        response = model.invoke([SystemMessage(content=domain.system_prompt), *state["messages"]], config)
        return {"messages": [response], "step_count": steps + 1}

    def human_approval(state: AgentState):
        last = state["messages"][-1]
        approved_ids = set(state.get("approved_tool_call_ids") or [])
        rejections: list[ToolMessage] = []
        newly_approved: list[str] = []
        for tc in last.tool_calls:
            if tc["name"] not in risky or tc["id"] in approved_ids:
                continue
            args = tool_args(tc)
            problem = domain.preflight(session_factory, tc["name"], args) if check_first else None
            if problem:
                rejections.append(ToolMessage(content=json.dumps({"error": BLOCKED_PREFIX + problem}),
                                              tool_call_id=tc["id"], name=tc["name"]))
                continue
            decision = interrupt(
                {
                    "type": "approval_required",
                    "domain": domain.name,
                    "tool_name": tc["name"],
                    "tool_call_id": tc["id"],
                    "arguments": args,
                    "summary": domain.tool(tc["name"]).approval_summary(args),
                }
            )
            if decision and decision.get("approved"):
                newly_approved.append(tc["id"])
            else:
                rejections.append(ToolMessage(content=REJECTED_MESSAGE, tool_call_id=tc["id"], name=tc["name"]))
        update: dict[str, Any] = {}
        if newly_approved:
            update["approved_tool_call_ids"] = newly_approved
        if rejections:
            update["messages"] = rejections
        return update

    def execute_tools(state: AgentState, config: RunnableConfig):
        messages = state["messages"]
        idx = max(i for i, m in enumerate(messages) if isinstance(m, AIMessage))
        last_ai = messages[idx]
        answered = {m.tool_call_id for m in messages[idx + 1:] if isinstance(m, ToolMessage)}
        approved_ids = set(state.get("approved_tool_call_ids") or [])
        runnable = [
            tc for tc in last_ai.tool_calls
            if tc["id"] not in answered and (tc["name"] not in risky or tc["id"] in approved_ids)
        ]
        if not runnable:
            return {}
        filtered = AIMessage(content=last_ai.content, tool_calls=runnable, id=last_ai.id)
        return tool_node.invoke({**state, "messages": [*messages[:idx], filtered]}, config)

    def after_agent(state: AgentState) -> Literal["human_approval", "__end__"]:
        return "human_approval" if tools_condition(state) == "tools" else END

    builder = StateGraph(AgentState)
    builder.add_node("agent", agent)
    builder.add_node("human_approval", human_approval)
    builder.add_node("execute_tools", execute_tools)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", after_agent)
    builder.add_edge("human_approval", "execute_tools")
    builder.add_edge("execute_tools", "agent")
    return builder.compile(checkpointer=checkpointer or MemorySaver())
