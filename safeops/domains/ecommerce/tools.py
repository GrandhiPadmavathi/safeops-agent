from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from safeops.domains.base import DomainError, ToolSpec
from safeops.domains.ecommerce.models import EcomCustomer, EcomOrder, EcomRefund

AGENT_REFUND_LIMIT = 10_000.00


def _order_number(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        raise DomainError(f"'{raw}' is not a valid order number (expected e.g. ORD-5001).")
    return f"ORD-{digits}"


def _get_order(session: Session, raw: str) -> EcomOrder:
    number = _order_number(raw)
    order = session.query(EcomOrder).filter_by(number=number).one_or_none()
    if order is None:
        raise DomainError(f"Order {number} was not found.")
    return order


def _order_dict(o: EcomOrder) -> dict[str, Any]:
    return {
        "order_number": o.number,
        "customer_ref": o.customer.ref,
        "status": o.status,
        "total": o.total,
        "refunded": o.refunded,
        "refundable": round(o.total - o.refunded, 2),
        "currency": o.currency,
        "shipping_address": o.shipping_address,
        "placed_at": o.placed_at.date().isoformat(),
    }


class FindCustomerIn(BaseModel):
    email: str | None = Field(None, description="Customer email address")
    customer_ref: str | None = Field(None, description="Customer reference such as C-1001")


def find_customer(session: Session, email: str | None = None, customer_ref: str | None = None):
    if not email and not customer_ref:
        raise DomainError("Provide the customer's email or customer reference.")
    q = session.query(EcomCustomer)
    c = (
        q.filter_by(email=email.strip().lower()).one_or_none()
        if email
        else q.filter_by(ref=customer_ref.strip().upper()).one_or_none()
    )
    if c is None:
        return {"found": False}
    return {
        "found": True,
        "customer": {"customer_ref": c.ref, "name": c.name, "email": c.email},
        "orders": [
            {"order_number": o.number, "status": o.status, "total": o.total} for o in c.orders
        ],
    }


class OrderIn(BaseModel):
    order_number: str = Field(..., description="Order number such as ORD-5001")


def get_order(session: Session, order_number: str):
    o = _get_order(session, order_number)
    data = _order_dict(o)
    data["refunds"] = [{"amount": r.amount, "reason": r.reason} for r in o.refunds]
    return data


def track_shipment(session: Session, order_number: str):
    o = _get_order(session, order_number)
    if o.shipment is None:
        return {"order_number": o.number, "status": o.status, "shipment": None,
                "note": "No shipment yet; the order has not been dispatched."}
    s = o.shipment
    return {
        "order_number": o.number,
        "carrier": s.carrier,
        "tracking_number": s.tracking_number,
        "shipment_status": s.status,
        "eta": s.eta,
    }


class CancelIn(BaseModel):
    order_number: str = Field(..., description="Order number such as ORD-5001")
    reason: str = Field("Customer request", description="Why the order is being cancelled")


def cancel_order(session: Session, order_number: str, reason: str = "Customer request"):
    o = _get_order(session, order_number)
    if o.status != "PLACED":
        raise DomainError(
            f"Order {o.number} is {o.status}; only PLACED orders can be cancelled. "
            "For shipped or delivered orders, offer a return or refund instead."
        )
    amount = round(o.total - o.refunded, 2)
    o.status = "CANCELLED"
    o.refunded = o.total
    session.add(EcomRefund(order_id=o.id, amount=amount, reason=f"Cancelled: {reason}"))
    return {"order_number": o.number, "status": o.status, "refunded_amount": amount}


class RefundIn(BaseModel):
    order_number: str = Field(..., description="Order number such as ORD-5002")
    amount: float = Field(..., gt=0, description="Refund amount in the order currency")
    reason: str = Field("Customer request", description="Why the refund is issued")


def issue_refund(session: Session, order_number: str, amount: float, reason: str = "Customer request"):
    o = _get_order(session, order_number)
    if o.status != "DELIVERED":
        raise DomainError(
            f"Order {o.number} is {o.status}; refunds are only issued on DELIVERED orders "
            "(PLACED orders should be cancelled instead)."
        )
    refundable = round(o.total - o.refunded, 2)
    if amount > refundable:
        raise DomainError(f"Refund of {amount:.2f} exceeds the refundable balance of {refundable:.2f}.")
    if amount > AGENT_REFUND_LIMIT:
        raise DomainError(
            f"Refunds above {AGENT_REFUND_LIMIT:,.0f} need the finance team; escalate instead."
        )
    o.refunded = round(o.refunded + amount, 2)
    session.add(EcomRefund(order_id=o.id, amount=amount, reason=reason))
    return {"order_number": o.number, "refunded_amount": amount,
            "total_refunded": o.refunded, "remaining_refundable": round(o.total - o.refunded, 2)}


class AddressIn(BaseModel):
    order_number: str = Field(..., description="Order number such as ORD-5001")
    new_address: str = Field(..., min_length=10, description="Full new shipping address")


def update_shipping_address(session: Session, order_number: str, new_address: str):
    o = _get_order(session, order_number)
    if o.status != "PLACED":
        raise DomainError(f"Order {o.number} is {o.status}; the address can only change before dispatch.")
    old = o.shipping_address
    o.shipping_address = new_address.strip()
    return {"order_number": o.number, "old_address": old, "new_address": o.shipping_address}


TOOLS = [
    ToolSpec("find_customer", "Find a customer and their orders by email or customer reference.",
             FindCustomerIn, find_customer),
    ToolSpec("get_order", "Get an order's status, totals, refunds and shipping address.",
             OrderIn, get_order),
    ToolSpec("track_shipment", "Get carrier, tracking number and delivery ETA for an order.",
             OrderIn, track_shipment),
    ToolSpec("cancel_order", "Cancel a PLACED order and refund it in full.", CancelIn, cancel_order,
             risky=True, summary="Cancel order {order_number} and refund it in full (reason: {reason})"),
    ToolSpec("issue_refund", "Issue a partial or full refund on a DELIVERED order.", RefundIn, issue_refund,
             risky=True, summary="Refund {amount} on order {order_number} (reason: {reason})"),
    ToolSpec("update_shipping_address", "Change the shipping address of a PLACED order.", AddressIn,
             update_shipping_address, risky=True,
             summary="Change shipping address of {order_number} to: {new_address}"),
]


def records(session: Session) -> dict[str, list[dict[str, Any]]]:
    orders = session.query(EcomOrder).order_by(EcomOrder.number).all()
    refunds = session.query(EcomRefund).order_by(EcomRefund.id.desc()).limit(10).all()
    return {
        "orders": [
            {"order": o.number, "customer": o.customer.ref, "status": o.status,
             "total": o.total, "refunded": o.refunded}
            for o in orders
        ],
        "refunds": [
            {"order": r.order.number, "amount": r.amount, "reason": r.reason} for r in refunds
        ],
    }
