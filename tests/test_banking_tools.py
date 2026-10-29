from safeops.domains import get_domain
from tests.conftest import result_of

BANK = get_domain("banking")


def test_find_customer_lists_accounts(db):
    out = result_of(BANK, db, "find_customer", customer_ref="b-2001")
    assert out["found"]
    assert out["accounts"][0]["account_number"].startswith("ACC-")


def test_unknown_customer(db):
    assert result_of(BANK, db, "find_customer", customer_ref="B-9999") == {"found": False}


def test_list_transactions_limit(db):
    out = result_of(BANK, db, "list_transactions", account_number="ACC-3001", limit=1)
    assert len(out["transactions"]) == 1


def test_block_card_once(db):
    ok = result_of(BANK, db, "block_card", card_id="card 4242", reason="Lost")
    assert ok["status"] == "BLOCKED"
    assert "already blocked" in result_of(BANK, db, "block_card", card_id="CARD-4242")["error"]


def test_reverse_small_transaction_credits_balance(db):
    before = result_of(BANK, db, "get_account", account_number="ACC-3001")["balance"]
    out = result_of(BANK, db, "reverse_transaction", transaction_ref="TXN-7001")
    assert out["status"] == "REVERSED"
    assert out["new_balance"] == round(before + out["credited"], 2)


def test_reversal_guards(db):
    assert "disputes team" in result_of(BANK, db, "reverse_transaction", transaction_ref="TXN-7002")["error"]
    assert "only POSTED" in result_of(BANK, db, "reverse_transaction", transaction_ref="TXN-7005")["error"]


def test_frozen_account_blocks_reversal(db):
    assert "FROZEN" in result_of(BANK, db, "reverse_transaction", transaction_ref="TXN-7007")["error"]


def test_frozen_account_blocks_card_changes(db):
    result_of(BANK, db, "freeze_account", account_number="ACC-3001", reason="Suspected fraud")
    assert "FROZEN" in result_of(BANK, db, "block_card", card_id="CARD-4242", reason="Lost")["error"]
    assert "FROZEN" in result_of(BANK, db, "block_card", card_id="CARD-7777", reason="Lost")["error"]


def test_freeze_requires_reason(db):
    assert "Invalid arguments" in result_of(BANK, db, "freeze_account", account_number="ACC-3002")["error"]
    ok = result_of(BANK, db, "freeze_account", account_number="ACC-3002", reason="Suspected fraud")
    assert ok["status"] == "FROZEN"
    assert "already frozen" in result_of(BANK, db, "freeze_account", account_number="ACC-3002",
                                         reason="Again")["error"]
