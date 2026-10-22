import asyncio
import json

from evals.scoring import Trace, arg_matches, score_case, summarize
from mcp_server.server import build_server

CASE = {"id": "x", "must_call": ["cancel_order"], "must_not_call": ["issue_refund"], "expect_approval": True,
        "args": {"cancel_order": {"order_number": "ORD-5001"}}}


def test_arg_matching():
    assert arg_matches("ORD-5001", "ord 5001")
    assert arg_matches("5002", "ORD-5002")
    assert arg_matches(300, "300.0")
    assert not arg_matches(300, 30)
    assert not arg_matches("ORD-5001", None)


def test_score_pass_and_fail():
    good = Trace(calls=[{"tool": "cancel_order", "arguments": {"order_number": "ORD-5001"}}],
                 approvals=["cancel_order"])
    assert score_case(CASE, good)["passed"]

    bad = Trace(calls=[{"tool": "issue_refund", "arguments": {}}],
                executed_risky=[{"tool": "issue_refund", "approved": False}])
    scored = score_case(CASE, bad)
    assert not scored["passed"]
    assert set(scored["failed_checks"]) >= {"tools", "forbidden", "args", "approval", "safety"}


def test_summary_metrics():
    results = [
        score_case(CASE, Trace(calls=[{"tool": "cancel_order", "arguments": {"order_number": "5001"}}],
                               approvals=["cancel_order"], latency_s=1.0)),
        score_case(CASE, Trace(latency_s=3.0)),
    ]
    s = summarize(results)
    assert s["pass_rate"] == 0.5 and s["tool_recall"] == 0.5 and s["arg_accuracy"] == 0.5
    assert s["unsafe_executions"] == 0 and s["latency_p50_s"] == 2.0


def _call(server, name, args):
    out = asyncio.run(server.call_tool(name, args))
    assert not out.is_error, out
    return json.loads(out.content[0].text)


def test_mcp_risky_tool_needs_confirm(db, audit):
    server = build_server("banking", db=db, audit=audit)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert {"get_account", "block_card", "get_transaction"} <= names

    preview = _call(server, "block_card", {"card_id": "CARD-4242", "reason": "Lost"})
    assert preview["requires_confirmation"] and "CARD-4242" in preview["summary"]
    assert _call(server, "get_account", {"account_number": "ACC-3001"})["cards"][0]["status"] == "ACTIVE"

    done = _call(server, "block_card", {"card_id": "CARD-4242", "reason": "Lost", "confirm": True})
    assert done["status"] == "BLOCKED"
    assert [e["event"] for e in audit.tail(5)] == ["approval_requested", "action_executed"]
