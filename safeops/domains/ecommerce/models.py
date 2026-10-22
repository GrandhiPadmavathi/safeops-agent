from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from safeops.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EcomCustomer(Base):
    __tablename__ = "ecom_customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(120), unique=True)

    orders: Mapped[list[EcomOrder]] = relationship(back_populates="customer", order_by="EcomOrder.id")


class EcomOrder(Base):
    __tablename__ = "ecom_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(16), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("ecom_customers.id"))
    status: Mapped[str] = mapped_column(String(16))
    total: Mapped[float] = mapped_column(Float)
    refunded: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    shipping_address: Mapped[str] = mapped_column(String(200))
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    customer: Mapped[EcomCustomer] = relationship(back_populates="orders")
    shipment: Mapped[EcomShipment | None] = relationship(back_populates="order", uselist=False)
    refunds: Mapped[list[EcomRefund]] = relationship(back_populates="order", order_by="EcomRefund.id")


class EcomShipment(Base):
    __tablename__ = "ecom_shipments"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("ecom_orders.id"), unique=True)
    carrier: Mapped[str] = mapped_column(String(40))
    tracking_number: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    eta: Mapped[str] = mapped_column(String(10))

    order: Mapped[EcomOrder] = relationship(back_populates="shipment")


class EcomRefund(Base):
    __tablename__ = "ecom_refunds"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("ecom_orders.id"))
    amount: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    order: Mapped[EcomOrder] = relationship(back_populates="refunds")
