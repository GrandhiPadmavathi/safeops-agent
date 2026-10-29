from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from safeops.domains.banking.models import BankAccount, BankCard, BankCustomer, BankTransaction
from safeops.domains.base import DomainError, ToolSpec

AGENT_REVERSAL_LIMIT = 5_000.00


def _normalize(raw: str, prefix: str, example: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        raise DomainError(f"'{raw}' is not a valid identifier (expected e.g. {example}).")
    return f"{prefix}-{digits}"


def _account(session: Session, raw: str) -> BankAccount:
    number = _normalize(raw, "ACC", "ACC-3001")
    acc = session.query(BankAccount).filter_by(number=number).one_or_none()
    if acc is None:
        raise DomainError(f"Account {number} was not found.")
    return acc


def _card(session: Session, raw: str) -> BankCard:
    card_id = _normalize(raw, "CARD", "CARD-4242")
    card = session.query(BankCard).filter_by(card_id=card_id).one_or_none()
    if card is None:
        raise DomainError(f"Card {card_id} was not found.")
    return card


def _txn(session: Session, raw: str) -> BankTransaction:
    ref = _normalize(raw, "TXN", "TXN-7001")
    txn = session.query(BankTransaction).filter_by(ref=ref).one_or_none()
    if txn is None:
        raise DomainError(f"Transaction {ref} was not found.")
    return txn


def _account_dict(a: BankAccount) -> dict[str, Any]:
    return {
        "account_number": a.number,
        "customer_ref": a.customer.ref,
        "type": a.kind,
        "balance": a.balance,
        "currency": a.currency,
        "status": a.status,
        "status_reason": a.status_reason,
        "cards": [{"card_id": c.card_id, "network": c.network, "status": c.status} for c in a.cards],
    }


class CustomerIn(BaseModel):
    customer_ref: str = Field(..., description="Customer reference such as B-2001")


def find_customer(session: Session, customer_ref: str):
    c = session.query(BankCustomer).filter_by(ref=customer_ref.strip().upper()).one_or_none()
    if c is None:
        return {"found": False}
    return {
        "found": True,
        "customer": {"customer_ref": c.ref, "name": c.name},
        "accounts": [_account_dict(a) for a in c.accounts],
    }


class AccountIn(BaseModel):
    account_number: str = Field(..., description="Account number such as ACC-3001")


def get_account(session: Session, account_number: str):
    return _account_dict(_account(session, account_number))


class TransactionsIn(BaseModel):
    account_number: str = Field(..., description="Account number such as ACC-3001")
    limit: int = Field(5, ge=1, le=20, description="How many recent transactions to return")


def list_transactions(session: Session, account_number: str, limit: int = 5):
    acc = _account(session, account_number)
    return {
        "account_number": acc.number,
        "transactions": [
            {"transaction_ref": t.ref, "amount": t.amount, "merchant": t.merchant,
             "posted_on": t.posted_on, "status": t.status}
            for t in acc.transactions[:limit]
        ],
    }


class TransactionIn(BaseModel):
    transaction_ref: str = Field(..., description="Transaction reference such as TXN-7001")


def get_transaction(session: Session, transaction_ref: str):
    t = _txn(session, transaction_ref)
    return {"transaction_ref": t.ref, "account_number": t.account.number, "account_status": t.account.status,
            "amount": t.amount, "merchant": t.merchant, "posted_on": t.posted_on, "status": t.status,
            "reversal_reason": t.reversal_reason}


class BlockCardIn(BaseModel):
    card_id: str = Field(..., description="Card identifier such as CARD-4242")
    reason: str = Field("Customer request", description="Why the card is blocked, e.g. lost or stolen")


def block_card(session: Session, card_id: str, reason: str = "Customer request"):
    card = _card(session, card_id)
    if card.account.status != "ACTIVE":
        raise DomainError(f"Account {card.account.number} is {card.account.status}; no changes are allowed.")
    if card.status == "BLOCKED":
        raise DomainError(f"Card {card.card_id} is already blocked ({card.block_reason}).")
    card.status = "BLOCKED"
    card.block_reason = reason
    return {"card_id": card.card_id, "status": card.status, "reason": reason}


class ReverseIn(BaseModel):
    transaction_ref: str = Field(..., description="Transaction reference such as TXN-7001")
    reason: str = Field("Customer dispute", description="Why the transaction is reversed")


def reverse_transaction(session: Session, transaction_ref: str, reason: str = "Customer dispute"):
    txn = _txn(session, transaction_ref)
    if txn.status != "POSTED":
        raise DomainError(f"Transaction {txn.ref} is {txn.status}; only POSTED transactions can be reversed.")
    if txn.account.status != "ACTIVE":
        raise DomainError(f"Account {txn.account.number} is {txn.account.status}; no changes are allowed.")
    if txn.amount > AGENT_REVERSAL_LIMIT:
        raise DomainError(
            f"Reversals above {AGENT_REVERSAL_LIMIT:,.0f} must go to the disputes team; escalate instead."
        )
    txn.status = "REVERSED"
    txn.reversal_reason = reason
    txn.account.balance = round(txn.account.balance + txn.amount, 2)
    return {"transaction_ref": txn.ref, "status": txn.status, "credited": txn.amount,
            "new_balance": txn.account.balance}


class FreezeIn(BaseModel):
    account_number: str = Field(..., description="Account number such as ACC-3001")
    reason: str = Field(..., min_length=3, description="Why the account is frozen, e.g. suspected fraud")


def freeze_account(session: Session, account_number: str, reason: str):
    acc = _account(session, account_number)
    if acc.status == "FROZEN":
        raise DomainError(f"Account {acc.number} is already frozen ({acc.status_reason}).")
    acc.status = "FROZEN"
    acc.status_reason = reason
    return {"account_number": acc.number, "status": acc.status, "reason": reason}


TOOLS = [
    ToolSpec("find_customer", "Find a banking customer, their accounts and cards by customer reference.",
             CustomerIn, find_customer),
    ToolSpec("get_account", "Get an account's balance, status and cards.", AccountIn, get_account),
    ToolSpec("list_transactions", "List the most recent transactions on an account.",
             TransactionsIn, list_transactions),
    ToolSpec("get_transaction", "Get one transaction's amount, merchant, status and its account's status.",
             TransactionIn, get_transaction),
    ToolSpec("block_card", "Block a debit card, e.g. when it is lost or stolen.", BlockCardIn, block_card,
             risky=True, summary="Block card {card_id} (reason: {reason})"),
    ToolSpec("reverse_transaction", "Reverse a POSTED transaction and credit the account.", ReverseIn,
             reverse_transaction, risky=True,
             summary="Reverse transaction {transaction_ref} and credit the account (reason: {reason})"),
    ToolSpec("freeze_account", "Freeze an account so no money can move, e.g. suspected fraud.", FreezeIn,
             freeze_account, risky=True, summary="Freeze account {account_number} (reason: {reason})"),
]


def records(session: Session) -> dict[str, list[dict[str, Any]]]:
    accounts = session.query(BankAccount).order_by(BankAccount.number).all()
    cards = session.query(BankCard).order_by(BankCard.card_id).all()
    txns = session.query(BankTransaction).order_by(BankTransaction.ref).all()
    return {
        "accounts": [{"account": a.number, "customer": a.customer.ref, "status": a.status,
                      "balance": a.balance} for a in accounts],
        "cards": [{"card": c.card_id, "account": c.account.number, "status": c.status} for c in cards],
        "transactions": [{"txn": t.ref, "account": t.account.number, "amount": t.amount,
                          "merchant": t.merchant, "status": t.status} for t in txns],
    }
