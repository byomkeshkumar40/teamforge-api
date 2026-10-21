import pytest
from sqlalchemy import func, select

from app.core.permissions import ROLE_PERMISSIONS, Permission
from app.models import Membership, Role
from tests.helpers import API, auth_headers, create_org, join_org, make_org_with_roles, set_role


def members_url(org_id: str, user=None) -> str:
    base = f"{API}/organizations/{org_id}/members"
    return f"{base}/{user.id}" if user else base


def owner_count(db, org_id) -> int:
    db.expire_all()
    return db.scalar(
        select(func.count())
        .select_from(Membership)
        .where(Membership.organization_id == org_id, Membership.role == Role.OWNER)
    )


def test_permission_matrix_is_what_the_docs_promise():
    assert ROLE_PERMISSIONS[Role.OWNER] == frozenset(Permission)
    assert Permission.ORG_DELETE not in ROLE_PERMISSIONS[Role.ADMIN]
    assert Permission.MEMBERS_MANAGE in ROLE_PERMISSIONS[Role.ADMIN]
    assert ROLE_PERMISSIONS[Role.MEMBER] == frozenset({Permission.TASKS_WRITE})


def test_any_member_can_list_members(client, make_user):
    ctx = make_org_with_roles(client, make_user)
    response = client.get(members_url(ctx["org"]["id"]), headers=auth_headers(ctx["member"]))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert {m["role"] for m in body["items"]} == {"OWNER", "ADMIN", "MEMBER"}
    assert "password" not in response.text


# ------------------------------------------------------------- changing roles


def test_owner_can_promote_and_demote(client, make_user):
    ctx = make_org_with_roles(client, make_user)
    org_id = ctx["org"]["id"]
    assert set_role(client, org_id, ctx["owner"], ctx["member"], "ADMIN").json()["role"] == "ADMIN"
    assert set_role(client, org_id, ctx["owner"], ctx["admin"], "MEMBER").json()["role"] == "MEMBER"


def test_admin_can_manage_non_owners(client, make_user):
    ctx = make_org_with_roles(client, make_user)
    response = set_role(client, ctx["org"]["id"], ctx["admin"], ctx["member"], "ADMIN")
    assert response.status_code == 200


def test_admin_cannot_grant_ownership(client, make_user):
    ctx = make_org_with_roles(client, make_user)
    response = set_role(client, ctx["org"]["id"], ctx["admin"], ctx["member"], "OWNER")
    assert response.status_code == 403


def test_admin_cannot_demote_an_owner(client, make_user):
    ctx = make_org_with_roles(client, make_user)
    org_id = ctx["org"]["id"]
    assert (
        set_role(client, org_id, ctx["owner"], ctx["admin"], "OWNER").status_code == 200
    )  # 2nd owner
    other_admin = make_user()
    join_org(client, org_id, ctx["owner"], other_admin, "ADMIN")
    assert set_role(client, org_id, other_admin, ctx["admin"], "MEMBER").status_code == 403


def test_member_cannot_change_roles(client, make_user):
    ctx = make_org_with_roles(client, make_user)
    response = set_role(client, ctx["org"]["id"], ctx["member"], ctx["member"], "ADMIN")
    assert response.status_code == 403


def test_role_change_for_unknown_member_is_404(client, make_user):
    ctx = make_org_with_roles(client, make_user)
    stranger = make_user()
    assert set_role(client, ctx["org"]["id"], ctx["owner"], stranger, "ADMIN").status_code == 404


def test_invalid_role_value_is_422(client, make_user):
    ctx = make_org_with_roles(client, make_user)
    response = client.patch(
        members_url(ctx["org"]["id"], ctx["member"]),
        json={"role": "SUPERUSER"},
        headers=auth_headers(ctx["owner"]),
    )
    assert response.status_code == 422


# ------------------------------------------------------------ last-owner rule


def test_sole_owner_cannot_demote_themselves(client, db, make_user):
    owner = make_user()
    org = create_org(client, owner)
    response = set_role(client, org["id"], owner, owner, "ADMIN")
    assert response.status_code == 409
    assert owner_count(db, org["id"]) == 1


def test_sole_owner_cannot_leave(client, db, make_user):
    owner = make_user()
    org = create_org(client, owner)
    response = client.delete(members_url(org["id"], owner), headers=auth_headers(owner))
    assert response.status_code == 409
    assert owner_count(db, org["id"]) == 1


