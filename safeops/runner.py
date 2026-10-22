from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from safeops.agent import BLOCKED_PREFIX, REJECTED_MESSAGE, build_graph, tool_args
from safeops.audit import AuditLog
from safeops.db import Database
from safeops.domains import get_domain
from safeops.llm import make_llm


def _parse(content: Any) -> Any:
    if isinstance(content, str):
        try:
            return json.loads(content)
        except ValueError:
            return content
    return content


class AgentRunner:
    """Runs conversations for any domain and turns graph state into UI-friendly events."""

    def __init__(
        self,
        db: Database,
        audit: AuditLog,
        llm_factory: Callable[[str], Any] | None = None,
        preflight: bool | None = None,
    ) -> None:
        self.db = db
        self.audit = audit
        self.llm_factory = llm_factory or (lambda _domain: make_llm())
        self.preflight = preflight
        self.checkpointer = MemorySaver()
        self._graphs: dict[str, Any] = {}
        self._thread_domain: dict[str, str] = {}
        self._lock = threading.Lock()

    def _graph(self, domain_name: str):
        with self._lock:
            if domain_name not in self._graphs:
                domain = get_domain(domain_name)
                self._graphs[domain_name] = build_graph(
                    domain, self.db.session_factory, self.llm_factory(domain_name),
                    checkpointer=self.checkpointer, preflight=self.preflight,
                )
            return self._graphs[domain_name]

    @staticmethod
    def _config(thread_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}}

    def chat(self, domain_name: str, message: str, thread_id: str | None = None) -> dict[str, Any]:
        get_domain(domain_name)
        thread_id = thread_id or str(uuid.uuid4())
        known = self._thread_domain.get(thread_id)
        if known and known != domain_name:
            raise ValueError(f"Thread {thread_id} belongs to domain '{known}'.")
        if self.pending_approval(thread_id):
            raise ValueError("This conversation is waiting for an approval decision first.")
        self._thread_domain[thread_id] = domain_name
        state = {"messages": [HumanMessage(content=message)], "step_count": 0, "approved_tool_call_ids": []}
        return self._run(domain_name, thread_id, state)

    def approve(self, thread_id: str, approved: bool, reviewer: str = "reviewer", note: str = "") -> dict[str, Any]:
        domain_name = self._thread_domain.get(thread_id)
        pending = self.pending_approval(thread_id) if domain_name else None
        if not pending:
            raise ValueError("There is no action waiting for approval in this conversation.")
        self.audit.record(
            "approval_decision", thread_id=thread_id, domain=domain_name, tool=pending["tool_name"],
            arguments=pending["arguments"], summary=pending["summary"],
            decision="approved" if approved else "rejected", reviewer=reviewer, note=note,
        )
        return self._run(domain_name, thread_id, Command(resume={"approved": approved}))

    def pending_approval(self, thread_id: str) -> dict[str, Any] | None:
        domain_name = self._thread_domain.get(thread_id)
        if not domain_name:
            return None
        snapshot = self._graph(domain_name).get_state(self._config(thread_id))
        for intr in snapshot.interrupts:
            if isinstance(intr.value, dict) and intr.value.get("type") == "approval_required":
                return intr.value
        return None

    def _run(self, domain_name: str, thread_id: str, graph_input: Any) -> dict[str, Any]:
        graph = self._graph(domain_name)
        config = self._config(thread_id)
        before = len(graph.get_state(config).values.get("messages", []))
        graph.invoke(graph_input, config=config)
        snapshot = graph.get_state(config)
        messages = snapshot.values.get("messages", [])
        risky = get_domain(domain_name).risky_tool_names

        events: list[dict[str, Any]] = []
        for msg in messages[before:]:
            if isinstance(msg, AIMessage):
                for tc in msg.tool_calls:
                    events.append({"type": "tool_call", "tool": tc["name"], "arguments": tool_args(tc),
                                   "risky": tc["name"] in risky})
            elif isinstance(msg, ToolMessage):
                rejected = msg.content == REJECTED_MESSAGE
                result = _parse(msg.content)
                error = result.get("error", "") if isinstance(result, dict) else ""
                blocked = error.startswith(BLOCKED_PREFIX)
                events.append({"type": "tool_result", "tool": msg.name, "result": result,
                               "rejected": rejected, "blocked": blocked})
                if msg.name in risky and not rejected:
                    event = "action_blocked" if blocked else "action_failed" if error else "action_executed"
                    self.audit.record(event, thread_id=thread_id, domain=domain_name, tool=msg.name, result=result)

        pending = self.pending_approval(thread_id)
        if pending:
            self.audit.record("approval_requested", thread_id=thread_id, domain=domain_name,
                              tool=pending["tool_name"], arguments=pending["arguments"],
                              summary=pending["summary"])
            events.append({"type": "approval_required", **pending})
            return {"thread_id": thread_id, "domain": domain_name, "status": "awaiting_approval",
                    "events": events, "reply": "", "approval": pending}

        reply = ""
        for msg in reversed(messages[before:]):
            if isinstance(msg, AIMessage) and not msg.tool_calls and msg.content:
                reply = str(msg.content)
                break
        return {"thread_id": thread_id, "domain": domain_name, "status": "completed",
                "events": events, "reply": reply, "approval": None}
