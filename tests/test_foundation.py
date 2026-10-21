import json
import logging

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.logging import JsonFormatter


def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_response_has_request_id_header(client):
    response = client.get("/health")
    assert len(response.headers["X-Request-ID"]) == 32


def test_unknown_route_uses_consistent_error_format(client):
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert "message" in body["error"]


def test_wrong_method_uses_consistent_error_format(client):
    response = client.post("/health")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_json_formatter_redacts_sensitive_extras():
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "login", None, None)
    record.password = "hunter2"
    record.token = "abc"
    record.user_id = "u1"
    line = json.loads(JsonFormatter().format(record))
    assert line["password"] == "[REDACTED]"
    assert line["token"] == "[REDACTED]"
    assert line["user_id"] == "u1"
    assert "hunter2" not in json.dumps(line)


def test_settings_reject_short_jwt_secret():
    with pytest.raises(ValidationError):
        Settings(postgres_password="x", jwt_secret_key="too-short")


def test_settings_forbid_token_exposure_in_production():
    with pytest.raises(ValidationError):
        Settings(
            postgres_password="x",
            jwt_secret_key="k" * 40,
            app_env="production",
            expose_invitation_tokens=True,
        )
