import uuid

import pytest

from tests.helpers import API, auth_headers, create_org, create_project, make_org_with_roles


def url(org_id, suffix=""):
    return f"{API}/organizations/{org_id}/projects{suffix}"


def test_create_and_get_project(client, make_user):
    ctx = make_org_with_roles(client, make_user)
    org_id = ctx["org"]["id"]
    project = create_project(client, org_id, ctx["owner"], "  Website  ", description="Redesign")
    assert project["name"] == "Website"
    assert project["organization_id"] == org_id
    assert project["archived_at"] is None
    assert project["created_by"] == str(ctx["owner"].id)

    for who in ("owner", "admin", "member"):  # every member can read
        response = client.get(url(org_id, f"/{project['id']}"), headers=auth_headers(ctx[who]))
        assert response.status_code == 200


@pytest.mark.parametrize(("who", "expected"), [("owner", 201), ("admin", 201), ("member", 403)])
def test_only_owner_and_admin_can_create_projects(client, make_user, who, expected):
    ctx = make_org_with_roles(client, make_user)
    response = client.post(
        url(ctx["org"]["id"]), json={"name": "P"}, headers=auth_headers(ctx[who])
    )
    assert response.status_code == expected


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": ""},
        {"name": "  "},
        {"name": "x" * 101},
        {"name": "ok", "description": "d" * 5001},
    ],
)
def test_create_project_validation(client, make_user, body):
    owner = make_user()
    org = create_org(client, owner)
    assert client.post(url(org["id"]), json=body, headers=auth_headers(owner)).status_code == 422