def test_ownership_can_be_transferred_then_old_owner_can_step_down_and_leave(client, db, make_user):
    ctx = make_org_with_roles(client, make_user)
    org_id = ctx["org"]["id"]
    assert set_role(client, org_id, ctx["owner"], ctx["admin"], "OWNER").status_code == 200
    assert set_role(client, org_id, ctx["owner"], ctx["owner"], "MEMBER").status_code == 200
    # the old owner is now a plain member and may leave
    assert (
        client.delete(
            members_url(org_id, ctx["owner"]), headers=auth_headers(ctx["owner"])
        ).status_code
        == 204
    )
    assert owner_count(db, org_id) == 1


def test_the_last_remaining_owner_cannot_be_demoted_by_another_owner_race_free_path(
    client, db, make_user
):
    ctx = make_org_with_roles(client, make_user)
    org_id = ctx["org"]["id"]
    set_role(client, org_id, ctx["owner"], ctx["admin"], "OWNER")
    assert set_role(client, org_id, ctx["admin"], ctx["owner"], "MEMBER").status_code == 200
    # `admin` is now the only owner and cannot be demoted, even by themselves
    assert set_role(client, org_id, ctx["admin"], ctx["admin"], "MEMBER").status_code == 409
    assert owner_count(db, org_id) == 1


# -------------------------------------------------------------------- removal


def test_owner_and_admin_can_remove_members(client, make_user):
    ctx = make_org_with_roles(client, make_user)
    org_id = ctx["org"]["id"]
    assert (
        client.delete(
            members_url(org_id, ctx["member"]), headers=auth_headers(ctx["admin"])
        ).status_code
        == 204
    )
    assert (
        client.delete(
            members_url(org_id, ctx["admin"]), headers=auth_headers(ctx["owner"])
        ).status_code
        == 204
    )


def test_member_cannot_remove_others_but_can_leave(client, make_user):
    ctx = make_org_with_roles(client, make_user)
    org_id = ctx["org"]["id"]
    forbidden = client.delete(
        members_url(org_id, ctx["admin"]), headers=auth_headers(ctx["member"])
    )
    assert forbidden.status_code == 403
    leave = client.delete(members_url(org_id, ctx["member"]), headers=auth_headers(ctx["member"]))
    assert leave.status_code == 204


def test_admin_cannot_remove_an_owner(client, make_user):
    ctx = make_org_with_roles(client, make_user)
    response = client.delete(
        members_url(ctx["org"]["id"], ctx["owner"]), headers=auth_headers(ctx["admin"])
    )
    assert response.status_code == 403


def test_removed_member_loses_access_immediately(client, make_user):
    ctx = make_org_with_roles(client, make_user)
    org_id = ctx["org"]["id"]
    headers = auth_headers(ctx["member"])  # token stays valid; membership is checked per request
    assert client.get(f"{API}/organizations/{org_id}", headers=headers).status_code == 200
    client.delete(members_url(org_id, ctx["member"]), headers=auth_headers(ctx["owner"]))
    assert client.get(f"{API}/organizations/{org_id}", headers=headers).status_code == 404


def test_removed_member_can_be_reinvited(client, make_user):
    ctx = make_org_with_roles(client, make_user)
    org_id = ctx["org"]["id"]
    client.delete(members_url(org_id, ctx["member"]), headers=auth_headers(ctx["owner"]))
    join_org(client, org_id, ctx["owner"], ctx["member"], "MEMBER")
    assert (
        client.get(f"{API}/organizations/{org_id}", headers=auth_headers(ctx["member"])).status_code
        == 200
    )


@pytest.mark.parametrize("path_suffix", ["", "/members"])
def test_role_is_read_fresh_on_every_request(client, make_user, path_suffix):
    """Demotion takes effect immediately; roles are not baked into the JWT."""
    ctx = make_org_with_roles(client, make_user)
    org_id = ctx["org"]["id"]
    headers = auth_headers(ctx["admin"])
    assert (
        client.patch(
            f"{API}/organizations/{org_id}", json={"name": "A"}, headers=headers
        ).status_code
        == 200
    )
    set_role(client, org_id, ctx["owner"], ctx["admin"], "MEMBER")
    assert (
        client.patch(
            f"{API}/organizations/{org_id}", json={"name": "B"}, headers=headers
        ).status_code
        == 403
    )
