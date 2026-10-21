import pytest
from sqlalchemy import select

from app.models import Membership, Organization
from tests.helpers import API, auth_headers, create_org, make_org_with_roles


def test_create_organization_makes_creator_owner(client, db, make_user):
    user = make_user()
    org = create_org(client, user, "  Acme Corp!  ")
    assert org["name"] == "Acme Corp!"
    assert org["role"] == "OWNER"
    assert org["slug"].startswith("acme-corp-")

    membership = db.scalar(select(Membership).where(Membership.user_id == user.id))
    assert str(membership.organization_id) == org["id"]


@pytest.mark.parametrize("body", [{}, {"name": ""}, {"name": "   "}, {"name": "x" * 101}])
def test_create_organization_validation(client, make_user, body):
    response = client.post(f"{API}/organizations", json=body, headers=auth_headers(make_user()))
    assert response.status_code == 422


def test_create_organization_requires_authentication(client):
    assert client.post(f"{API}/organizations", json={"name": "X"}).status_code == 401


def test_same_name_organizations_get_distinct_slugs(client, make_user):
    user = make_user()
    assert create_org(client, user, "Same")["slug"] != create_org(client, user, "Same")["slug"]


def test_list_shows_only_my_organizations_with_my_role(client, make_user):
    ada, bob = make_user(), make_user()
    create_org(client, ada, "Ada Org")
    create_org(client, bob, "Bob Org")
    body = client.get(f"{API}/organizations", headers=auth_headers(ada)).json()
    assert body["total"] == 1
    assert [o["name"] for o in body["items"]] == ["Ada Org"]
    assert body["items"][0]["role"] == "OWNER"


def test_list_organizations_pagination(client, make_user):
    user = make_user()
    for i in range(3):
        create_org(client, user, f"Org {i}")
    page = client.get(f"{API}/organizations?limit=2&offset=2", headers=auth_headers(user)).json()
    assert page["total"] == 3 and len(page["items"]) == 1
    assert page["limit"] == 2 and page["offset"] == 2


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "limit=abc", "offset=-1"])
def test_pagination_limits_are_enforced(client, make_user, query):
    response = client.get(f"{API}/organizations?{query}", headers=auth_headers(make_user()))
    assert response.status_code == 422


def test_user_can_belong_to_several_organizations(client, make_user):
    owner, user = make_user(), make_user()
    a, b = create_org(client, owner, "A"), create_org(client, owner, "B")
    from tests.helpers import join_org

    join_org(client, a["id"], owner, user, "ADMIN")
    join_org(client, b["id"], owner, user, "MEMBER")
    roles = {
        o["name"]: o["role"]
        for o in client.get(f"{API}/organizations", headers=auth_headers(user)).json()["items"]
    }
    assert roles == {"A": "ADMIN", "B": "MEMBER"}


def test_any_member_can_read_the_organization(client, make_user):
    ctx = make_org_with_roles(client, make_user)
    for who in ("owner", "admin", "member"):
        response = client.get(
            f"{API}/organizations/{ctx['org']['id']}", headers=auth_headers(ctx[who])
        )
        assert response.status_code == 200
        assert response.json()["role"] == who.upper()


@pytest.mark.parametrize(("who", "expected"), [("owner", 200), ("admin", 200), ("member", 403)])
def test_update_organization_permissions(client, make_user, who, expected):
    ctx = make_org_with_roles(client, make_user)
    response = client.patch(
        f"{API}/organizations/{ctx['org']['id']}",
        json={"name": "Renamed"},
        headers=auth_headers(ctx[who]),
    )
    assert response.status_code == expected


@pytest.mark.parametrize(("who", "expected"), [("admin", 403), ("member", 403), ("owner", 204)])
def test_delete_organization_is_owner_only(client, db, make_user, who, expected):
    ctx = make_org_with_roles(client, make_user)
    response = client.delete(
        f"{API}/organizations/{ctx['org']['id']}", headers=auth_headers(ctx[who])
    )
    assert response.status_code == expected
    still_exists = db.scalar(select(Organization.id)) is not None
    assert still_exists is (expected != 204)
    if expected == 204:
        assert db.scalar(select(Membership.id)) is None  # cascaded
