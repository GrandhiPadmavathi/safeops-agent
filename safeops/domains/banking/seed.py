from sqlalchemy.orm import Session

from safeops.domains.banking.models import BankAccount, BankCard, BankCustomer, BankTransaction

CUSTOMERS = [("B-2001", "Meera Iyer"), ("B-2002", "Arjun Rao"), ("B-2003", "Sara Thomas")]

# number, customer_ref, kind, balance, status
ACCOUNTS = [
    ("ACC-3001", "B-2001", "SAVINGS", 84250.75, "ACTIVE"),
    ("ACC-3002", "B-2001", "CURRENT", 15000.00, "ACTIVE"),
    ("ACC-3003", "B-2002", "SAVINGS", 3200.40, "ACTIVE"),
    ("ACC-3004", "B-2003", "SAVINGS", 51000.00, "FROZEN"),
]

# card_id, account, network, status
CARDS = [
    ("CARD-4242", "ACC-3001", "VISA", "ACTIVE"),
    ("CARD-1881", "ACC-3002", "MASTERCARD", "ACTIVE"),
    ("CARD-5005", "ACC-3003", "RUPAY", "ACTIVE"),
    ("CARD-7777", "ACC-3004", "VISA", "BLOCKED"),
]

# ref, account, amount, merchant, posted_on, status
TRANSACTIONS = [
    ("TXN-7001", "ACC-3001", 1299.00, "StreamFlix", "2026-10-12", "POSTED"),
    ("TXN-7002", "ACC-3001", 45000.00, "LuxWatch Store", "2026-10-14", "POSTED"),
    ("TXN-7003", "ACC-3001", 249.00, "Metro Cafe", "2026-10-15", "POSTED"),
    ("TXN-7004", "ACC-3003", 799.00, "QuickCab", "2026-10-13", "POSTED"),
    ("TXN-7005", "ACC-3003", 2100.00, "ElectroMart", "2026-10-11", "REVERSED"),
    ("TXN-7006", "ACC-3002", 3499.00, "CloudHost Inc", "2026-10-09", "POSTED"),
    ("TXN-7007", "ACC-3004", 1800.00, "TravelNest", "2026-10-08", "POSTED"),
]


def seed(session: Session) -> None:
    if session.query(BankCustomer).first():
        return
    customers = {}
    for ref, name in CUSTOMERS:
        c = BankCustomer(ref=ref, name=name)
        session.add(c)
        customers[ref] = c
    session.flush()

    accounts = {}
    for number, cref, kind, balance, status in ACCOUNTS:
        a = BankAccount(
            number=number,
            customer_id=customers[cref].id,
            kind=kind,
            balance=balance,
            status=status,
            status_reason="Compliance review" if status == "FROZEN" else None,
        )
        session.add(a)
        accounts[number] = a
    session.flush()

    for card_id, acc, network, status in CARDS:
        session.add(
            BankCard(
                card_id=card_id,
                account_id=accounts[acc].id,
                network=network,
                status=status,
                block_reason="Reported lost" if status == "BLOCKED" else None,
            )
        )
    for ref, acc, amount, merchant, posted_on, status in TRANSACTIONS:
        session.add(
            BankTransaction(
                ref=ref,
                account_id=accounts[acc].id,
                amount=amount,
                merchant=merchant,
                posted_on=posted_on,
                status=status,
                reversal_reason="Duplicate charge" if status == "REVERSED" else None,
            )
        )
    session.flush()
