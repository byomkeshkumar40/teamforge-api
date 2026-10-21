import os

# Test settings must be in place BEFORE the app (and its settings) is imported.
# Real environment variables win over .env, so tests never touch the dev database.
os.environ["APP_ENV"] = "test"
os.environ["POSTGRES_DB"] = os.environ.get("TEST_POSTGRES_DB", "teamforge_test")
os.environ["JWT_SECRET_KEY"] = "test-only-secret-key-not-used-anywhere-else-0123456789"
os.environ["EXPOSE_INVITATION_TOKENS"] = "true"
os.environ["LOG_LEVEL"] = "WARNING"

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client
