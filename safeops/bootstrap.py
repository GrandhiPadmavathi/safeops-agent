from safeops.db import Base, Database
from safeops.domains import DOMAINS


def seed_all(db: Database, *, reset: bool = False) -> None:
    """Create tables and load demo data. ``reset`` wipes and reseeds in one transaction."""
    db.create_all()
    with db.session() as session:
        if reset:
            for table in reversed(Base.metadata.sorted_tables):
                session.execute(table.delete())
        for domain in DOMAINS.values():
            domain.seed(session)
