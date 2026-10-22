from datetime import datetime, timezone

from sqlalchemy.orm import Session

from safeops.domains.ecommerce.models import EcomCustomer, EcomOrder, EcomRefund, EcomShipment

CUSTOMERS = [
    ("C-1001", "Asha Verma", "asha.verma@example.com"),
    ("C-1002", "Rahul Mehta", "rahul.mehta@example.com"),
    ("C-1003", "Priya Nair", "priya.nair@example.com"),
    ("C-1004", "Daniel Brooks", "daniel.brooks@example.com"),
]

# number, customer_ref, status, total, refunded, address, placed (day of Oct 2026)
ORDERS = [
    ("ORD-5001", "C-1001", "PLACED", 2499.00, 0.0, "12 MG Road, Pune 411001", 14),
    ("ORD-5002", "C-1001", "DELIVERED", 899.00, 0.0, "12 MG Road, Pune 411001", 2),
    ("ORD-5003", "C-1002", "SHIPPED", 15999.00, 0.0, "44 Park Street, Kolkata 700016", 10),
    ("ORD-5004", "C-1003", "PLACED", 349.50, 0.0, "7 Marine Drive, Kochi 682031", 15),
    ("ORD-5005", "C-1003", "CANCELLED", 1200.00, 1200.00, "7 Marine Drive, Kochi 682031", 5),
    ("ORD-5006", "C-1004", "DELIVERED", 5400.00, 400.00, "221 Baker Lane, Bengaluru 560001", 1),
]

# order_number, carrier, tracking, status, eta
SHIPMENTS = [
    ("ORD-5002", "BlueDart", "BD100200300IN", "DELIVERED", "2026-10-06"),
    ("ORD-5003", "Delhivery", "DLV7788990011", "IN_TRANSIT", "2026-10-19"),
    ("ORD-5006", "Ekart", "EK5544332211", "DELIVERED", "2026-10-04"),
]


def seed(session: Session) -> None:
    if session.query(EcomCustomer).first():
        return
    customers = {}
    for ref, name, email in CUSTOMERS:
        c = EcomCustomer(ref=ref, name=name, email=email)
        session.add(c)
        customers[ref] = c
    session.flush()

    orders = {}
    for number, cref, status, total, refunded, address, day in ORDERS:
        o = EcomOrder(
            number=number,
            customer_id=customers[cref].id,
            status=status,
            total=total,
            refunded=refunded,
            shipping_address=address,
            placed_at=datetime(2026, 10, day, 10, 30, tzinfo=timezone.utc),
        )
        session.add(o)
        orders[number] = o
    session.flush()

    for number, carrier, tracking, status, eta in SHIPMENTS:
        session.add(
            EcomShipment(
                order_id=orders[number].id,
                carrier=carrier,
                tracking_number=tracking,
                status=status,
                eta=eta,
            )
        )
    session.add(EcomRefund(order_id=orders["ORD-5005"].id, amount=1200.00, reason="Order cancelled"))
    session.add(EcomRefund(order_id=orders["ORD-5006"].id, amount=400.00, reason="Damaged packaging"))
    session.flush()
