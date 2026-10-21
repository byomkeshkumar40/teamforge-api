from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

# The engine connects lazily, so importing this module does not require a database.
engine = create_engine(get_settings().sqlalchemy_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request.

    Services commit explicitly. If a request fails before commit, closing the
    session rolls back the open transaction.
    """
    with SessionLocal() as session:
        yield session
