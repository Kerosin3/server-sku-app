from collections.abc import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def dry_run_session() -> Iterator[Session]:
    """
    A Session whose work is always rolled back, used by the API's
    `dry_run` flag (see app/routers/api_v1.py).

    The point is to run the *real* service function — every validation,
    every prerequisite check, in the exact order the real call runs them
    — and then throw the result away. Re-implementing those checks as a
    separate "validate only" path would duplicate the rules and drift
    from them; this cannot drift, because it is the same code.

    Service functions call db.commit() themselves, so an ordinary
    session would have already written by the time we got control back.
    Binding the Session to a connection-level transaction with
    join_transaction_mode="create_savepoint" turns those commits into
    savepoint releases; rolling back the outer transaction then undoes
    everything, including the audit_log rows.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
