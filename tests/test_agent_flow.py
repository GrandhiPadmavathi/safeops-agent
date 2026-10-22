import pytest

from safeops.agent import REJECTED_MESSAGE
from safeops.domains import get_domain
from tests.conftest import call, result_of, say

RISKY_CASES = [
    pytest.param(
        "ecommerce", call("cancel_order", order_number="ORD-5001", reason="Changed mind"),
        lambda db: result_of(get_domain("ecommerce"), db, "get_order", order_number="ORD-5001")["status"],
        "PLACED", "CANCELLED", id="ecommerce-cancel",
    ),
    pytest.param(
        "banking", call("block_card", card_id="CARD-4242", reason="Lost"),
        lambda db: next(c["status"] for c in result_of(get_domain("banking"), db, "get_account",
                                                       account_number="ACC-3001")["cards"]),
        "ACTIVE", "BLOCKED", id="banking-block-card",
    ),
]


@pytest.mark.parametrize("domain, risky_call, read_state, before, after", RISKY_CASES)
def test_risky_action_pauses_then_runs_when_approved(make_runner, db, audit, domain, risky_call,
                                                     read_state, before, after):
    runner = make_runner([risky_call, say("Done.")])
    first = runner.chat(domain, "please do it")

    assert first["status"] == "awaiting_approval"
    assert first["approval"]["tool_name"] == risky_call.tool_calls[0]["name"]
    assert first["approval"]["summary"]
    assert read_state(db) == before, "nothing may change before approval"

    second = runner.approve(first["thread_id"], True, reviewer="lead")
    assert second["status"] == "completed"
    assert second["reply"] == "Done."
    assert read_state(db) == after
    events = [e["event"] for e in audit.tail(10)]
    assert events == ["approval_requested", "approval_decision", "action_executed"]


@pytest.mark.parametrize("domain, risky_call, read_state, before, after", RISKY_CASES)
def test_rejected_action_never_runs(make_runner, db, domain, risky_call, read_state, before, after):
    runner = make_runner([risky_call, say("Okay, I did not change anything.")])
    first = runner.chat(domain, "please do it")
    second = runner.approve(first["thread_id"], False, note="not verified")

    assert second["status"] == "completed"
    assert read_state(db) == before
    result = next(e for e in second["events"] if e["type"] == "tool_result")
    assert result["rejected"] and result["result"] == REJECTED_MESSAGE


@pytest.mark.parametrize("domain, tool, args", [
    ("ecommerce", "get_order", {"order_number": "ORD-5003"}),
    ("banking", "list_transactions", {"account_number": "ACC-3001"}),
])
def test_safe_tools_run_without_approval(make_runner, domain, tool, args):
    runner = make_runner([call(tool, **args), say("Here you go.")])
    out = runner.chat(domain, "look it up")
    assert out["status"] == "completed"
    assert [e["type"] for e in out["events"]] == ["tool_call", "tool_result"]
    assert "error" not in out["events"][1]["result"]


def test_two_risky_calls_need_two_decisions(make_runner, db):
    from langchain_core.messages import AIMessage

    both = AIMessage(content="", tool_calls=[
        {"name": "block_card", "args": {"card_id": "CARD-4242", "reason": "Stolen"}, "id": "a", "type": "tool_call"},
        {"name": "freeze_account", "args": {"account_number": "ACC-3001", "reason": "Fraud"}, "id": "b",
         "type": "tool_call"},
    ])
    runner = make_runner([both, say("Card blocked; freeze was declined.")])
    first = runner.chat("banking", "my card was stolen, lock everything")
    assert first["approval"]["tool_name"] == "block_card"
    second = runner.approve(first["thread_id"], True)
    assert second["status"] == "awaiting_approval"
    assert second["approval"]["tool_name"] == "freeze_account"
    third = runner.approve(first["thread_id"], False)
    assert third["status"] == "completed"

    account = result_of(get_domain("banking"), db, "get_account", account_number="ACC-3001")
    assert account["status"] == "ACTIVE"
    assert account["cards"][0]["status"] == "BLOCKED"


def test_preflight_blocks_rule_breaking_action_without_bothering_reviewer(make_runner, db, audit):
    script = [call("reverse_transaction", transaction_ref="TXN-7002"), say("That needs the disputes team.")]
    runner = make_runner(script)
    out = runner.chat("banking", "reverse TXN-7002")

    assert out["status"] == "completed"
    result = next(e for e in out["events"] if e["type"] == "tool_result")
    assert result["blocked"] and "disputes team" in result["result"]["error"]
    assert [e["event"] for e in audit.tail(5)] == ["action_blocked"]
    txn = result_of(get_domain("banking"), db, "get_transaction", transaction_ref="TXN-7002")
    assert txn["status"] == "POSTED"


def test_preflight_does_not_mutate_and_valid_action_still_pauses(make_runner, db):
    runner = make_runner([call("reverse_transaction", transaction_ref="TXN-7001"), say("ok")])
    out = runner.chat("banking", "reverse TXN-7001")
    assert out["status"] == "awaiting_approval"
    txn = result_of(get_domain("banking"), db, "get_transaction", transaction_ref="TXN-7001")
    assert txn["status"] == "POSTED", "the dry run must roll back"


def test_without_preflight_reviewer_sees_rule_breaking_action(make_runner):
    runner = make_runner([call("reverse_transaction", transaction_ref="TXN-7002"), say("ok")], preflight=False)
    assert runner.chat("banking", "reverse TXN-7002")["status"] == "awaiting_approval"


def test_step_limit_stops_loops(make_runner):
    runner = make_runner([call("get_order", order_number="ORD-5001")])
    out = runner.chat("ecommerce", "loop forever")
    assert out["status"] == "completed"
    assert "step limit" in out["reply"]


def test_runner_guards(make_runner):
    runner = make_runner([call("cancel_order", order_number="ORD-5001"), say("ok")])
    first = runner.chat("ecommerce", "cancel ORD-5001")
    with pytest.raises(ValueError, match="waiting for an approval"):
        runner.chat("ecommerce", "hello again", first["thread_id"])
    with pytest.raises(ValueError, match="belongs to domain"):
        runner.chat("banking", "hi", first["thread_id"])
    with pytest.raises(ValueError, match="no action waiting"):
        runner.approve("unknown-thread", True)
    with pytest.raises(KeyError):
        runner.chat("insurance", "hi")


def test_followup_reply_is_from_current_turn(make_runner):
    runner = make_runner([say("First answer."), call("get_order", order_number="ORD-9999"), say("")])
    first = runner.chat("ecommerce", "hi")
    second = runner.chat("ecommerce", "check ORD-9999", first["thread_id"])
    assert first["reply"] == "First answer."
    assert second["reply"] == ""
