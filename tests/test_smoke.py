import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_python_version():
    assert sys.version_info >= (3, 12)


def test_env_example_documents_required_settings():
    keys = {
        line.split("=", 1)[0]
        for line in (ROOT / ".env.example").read_text().splitlines()
        if "=" in line and not line.startswith("#")
    }
    assert {"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "JWT_SECRET_KEY"} <= keys
