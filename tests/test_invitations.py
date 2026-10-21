from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models import Invitation, Membership
from app.services.invitations import hash_token
from tests.helpers import API, auth_headers, create_org, join_org, make_org_with_roles


def invite(client, org_id, actor, email, role="MEMBER"):
    return client.post(
        f"{API}/organizations/{org_id}/invitations",
        json={"email": email, "role": role},
        headers=auth_headers(actor),
    )


def accept(client, user, token):
    return client.post(
        f"{API}/invitations/accept", json={"token": token}, headers=auth_headers(user)
    )


def test_invitation_flow_adds_member_with_invited_role(client, db, make_user):
    owner, invitee = make_user(), make_user("new@example.com")
    org = create_org(client, owner)
    created = invite(client, org["id"], owner, "New@Example.com", "ADMIN")
    assert created.status_code == 201
    assert created.json()["email"] == "new@example.com"

    response = accept(client, invitee, created.json()["token"])
    assert response.status_code == 200
    assert response.json()["role"] == "ADMIN" and response.json()["id"] == org["id"]
    assert (
        db.scalar(select(Membership.role).where(Membership.user_id == invitee.id)).value == "ADMIN"
    )


def test_raw_token_is_never_stored(client, db, make_user):
    owner = make_user()
    org = create_org(client, owner)
    token = invite(client, org["id"], owner, "x@example.com").json()["token"]
    stored = db.scalar(select(Invitation))
    assert stored.token_hash == hash_token(token) != token
    assert token not in repr(stored.__dict__.values())


def test_token_is_only_returned_when_development_flag_is_on(client, make_user, monkeypatch):
    owner = make_user()
    org = create_org(client, owner)
    monkeypatch.setattr(get_settings(), "expose_invitation_tokens", False)
    response = invite(client, org["id"], owner, "x@example.com")
    assert response.status_code == 201
    assert "token" not in response.json()


def test_listing_invitations_never_exposes_tokens(client, make_user):
    owner = make_user()
    org = create_org(client, owner)
    invite(client, org["id"], owner, "x@example.com")
    response = client.get(
        f"{API}/organizations/{org['id']}/invitations", headers=auth_headers(owner)
    )
    assert response.json()["total"] == 1
    assert "token" not in response.text and "token_hash" not in response.text


def test_invitation_token_never_appears_in_logs(client, make_user, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    owner, invitee = make_user("n@example.com"), make_user("m@example.com")
    org = create_org(client, owner)
    token = invite(client, org["id"], owner, "m@example.com").json()["token"]
    accept(client, invitee, token)
    assert token not in caplog.text


@pytest.mark.parametrize(("who", "expected"), [("owner", 201), ("admin", 201), ("member", 403)])
def test_only_owner_and_admin_can_invite(client, make_user, who, expected):
    ctx = make_org_with_roles(client, make_user)
    assert invite(client, ctx["org"]["id"], ctx[who], "x@example.com").status_code == expected


def test_cannot_invite_as_owner(client, make_user):
    owner = make_user()
    org = create_org(client, owner)
    response = invite(client, org["id"], owner, "x@example.com", "OWNER")
    assert response.status_code == 422


def test_cannot_invite_existing_member(client, make_user):
    ctx = make_org_with_roles(client, make_user)
    assert invite(client, ctx["org"]["id"], ctx["owner"], ctx["member"].email).status_code == 409


def test_invitation_can_only_be_redeemed_by_matching_email(client, make_user):
    owner, intended, thief = make_user(), make_user("intended@example.com"), make_user()
    org = create_org(client, owner)
    token = invite(client, org["id"], owner, "intended@example.com").json()["token"]
    assert accept(client, thief, token).status_code == 400
    assert accept(client, intended, token).status_code == 200


def test_token_cannot_be_reused(client, make_user):
    owner, invitee = make_user(), make_user("a@example.com")
    org = create_org(client, owner)
    token = invite(client, org["id"], owner, "a@example.com").json()["token"]
    assert accept(client, invitee, token).status_code == 200
    assert accept(client, invitee, token).status_code == 400


def test_expired_invitation_is_rejected(client, db, make_user):
    owner, invitee = make_user(), make_user("a@example.com")
    org = create_org(client, owner)
    token = invite(client, org["id"], owner, "a@example.com").json()["token"]
    invitation = db.scalar(select(Invitation))
    invitation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    response = accept(client, invitee, token)
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "Invalid or expired invitation"


def test_all_invalid_token_failures_look_identical(client, make_user):
    owner, invitee = make_user(), make_user("a@example.com")
    org = create_org(client, owner)
    real = invite(client, org["id"], owner, "other@example.com").json()["token"]
    wrong_email = accept(client, invitee, real)
    garbage = accept(client, invitee, "g" * 43)
    assert wrong_email.json() == garbage.json()


def test_accepting_requires_authentication_and_valid_body(client, make_user):
    assert client.post(f"{API}/invitations/accept", json={"token": "x" * 30}).status_code == 401
    response = client.post(
        f"{API}/invitations/accept", json={"token": "short"}, headers=auth_headers(make_user())
    )
    assert response.status_code == 422


def test_reinviting_invalidates_the_previous_token(client, make_user):
    owner, invitee = make_user(), make_user("a@example.com")
    org = create_org(client, owner)
    first = invite(client, org["id"], owner, "a@example.com").json()["token"]
    second = invite(client, org["id"], owner, "a@example.com", "ADMIN").json()["token"]
    assert accept(client, invitee, first).status_code == 400
    assert accept(client, invitee, second).json()["role"] == "ADMIN"


def test_revoked_invitation_cannot_be_accepted(client, make_user):
    owner, invitee = make_user(), make_user("a@example.com")
    org = create_org(client, owner)
    created = invite(client, org["id"], owner, "a@example.com").json()
    revoke = client.delete(
        f"{API}/organizations/{org['id']}/invitations/{created['id']}", headers=auth_headers(owner)
    )
    assert revoke.status_code == 204
    assert accept(client, invitee, created["token"]).status_code == 400


def test_member_cannot_list_or_revoke_invitations(client, make_user):
    ctx = make_org_with_roles(client, make_user)
    org_id = ctx["org"]["id"]
    created = invite(client, org_id, ctx["owner"], "x@example.com").json()
    member = auth_headers(ctx["member"])
    assert (
        client.get(f"{API}/organizations/{org_id}/invitations", headers=member).status_code == 403
    )
    assert (
        client.delete(
            f"{API}/organizations/{org_id}/invitations/{created['id']}", headers=member
        ).status_code
        == 403
    )


def test_replaced_token_is_rejected_even_after_user_joined_via_new_one(client, make_user):
    owner, user = make_user(), make_user("a@example.com")
    org = create_org(client, owner)
    token = invite(client, org["id"], owner, "a@example.com").json()["token"]
    join_org(client, org["id"], owner, user)  # joins through a newer invitation
    assert accept(client, user, token).status_code == 400  # the old token was replaced
