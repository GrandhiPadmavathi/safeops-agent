"""Expose one SafeOps domain as MCP tools.

Risky tools only return a preview unless called with ``confirm=true``, so an MCP client
(Claude Desktop, Cursor, ...) has to show the action to its user before it runs.
"""
from __future__ import annotations

import argparse
import inspect
import json
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from safeops.audit import AuditLog
from safeops.bootstrap import seed_all
from safeops.config import settings
from safeops.db import Database
from safeops.domains import DOMAINS, Domain, ToolSpec, get_domain


def _signature(spec: ToolSpec) -> inspect.Signature:
    params = []
    for name, f in spec.args_schema.model_fields.items():
        default = inspect.Parameter.empty if f.is_required() else f.default
        params.append(inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, default=default,
                                        annotation=f.annotation))
    if spec.risky:
        params.append(inspect.Parameter("confirm", inspect.Parameter.KEYWORD_ONLY, default=False,
                                        annotation=bool))
    return inspect.Signature(params, return_annotation=str)


def make_tool(domain: Domain, spec: ToolSpec, db: Database, audit: AuditLog):
    def tool(**kwargs: Any) -> str:
        confirm = bool(kwargs.pop("confirm", False))
        args = {k: v for k, v in kwargs.items() if v is not None}
        if spec.risky and not confirm:
            summary = spec.approval_summary(args)
            audit.record("approval_requested", channel="mcp", domain=domain.name, tool=spec.name,
                         arguments=args, summary=summary)
            return json.dumps({
                "requires_confirmation": True,
                "summary": summary,
                "next_step": "Show this to the user. Only if they agree, call again with confirm=true.",
            })
        result = domain.run_tool(db.session_factory, spec.name, args)
        if spec.risky:
            audit.record("action_executed", channel="mcp", domain=domain.name, tool=spec.name,
                         arguments=args, result=json.loads(result))
        return result

    sig = _signature(spec)
    tool.__name__ = spec.name
    tool.__signature__ = sig
    tool.__annotations__ = {p.name: p.annotation for p in sig.parameters.values()} | {"return": str}
    return tool


def build_server(domain_name: str, db: Database | None = None, audit: AuditLog | None = None) -> MCPServer:
    domain = get_domain(domain_name)
    db = db or Database(settings.database_url)
    audit = audit or AuditLog(settings.audit_log_path)
    seed_all(db)

    server = MCPServer(f"safeops-{domain.name}", instructions=domain.description)
    for spec in domain.tools:
        description = spec.description + (
            " Risky: returns a preview unless confirm=true; only confirm after the user agrees."
            if spec.risky else ""
        )
        server.add_tool(
            make_tool(domain, spec, db, audit), name=spec.name, description=description,
            annotations=ToolAnnotations(read_only_hint=not spec.risky, destructive_hint=spec.risky),
            structured_output=False,
        )
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a SafeOps domain as an MCP server (stdio).")
    parser.add_argument("--domain", choices=sorted(DOMAINS), default="ecommerce")
    build_server(parser.parse_args().domain).run()


if __name__ == "__main__":
    main()
