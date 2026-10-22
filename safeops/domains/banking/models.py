from __future__ import annotations

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from safeops.db import Base


class BankCustomer(Base):
    __tablename__ = "bank_customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(80))

    accounts: Mapped[list[BankAccount]] = relationship(back_populates="customer", order_by="BankAccount.id")


class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(16), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("bank_customers.id"))
    kind: Mapped[str] = mapped_column(String(16))
    balance: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[str] = mapped_column(String(16))
    status_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    customer: Mapped[BankCustomer] = relationship(back_populates="accounts")
    cards: Mapped[list[BankCard]] = relationship(back_populates="account", order_by="BankCard.id")
    transactions: Mapped[list[BankTransaction]] = relationship(
        back_populates="account", order_by="BankTransaction.posted_on.desc()"
    )


class BankCard(Base):
    __tablename__ = "bank_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[str] = mapped_column(String(16), unique=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("bank_accounts.id"))
    network: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    block_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    account: Mapped[BankAccount] = relationship(back_populates="cards")


class BankTransaction(Base):
    __tablename__ = "bank_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(16), unique=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("bank_accounts.id"))
    amount: Mapped[float] = mapped_column(Float)
    merchant: Mapped[str] = mapped_column(String(80))
    posted_on: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(16))
    reversal_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    account: Mapped[BankAccount] = relationship(back_populates="transactions")
