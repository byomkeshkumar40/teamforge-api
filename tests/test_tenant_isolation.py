"""Cross-tenant isolation at the organization level: read, write, update and delete.

Convention under test: a user who is NOT a member of an organization gets 404 for every
route under it, identical to the response for an organization that does not exist, so the
API never confirms that another tenant's organization exists.
"""

import uuid

import pytest
from sqlalchemy import select

from app.models import Membership, Organization
from tests.helpers import API, auth_headers, create_org, join_org


@pytest.fixture
def tenants(client, make_user):
    """Two organizations with one owner each, plus a user who belongs to neither."""
    alice, bob, nobody = make_user(), make_user(), make_user()
    return {
        "alice": alice,
        "bob": bob,
        "nobody": nobody,
        "org_a": create_org(client, alice, "Org A"),
        "org_b": create_org(client, bob, "Org B"),
    }


def test_non_member_cannot_read_another_tenants_organization(client, tenants):
    url = f"{API}/organizations/{tenants['org_a']['id']}"
    for path in ("", "/members", "/invitations"):
        response = client.get(url + path, headers=auth_headers(tenants["bob"]))
        assert response.status_code == 404, path


def test_non_member_cannot_update_another_tenants_organization(client, db, tenants):
    response = client.patch(
        f"{API}/organizations/{tenants['org_a']['id']}",
        json={"name": "Hijacked"},
        headers=auth_headers(tenants["bob"]),
    )
    assert response.status_code == 404
    assert db.scalar(select(Organization.name).where(Organization.name == "Hijacked")) is None


def test_non_member_cannot_delete_another_tenants_organization(client, db, tenants):
    response = client.delete(
        f"{API}/organizations/{tenants['org_a']['id']}", headers=auth_headers(tenants["bob"])
    )
    assert response.status_code == 404
    assert db.scalar(
        select(Organization.id).where(Organization.id == uuid.UUID(tenants["org_a"]["id"]))
    )


def test_non_member_cannot_modify_memberships_of_another_tenant(client, db, tenants):
    org_a, alice, bob = tenants["org_a"]["id"], tenants["alice"], tenants["bob"]
    promote = client.patch(
        f"{API}/organizations/{org_a}/members/{bob.id}",
        json={"role": "OWNER"},
        headers=auth_headers(bob),
    )
    remove_owner = client.delete(
        f"{API}/organizations/{org_a}/members/{alice.id}", headers=auth_headers(bob)
    )
    assert promote.status_code == remove_owner.status_code == 404
    memberships = db.scalars(
        select(Membership).where(Membership.organization_id == uuid.UUID(org_a))
    ).all()
    assert [m.user_id for m in memberships] == [alice.id]


def test_non_member_cannot_create_or_revoke_invitations_in_another_tenant(client, tenants):
    org_a = tenants["org_a"]["id"]
    created = client.post(
        f"{API}/organizations/{org_a}/invitations",
        json={"email": "evil@example.com"},
        headers=auth_headers(tenants["bob"]),
    )
    revoked = client.delete(
        f"{API}/organizations/{org_a}/invitations/{uuid.uuid4()}",
        headers=auth_headers(tenants["bob"]),
    )
    assert created.status_code == revoked.status_code == 404


def test_invitation_of_one_org_cannot_be_revoked_through_another_org(client, make_user):
    alice, bob = make_user(), make_user()
    org_a, org_b = create_org(client, alice, "A"), create_org(client, bob, "B")
    invitation = client.post(
        f"{API}/organizations/{org_a['id']}/invitations",
        json={"email": "x@example.com"},
        headers=auth_headers(alice),
    ).json()
    # Bob IS an owner, but of org B: the invitation id must not resolve inside org B.
    response = client.delete(
        f"{API}/organizations/{org_b['id']}/invitations/{invitation['id']}",
        headers=auth_headers(bob),
    )
    assert response.status_code == 404
    still_there = client.get(
        f"{API}/organizations/{org_a['id']}/invitations", headers=auth_headers(alice)
    )
    assert still_there.json()["total"] == 1


def test_responses_do_not_reveal_whether_a_foreign_org_exists(client, tenants):
    real_but_foreign = client.get(
        f"{API}/organizations/{tenants['org_a']['id']}", headers=auth_headers(tenants["bob"])
    )
    nonexistent = client.get(
        f"{API}/organizations/{uuid.uuid4()}", headers=auth_headers(tenants["bob"])
    )
    assert real_but_foreign.status_code == nonexistent.status_code == 404
    assert real_but_foreign.json() == nonexistent.json()


def test_unauthenticated_requests_are_rejected_before_any_tenant_lookup(client, tenants):
    response = client.get(f"{API}/organizations/{tenants['org_a']['id']}")
    assert response.status_code == 401


def test_organization_listing_never_leaks_other_tenants(client, tenants):
    names = [
        o["name"]
        for o in client.get(f"{API}/organizations", headers=auth_headers(tenants["bob"])).json()[
            "items"
        ]
    ]
    assert names == ["Org B"]
    assert (
        client.get(f"{API}/organizations", headers=auth_headers(tenants["nobody"])).json()["total"]
        == 0
    )


def test_membership_in_one_org_grants_nothing_in_another(client, tenants):
    """Bob is an ADMIN in org A and an OWNER in org B; his power does not cross over."""
    join_org(client, tenants["org_a"]["id"], tenants["alice"], tenants["bob"], "MEMBER")
    # In org A he is only a MEMBER, even though he owns org B.
    response = client.patch(
        f"{API}/organizations/{tenants['org_a']['id']}",
        json={"name": "Nope"},
        headers=auth_headers(tenants["bob"]),
    )
    assert response.status_code == 403
    # and org B's data is still invisible to alice
    assert (
        client.get(
            f"{API}/organizations/{tenants['org_b']['id']}", headers=auth_headers(tenants["alice"])
        ).status_code
        == 404
    )


def test_malformed_org_id_is_a_validation_error_not_a_crash(client, tenants):
    response = client.get(f"{API}/organizations/not-a-uuid", headers=auth_headers(tenants["bob"]))
    assert response.status_code == 422
