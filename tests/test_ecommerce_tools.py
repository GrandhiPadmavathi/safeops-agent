from safeops.domains import get_domain
from tests.conftest import result_of

ECOM = get_domain("ecommerce")


def test_find_customer_by_email_and_ref(db):
    by_email = result_of(ECOM, db, "find_customer", email="  Asha.Verma@Example.com ")
    by_ref = result_of(ECOM, db, "find_customer", customer_ref="c-1001")
    assert by_email["found"] and by_ref["found"]
    assert by_email["customer"]["customer_ref"] == "C-1001"
    assert {o["order_number"] for o in by_ref["orders"]} == {"ORD-5001", "ORD-5002"}


def test_find_customer_needs_identifier(db):
    assert "error" in result_of(ECOM, db, "find_customer")


def test_get_order_normalizes_number(db):
    order = result_of(ECOM, db, "get_order", order_number="ord 5003")
    assert order["order_number"] == "ORD-5003"
    assert order["status"] == "SHIPPED"


def test_unknown_order(db):
    assert "not found" in result_of(ECOM, db, "get_order", order_number="ORD-9999")["error"]


def test_track_shipment_without_dispatch(db):
    assert result_of(ECOM, db, "track_shipment", order_number="ORD-5001")["shipment"] is None
    assert result_of(ECOM, db, "track_shipment", order_number="ORD-5003")["tracking_number"]


def test_cancel_placed_order_refunds_in_full(db):
    out = result_of(ECOM, db, "cancel_order", order_number="ORD-5001", reason="Changed mind")
    assert out == {"order_number": "ORD-5001", "status": "CANCELLED", "refunded_amount": 2499.0}
    assert result_of(ECOM, db, "get_order", order_number="ORD-5001")["refundable"] == 0


def test_cannot_cancel_shipped_order(db):
    assert "only PLACED" in result_of(ECOM, db, "cancel_order", order_number="ORD-5003")["error"]


def test_refund_rules(db):
    def refund_error(order_number, amount):
        return result_of(ECOM, db, "issue_refund", order_number=order_number, amount=amount)["error"]

    assert "only issued on DELIVERED" in refund_error("ORD-5001", 100)
    assert "exceeds the refundable" in refund_error("ORD-5006", 5001)
    assert "Invalid arguments" in refund_error("ORD-5002", -5)
    ok = result_of(ECOM, db, "issue_refund", order_number="ORD-5006", amount=1000, reason="Damaged")
    assert ok["total_refunded"] == 1400 and ok["remaining_refundable"] == 4000


def test_update_address_only_before_dispatch(db):
    ok = result_of(ECOM, db, "update_shipping_address", order_number="ORD-5004",
                   new_address="12 Lake Road, Pune 411001")
    assert ok["new_address"] == "12 Lake Road, Pune 411001"
    assert "error" in result_of(ECOM, db, "update_shipping_address", order_number="ORD-5002",
                                new_address="12 Lake Road, Pune 411001")


def test_risky_tools_and_summary():
    assert ECOM.risky_tool_names == {"cancel_order", "issue_refund", "update_shipping_address"}
    summary = ECOM.tool("cancel_order").approval_summary({"order_number": "ORD-5001"})
    assert summary == "Cancel order ORD-5001 and refund it in full (reason: Customer request)"
