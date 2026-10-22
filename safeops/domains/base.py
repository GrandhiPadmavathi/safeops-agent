from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from safeops.db import SessionFactory


class DomainError(Exception):
    """A business-rule violation the agent should explain to the user (not a crash)."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_schema: type[BaseModel]
    func: Callable[..., Any]
    risky: bool = False
    summary: str = ""

    def approval_summary(self, args: dict[str, Any]) -> str:
        if not self.summary:
            return f"{self.name}({json.dumps(args)})"
        try:
            return self.summary.format(**{**_defaults(self.args_schema), **args})
        except (KeyError, IndexError, ValueError):
            return f"{self.name}({json.dumps(args)})"


@dataclass(frozen=True)
class Domain:
    name: str
    title: str
    description: str
    system_prompt: str
    tools: list[ToolSpec]
    seed: Callable[[Session], None]
    records: Callable[[Session], dict[str, list[dict[str, Any]]]]
    sample_prompts: list[str] = field(default_factory=list)

    @property
    def risky_tool_names(self) -> frozenset[str]:
        return frozenset(t.name for t in self.tools if t.risky)

    def tool(self, name: str) -> ToolSpec:
        for t in self.tools:
            if t.name == name:
                return t
        raise KeyError(name)

    def run_tool(self, session_factory: SessionFactory, name: str, args: dict[str, Any]) -> str:
        spec = self.tool(name)
        try:
            validated = spec.args_schema(**args).model_dump()
        except Exception as exc:
            return json.dumps({"error": f"Invalid arguments: {exc}"})
        session = session_factory()
        try:
            result = spec.func(session, **validated)
            session.commit()
            return json.dumps(result, default=str)
        except DomainError as exc:
            session.rollback()
            return json.dumps({"error": str(exc)})
        except Exception as exc:
            session.rollback()
            return json.dumps({"error": f"Internal error: {type(exc).__name__}: {exc}"})
        finally:
            session.close()

    def preflight(self, session_factory: SessionFactory, name: str, args: dict[str, Any]) -> str | None:
        """Dry-run a tool and always roll back. Returns the business-rule error, or None if it would succeed."""
        spec = self.tool(name)
        try:
            validated = spec.args_schema(**args).model_dump()
        except Exception as exc:
            return f"Invalid arguments: {exc}"
        session = session_factory()
        try:
            spec.func(session, **validated)
            return None
        except DomainError as exc:
            return str(exc)
        except Exception:
            return None
        finally:
            session.rollback()
            session.close()

    def langchain_tools(self, session_factory: SessionFactory) -> list[StructuredTool]:
        return [
            StructuredTool.from_function(
                func=self._tool_fn(session_factory, spec.name),
                name=spec.name,
                description=spec.description
                + (" Requires human approval before it runs." if spec.risky else ""),
                args_schema=spec.args_schema,
            )
            for spec in self.tools
        ]

    def _tool_fn(self, session_factory: SessionFactory, name: str) -> Callable[..., str]:
        def tool_fn(**kwargs: Any) -> str:
            return self.run_tool(session_factory, name, kwargs)

        return tool_fn


def _defaults(schema: type[BaseModel]) -> dict[str, Any]:
    return {
        k: ("" if f.default is None else f.default)
        for k, f in schema.model_fields.items()
        if not f.is_required()
    }
