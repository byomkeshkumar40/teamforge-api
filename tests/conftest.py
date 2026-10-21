import os

# Test settings must be in place BEFORE the app (and its settings) is imported.
# Real environment variables win over .env, so tests never touch the dev database.
os.environ["APP_ENV"] = "test"
os.environ["POSTGRES_DB"] = os.environ.get("TEST_POSTGRES_DB", "teamforge_test")
os.environ["JWT_SECRET_KEY"] = "test-only-secret-key-not-used-anywhere-else-0123456789"
os.environ["EXPOSE_INVITATION_TOKENS"] = "true"
os.environ["LOG_LEVEL"] = "WARNING"

import itertools  # noqa: E402
import re  # noqa: E402
import uuid  # noqa: E402
from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from alembic import command  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import User  # noqa: E402
from tests.helpers import TEST_PASSWORD  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def database() -> Iterator[None]:
    """Create a fresh test database and build its schema with the real Alembic migrations."""
    settings = get_settings()
    name = settings.postgres_db
    # Safety: this fixture DROPs the database, so refuse anything not clearly a test DB.
    assert re.fullmatch(r"[a-z0-9_]+_test", name), f"refusing to reset non-test database {name!r}"

    admin = create_engine(
        settings.sqlalchemy_url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()

    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables() -> Iterator[None]:
    """Empty every table after each test (tests commit for real, so no rollback trick)."""
    yield
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def password_hash() -> str:
    """Argon2 is deliberately slow, so hash the shared test password once per run."""
    return hash_password(TEST_PASSWORD)


@pytest.fixture
def make_user(db: Session, password_hash: str):
    """Factory for committed users; the password is always TEST_PASSWORD."""
    counter = itertools.count(1)

    def _make(email: str | None = None, *, full_name: str = "Test User", is_active: bool = True):
        user = User(
            email=email or f"user{next(counter)}-{uuid.uuid4().hex[:6]}@example.com",
            password_hash=password_hash,
            full_name=full_name,
            is_active=is_active,
        )
        db.add(user)
        db.commit()
        return user

    return _make