def test_update_project(client, make_user):
    ctx = make_org_with_roles(client, make_user)
    org_id = ctx["org"]["id"]
    project = create_project(client, org_id, ctx["owner"])
    response = client.patch(
        url(org_id, f"/{project['id']}"),
        json={"name": "Renamed"},
        headers=auth_headers(ctx["admin"]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed" and body["description"] is None
    assert body["updated_at"] >= project["updated_at"]


def test_update_project_rejects_null_name_and_member_role(client, make_user):
    ctx = make_org_with_roles(client, make_user)
    org_id = ctx["org"]["id"]
    project = create_project(client, org_id, ctx["owner"])
    path = url(org_id, f"/{project['id']}")
    assert (
        client.patch(path, json={"name": None}, headers=auth_headers(ctx["owner"])).status_code
        == 422
    )
    assert (
        client.patch(path, json={"name": "X"}, headers=auth_headers(ctx["member"])).status_code
        == 403
    )


def test_archive_hides_project_by_default_and_is_idempotent(client, make_user):
    owner = make_user()
    org = create_org(client, owner)
    keep = create_project(client, org["id"], owner, "Keep")
    gone = create_project(client, org["id"], owner, "Gone")
    headers = auth_headers(owner)

    first = client.post(url(org["id"], f"/{gone['id']}/archive"), headers=headers)
    second = client.post(url(org["id"], f"/{gone['id']}/archive"), headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["archived_at"] == second.json()["archived_at"] is not None

    default = client.get(url(org["id"]), headers=headers).json()
    assert [p["id"] for p in default["items"]] == [keep["id"]]
    everything = client.get(url(org["id"]) + "?include_archived=true", headers=headers).json()
    assert everything["total"] == 2
    # archived projects are still readable by id
    assert client.get(url(org["id"], f"/{gone['id']}"), headers=headers).status_code == 200


def test_archived_project_is_read_only_until_unarchived(client, make_user):
    owner = make_user()
    org = create_org(client, owner)
    project = create_project(client, org["id"], owner)
    headers = auth_headers(owner)
    client.post(url(org["id"], f"/{project['id']}/archive"), headers=headers)
    assert (
        client.patch(
            url(org["id"], f"/{project['id']}"), json={"name": "N"}, headers=headers
        ).status_code
        == 409
    )
    restored = client.post(url(org["id"], f"/{project['id']}/unarchive"), headers=headers)
    assert restored.json()["archived_at"] is None
    assert (
        client.patch(
            url(org["id"], f"/{project['id']}"), json={"name": "N"}, headers=headers
        ).status_code
        == 200
    )


def test_member_cannot_archive(client, make_user):
    ctx = make_org_with_roles(client, make_user)
    project = create_project(client, ctx["org"]["id"], ctx["owner"])
    response = client.post(
        url(ctx["org"]["id"], f"/{project['id']}/archive"), headers=auth_headers(ctx["member"])
    )
    assert response.status_code == 403


def test_unknown_project_is_404(client, make_user):
    owner = make_user()
    org = create_org(client, owner)
    assert (
        client.get(url(org["id"], f"/{uuid.uuid4()}"), headers=auth_headers(owner)).status_code
        == 404
    )


def test_list_pagination_sorting_and_search(client, make_user):
    owner = make_user()
    org = create_org(client, owner)
    headers = auth_headers(owner)
    for name in ("Charlie", "Alpha", "Bravo", "100%_done"):
        create_project(client, org["id"], owner, name)

    by_name = client.get(url(org["id"]) + "?sort_by=name&order=asc", headers=headers).json()
    assert [p["name"] for p in by_name["items"]] == ["100%_done", "Alpha", "Bravo", "Charlie"]
    descending = client.get(url(org["id"]) + "?sort_by=name&order=desc", headers=headers).json()
    assert [p["name"] for p in descending["items"]] == ["Charlie", "Bravo", "Alpha", "100%_done"]

    page = client.get(
        url(org["id"]) + "?sort_by=name&order=asc&limit=2&offset=2", headers=headers
    ).json()
    assert page["total"] == 4 and len(page["items"]) == 2

    # LIKE wildcards in the search term are matched literally, not as patterns
    literal = client.get(url(org["id"]) + "?q=%25_", headers=headers).json()
    assert [p["name"] for p in literal["items"]] == ["100%_done"]
    assert client.get(url(org["id"]) + "?q=BRAV", headers=headers).json()["total"] == 1


@pytest.mark.parametrize(
    "query",
    [
        "sort_by=password_hash",
        "sort_by=name;DROP TABLE projects",
        "sort_by=organization_id",
        "order=sideways",
        "limit=1000",
        "include_archived=maybe",
    ],
)
def test_invalid_query_parameters_are_rejected(client, make_user, query):
    owner = make_user()
    org = create_org(client, owner)
    response = client.get(url(org["id"]) + f"?{query}", headers=auth_headers(owner))
    assert response.status_code == 422


# ----------------------------------------------------------- tenant isolation


@pytest.fixture
def two_orgs(client, make_user):
    alice, bob = make_user(), make_user()
    org_a, org_b = create_org(client, alice, "A"), create_org(client, bob, "B")
    return {
        "alice": alice,
        "bob": bob,
        "org_a": org_a,
        "org_b": org_b,
        "project_a": create_project(client, org_a["id"], alice, "A-secret"),
        "project_b": create_project(client, org_b["id"], bob, "B-project"),
    }


def test_cannot_read_another_tenants_project(client, two_orgs):
    t = two_orgs
    # through the foreign org's URL (not a member)
    r1 = client.get(
        url(t["org_a"]["id"], f"/{t['project_a']['id']}"), headers=auth_headers(t["bob"])
    )
    # through MY org's URL with the foreign project id (member, but id is not in my org)
    r2 = client.get(
        url(t["org_b"]["id"], f"/{t['project_a']['id']}"), headers=auth_headers(t["bob"])
    )
    assert r1.status_code == r2.status_code == 404
    assert "A-secret" not in r1.text + r2.text


def test_cannot_list_another_tenants_projects(client, two_orgs):
    t = two_orgs
    assert client.get(url(t["org_a"]["id"]), headers=auth_headers(t["bob"])).status_code == 404
    mine = client.get(url(t["org_b"]["id"]), headers=auth_headers(t["bob"])).json()
    assert [p["name"] for p in mine["items"]] == ["B-project"]


def test_cannot_update_another_tenants_project(client, two_orgs):
    t = two_orgs
    for org_key in ("org_a", "org_b"):  # via their org URL and via my own org URL
        response = client.patch(
            url(t[org_key]["id"], f"/{t['project_a']['id']}"),
            json={"name": "Hacked"},
            headers=auth_headers(t["bob"]),
        )
        assert response.status_code == 404
    still = client.get(
        url(t["org_a"]["id"], f"/{t['project_a']['id']}"), headers=auth_headers(t["alice"])
    )
    assert still.json()["name"] == "A-secret"


def test_cannot_archive_or_unarchive_another_tenants_project(client, two_orgs):
    t = two_orgs
    for action in ("archive", "unarchive"):
        for org_key in ("org_a", "org_b"):
            response = client.post(
                url(t[org_key]["id"], f"/{t['project_a']['id']}/{action}"),
                headers=auth_headers(t["bob"]),
            )
            assert response.status_code == 404
    refreshed = client.get(
        url(t["org_a"]["id"], f"/{t['project_a']['id']}"), headers=auth_headers(t["alice"])
    )
    assert refreshed.json()["archived_at"] is None


def test_cannot_create_a_project_in_another_tenant(client, two_orgs):
    t = two_orgs
    response = client.post(
        url(t["org_a"]["id"]), json={"name": "Plant"}, headers=auth_headers(t["bob"])
    )
    assert response.status_code == 404
    names = [
        p["name"]
        for p in client.get(url(t["org_a"]["id"]), headers=auth_headers(t["alice"])).json()["items"]
    ]
    assert names == ["A-secret"]
