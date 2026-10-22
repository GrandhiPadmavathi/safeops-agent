import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from tests.conftest import call, say


@pytest.fixture
def client_for(make_runner):
    def factory(script):
        runner = make_runner(script)
        return TestClient(create_app(runner=runner))

    return factory


def test_health_and_domains(client_for):
    with client_for([say("hi")]) as client:
        assert client.get("/health").json()["status"] == "ok"
        domains = {d["name"]: d for d in client.get("/domains").json()}
        assert set(domains) == {"ecommerce", "banking"}
        risky = {t["name"] for t in domains["banking"]["tools"] if t["risky"]}
        assert risky == {"block_card", "reverse_transaction", "freeze_account"}


def test_records_and_unknown_domain(client_for):
    with client_for([say("hi")]) as client:
        assert len(client.get("/domains/ecommerce/records").json()["orders"]) == 6
        assert "accounts" in client.get("/domains/banking/records").json()
        assert client.get("/domains/insurance/records").status_code == 404
        assert client.post("/chat", json={"domain": "insurance", "message": "hi"}).status_code == 404


def test_chat_approve_audit_roundtrip(client_for):
    script = [call("reverse_transaction", transaction_ref="TXN-7001", reason="Duplicate"), say("Reversed.")]
    with client_for(script) as client:
        first = client.post("/chat", json={"domain": "banking", "message": "reverse TXN-7001"}).json()
        assert first["status"] == "awaiting_approval"

        blocked = client.post("/chat", json={"domain": "banking", "message": "hi",
                                             "thread_id": first["thread_id"]})
        assert blocked.status_code == 409

        done = client.post("/approve", json={"thread_id": first["thread_id"], "approved": True,
                                             "reviewer": "ops-lead"}).json()
        assert done["reply"] == "Reversed."
        txns = {t["txn"]: t["status"] for t in client.get("/domains/banking/records").json()["transactions"]}
        assert txns["TXN-7001"] == "REVERSED"

        audit = client.get("/audit", params={"limit": 5}).json()
        assert [a["event"] for a in audit][-2:] == ["approval_decision", "action_executed"]
        assert client.post("/approve", json={"thread_id": first["thread_id"], "approved": True}).status_code == 409


def test_reset_restores_seed(client_for):
    script = [call("cancel_order", order_number="ORD-5001"), say("Cancelled.")]
    with client_for(script) as client:
        first = client.post("/chat", json={"domain": "ecommerce", "message": "cancel"}).json()
        client.post("/approve", json={"thread_id": first["thread_id"], "approved": True})
        assert client.post("/reset").json() == {"status": "reset"}
        orders = {o["order"]: o["status"] for o in client.get("/domains/ecommerce/records").json()["orders"]}
        assert orders["ORD-5001"] == "PLACED"


def test_validation(client_for):
    with client_for([say("hi")]) as client:
        assert client.post("/chat", json={"domain": "banking", "message": ""}).status_code == 422
