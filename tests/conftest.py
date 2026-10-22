from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from safeops.audit import AuditLog
from safeops.bootstrap import seed_all
from safeops.db import Database
from safeops.runner import AgentRunner


@pytest.fixture
def db() -> Database:
    database = Database("sqlite:///:memory:")
    seed_all(database)
    return database


@pytest.fixture
def audit(tmp_path) -> AuditLog:
    return AuditLog(tmp_path / "audit.jsonl")


def call(name: str, call_id: str = "call_1", **args) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def say(text: str) -> AIMessage:
    return AIMessage(content=text)


def result_of(domain, db: Database, tool: str, **args) -> dict:
    return json.loads(domain.run_tool(db.session_factory, tool, args))


@pytest.fixture
def make_runner(db, audit) -> Callable[[list[AIMessage]], AgentRunner]:
    def factory(script: list[AIMessage], preflight: bool = True) -> AgentRunner:
        llm = FakeMessagesListChatModel(responses=script)
        return AgentRunner(db, audit, llm_factory=lambda _domain: llm, preflight=preflight)

    return factory
