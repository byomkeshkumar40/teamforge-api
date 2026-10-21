import logging
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import create_access_token
from app.models import User
from tests.helpers import TEST_PASSWORD, auth_headers

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
ME = "/api/v1/users/me"


def secret() -> str:
    return get_settings().jwt_secret_key.get_secret_value()


def forge(claims: dict, key: str | None = None, algorithm: str = "HS256") -> str:
    return jwt.encode(claims, key or secret(), algorithm=algorithm)


def valid_claims(user_id, **overrides) -> dict:
    now = datetime.now(UTC)
    return {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=5)} | overrides


# ---------------------------------------------------------------- registration


def test_register_creates_user_without_exposing_password(client, db):
    response = client.post(
        REGISTER,
        json={"email": "Ada@Example.com", "password": TEST_PASSWORD, "full_name": "  Ada L  "},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "ada@example.com"  # normalised
    assert body["full_name"] == "Ada L"  # trimmed
    assert body["is_active"] is True
    assert "password" not in body and "password_hash" not in body

    stored = db.scalar(select(User).where(User.email == "ada@example.com"))
    assert stored.password_hash.startswith("$argon2id$")
    assert TEST_PASSWORD not in stored.password_hash


def test_register_duplicate_email_is_conflict_case_insensitively(client):
    payload = {"email": "dup@example.com", "password": TEST_PASSWORD, "full_name": "A"}
    assert client.post(REGISTER, json=payload).status_code == 201
    response = client.post(REGISTER, json=payload | {"email": "DUP@example.com"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": TEST_PASSWORD, "full_name": "A"},
        {"email": "a@example.com", "password": "short", "full_name": "A"},
        {"email": "a@example.com", "password": "x" * 129, "full_name": "A"},
        {"email": "a@example.com", "password": TEST_PASSWORD, "full_name": "   "},
        {"email": "a@example.com", "password": TEST_PASSWORD},
        {},
    ],
)
def test_register_validation_errors(client, payload):
    response = client.post(REGISTER, json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_validation_error_never_echoes_submitted_password(client):
    response = client.post(
        REGISTER, json={"email": "bad", "password": "secret-pw-123", "full_name": "A"}
    )
    assert response.status_code == 422
    assert "secret-pw-123" not in response.text


# ------------------------------------------------------------------------ login


def test_login_returns_a_valid_token(client, make_user):
    user = make_user("ada@example.com")
    response = client.post(LOGIN, json={"email": "ADA@example.com", "password": TEST_PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == get_settings().access_token_expire_minutes * 60

    claims = jwt.decode(body["access_token"], secret(), algorithms=["HS256"])
    assert claims["sub"] == str(user.id)
    assert claims["exp"] - claims["iat"] == body["expires_in"]


def test_login_wrong_password_and_unknown_user_give_identical_errors(client, make_user):
    make_user("ada@example.com")
    wrong = client.post(LOGIN, json={"email": "ada@example.com", "password": "wrong-password"})
    unknown = client.post(LOGIN, json={"email": "nobody@example.com", "password": "wrong-password"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.headers["WWW-Authenticate"] == "Bearer"


def test_inactive_user_cannot_log_in(client, make_user):
    make_user("gone@example.com", is_active=False)
    response = client.post(LOGIN, json={"email": "gone@example.com", "password": TEST_PASSWORD})
    assert response.status_code == 403


def test_inactive_user_with_wrong_password_learns_nothing(client, make_user):
    make_user("gone@example.com", is_active=False)
    response = client.post(LOGIN, json={"email": "gone@example.com", "password": "wrong-password"})
    assert response.status_code == 401


def test_login_and_register_do_not_log_passwords(client, make_user, caplog):
    make_user("ada@example.com")
    caplog.set_level(logging.DEBUG)
    client.post(LOGIN, json={"email": "ada@example.com", "password": "Sup3r-Secret-Pw!"})
    client.post(
        REGISTER, json={"email": "b@example.com", "password": "Sup3r-Secret-Pw!", "full_name": "B"}
    )
    assert "Sup3r-Secret-Pw!" not in caplog.text
    assert any(r.name == "app.request" for r in caplog.records)  # logging was active


# ------------------------------------------------------------- current user


def test_me_returns_current_user(client, make_user):
    user = make_user("ada@example.com")
    response = client.get(ME, headers=auth_headers(user))
    assert response.status_code == 200
    assert response.json()["id"] == str(user.id)


def test_me_without_token_is_401(client):
    response = client.get(ME)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


@pytest.mark.parametrize("header", ["Bearer", "Bearer not.a.jwt", "Basic abc", "garbage"])
def test_me_with_malformed_authorization_header_is_401(client, header):
    assert client.get(ME, headers={"Authorization": header}).status_code == 401


def test_expired_token_is_rejected(client, make_user):
    user = make_user()
    token = create_access_token(user.id, expires_delta=timedelta(seconds=-5))
    response = client.get(ME, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Token has expired"


def test_token_signed_with_wrong_key_is_rejected(client, make_user):
    user = make_user()
    token = forge(valid_claims(user.id), key="a-different-secret-key-that-is-long-enough!!")
    assert client.get(ME, headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_tampered_token_is_rejected(client, make_user):
    user = make_user()
    header, payload, signature = create_access_token(user.id).split(".")
    tampered = f"{header}.{payload}.{signature[:-2]}aa"
    assert client.get(ME, headers={"Authorization": f"Bearer {tampered}"}).status_code == 401


def test_unsigned_alg_none_token_is_rejected(client, make_user):
    user = make_user()
    token = jwt.encode(valid_claims(user.id), key=None, algorithm="none")
    assert client.get(ME, headers={"Authorization": f"Bearer {token}"}).status_code == 401


@pytest.mark.filterwarnings("ignore:The HMAC key is:UserWarning")
@pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning")
def test_different_hmac_algorithm_is_rejected(client, make_user):
    user = make_user()
    token = forge(valid_claims(user.id), algorithm="HS512")
    assert client.get(ME, headers={"Authorization": f"Bearer {token}"}).status_code == 401


@pytest.mark.parametrize("missing", ["exp", "iat", "sub"])
def test_token_missing_required_claim_is_rejected(client, make_user, missing):
    user = make_user()
    claims = valid_claims(user.id)
    del claims[missing]
    assert client.get(ME, headers={"Authorization": f"Bearer {forge(claims)}"}).status_code == 401


def test_token_with_non_uuid_subject_is_rejected(client):
    token = forge(valid_claims("not-a-uuid"))
    assert client.get(ME, headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_token_for_deleted_user_is_rejected(client, db, make_user):
    user = make_user()
    headers = auth_headers(user)
    db.delete(user)
    db.commit()
    assert client.get(ME, headers=headers).status_code == 401


def test_token_for_user_deactivated_after_login_is_rejected(client, db, make_user):
    user = make_user()
    headers = auth_headers(user)
    assert client.get(ME, headers=headers).status_code == 200
    user.is_active = False
    db.commit()
    assert client.get(ME, headers=headers).status_code == 401


def test_token_for_unknown_user_is_rejected(client):
    token = create_access_token(uuid.uuid4())
    assert client.get(ME, headers={"Authorization": f"Bearer {token}"}).status_code == 401
