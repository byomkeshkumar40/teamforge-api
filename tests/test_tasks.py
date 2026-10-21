import uuid

import pytest
from sqlalchemy import select

from app.models import Task
from tests.helpers import (
    API,
    auth_headers,
    create_org,
    create_project,
    create_task,
    join_org,
    make_org_with_roles,
)


def turl(org_id, suffix=""):
    return f"{API}/organizations/{org_id}/tasks{suffix}"


@pytest.fixture
def team(client, make_user):
    ctx = make_org_with_roles(client, make_user)
    ctx["project"] = create_project(client, ctx["org"]["id"], ctx["owner"])
    return ctx


def test_create_task_with_defaults(client, team):
    task = create_task(
        client, team["org"]["id"], team["member"], team["project"]["id"], "Write docs"
    )
    assert task["status"] == "TODO" and task["priority"] == "MEDIUM"
    assert task["assignee_id"] is None and task["due_date"] is None
    assert task["created_by"] == str(team["member"].id)  # members can create tasks
    assert task["organization_id"] == team["org"]["id"]


def test_create_task_with_all_fields(client, team):
    task = create_task(
        client,
        team["org"]["id"],
        team["admin"],
        team["project"]["id"],
        "Ship it",
        description="Release 1.0",
        status="IN_REVIEW",
        priority="URGENT",
        assignee_id=str(team["member"].id),
        due_date="2030-05-17",
    )
    assert (task["status"], task["priority"], task["due_date"]) == (
        "IN_REVIEW",
        "URGENT",
        "2030-05-17",
    )
    assert task["assignee_id"] == str(team["member"].id)


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"status": "STARTED"},
        {"priority": "CRITICAL"},
        {"due_date": "tomorrow"},
        {"due_date": "2030-13-45"},
        {"assignee_id": "not-a-uuid"},
        {"description": "d" * 10001},
    ],
)
def test_create_task_validation(client, team, overrides):
    body = {"project_id": team["project"]["id"], "title": "ok"} | overrides
    response = client.post(turl(team["org"]["id"]), json=body, headers=auth_headers(team["owner"]))
    assert response.status_code == 422


def test_create_task_requires_project_and_title(client, team):
    headers = auth_headers(team["owner"])
    assert (
        client.post(turl(team["org"]["id"]), json={"title": "x"}, headers=headers).status_code
        == 422
    )
    body = {"project_id": team["project"]["id"]}
    assert client.post(turl(team["org"]["id"]), json=body, headers=headers).status_code == 422


def test_create_task_with_unknown_project_is_404(client, team):
    response = client.post(
        turl(team["org"]["id"]),
        json={"project_id": str(uuid.uuid4()), "title": "x"},
        headers=auth_headers(team["owner"]),
    )
    assert response.status_code == 404


def test_update_task_partial_and_clearing_fields(client, team):
    org_id = team["org"]["id"]
    task = create_task(
        client,
        org_id,
        team["owner"],
        team["project"]["id"],
        description="d",
        due_date="2030-01-01",
        assignee_id=str(team["member"].id),
    )
    path = turl(org_id, f"/{task['id']}")
    response = client.patch(
        path,
        json={"status": "IN_PROGRESS", "priority": "HIGH"},
        headers=auth_headers(team["member"]),
    )
    body = response.json()
    assert response.status_code == 200
    assert (body["status"], body["priority"], body["title"]) == ("IN_PROGRESS", "HIGH", "Task")
    assert body["description"] == "d" and body["assignee_id"] == str(team["member"].id)  # untouched

    cleared = client.patch(
        path,
        json={"description": None, "due_date": None, "assignee_id": None},
        headers=auth_headers(team["owner"]),
    ).json()
    assert (
        cleared["description"] is None
        and cleared["due_date"] is None
        and cleared["assignee_id"] is None
    )
    assert cleared["updated_at"] >= task["updated_at"]


@pytest.mark.parametrize(
    "body", [{"title": None}, {"status": None}, {"priority": None}, {"status": "NOPE"}]
)
def test_update_task_rejects_null_or_invalid_required_fields(client, team, body):
    task = create_task(client, team["org"]["id"], team["owner"], team["project"]["id"])
    response = client.patch(
        turl(team["org"]["id"], f"/{task['id']}"), json=body, headers=auth_headers(team["owner"])
    )
    assert response.status_code == 422


def test_project_cannot_be_changed_through_update(client, team):
    other = create_project(client, team["org"]["id"], team["owner"], "Other")
    task = create_task(client, team["org"]["id"], team["owner"], team["project"]["id"])
    client.patch(
        turl(team["org"]["id"], f"/{task['id']}"),
        json={"project_id": other["id"]},
        headers=auth_headers(team["owner"]),
    )
    fetched = client.get(
        turl(team["org"]["id"], f"/{task['id']}"), headers=auth_headers(team["owner"])
    ).json()
    assert fetched["project_id"] == team["project"]["id"]


# ------------------------------------------------------------------ assignment


def test_assign_and_unassign(client, team):
    org_id = team["org"]["id"]
    task = create_task(client, org_id, team["owner"], team["project"]["id"])
    path = turl(org_id, f"/{task['id']}/assignee")
    assigned = client.put(
        path, json={"assignee_id": str(team["admin"].id)}, headers=auth_headers(team["member"])
    )
    assert assigned.status_code == 200 and assigned.json()["assignee_id"] == str(team["admin"].id)
    cleared = client.put(path, json={"assignee_id": None}, headers=auth_headers(team["member"]))
    assert cleared.json()["assignee_id"] is None


def test_assignee_must_belong_to_the_organization(client, team, make_user):
    outsider = make_user()
    org_id = team["org"]["id"]
    # outsider is a member of ANOTHER org, which makes the check non-trivial
    create_org(client, outsider, "Elsewhere")
    task = create_task(client, org_id, team["owner"], team["project"]["id"])

    create_bad = client.post(
        turl(org_id),
        json={"project_id": team["project"]["id"], "title": "x", "assignee_id": str(outsider.id)},
        headers=auth_headers(team["owner"]),
    )
    patch_bad = client.patch(
        turl(org_id, f"/{task['id']}"),
        json={"assignee_id": str(outsider.id)},
        headers=auth_headers(team["owner"]),
    )
    put_bad = client.put(
        turl(org_id, f"/{task['id']}/assignee"),
        json={"assignee_id": str(outsider.id)},
        headers=auth_headers(team["owner"]),
    )
    unknown = client.put(
        turl(org_id, f"/{task['id']}/assignee"),
        json={"assignee_id": str(uuid.uuid4())},
        headers=auth_headers(team["owner"]),
    )
    for response in (create_bad, patch_bad, put_bad, unknown):
        assert response.status_code == 422
        assert (
            response.json()["error"]["message"] == "Assignee must be a member of the organization"
        )


def test_removing_a_member_unassigns_their_tasks(client, db, team):
    org_id = team["org"]["id"]
    task = create_task(
        client, org_id, team["owner"], team["project"]["id"], assignee_id=str(team["member"].id)
    )
    response = client.delete(
        f"{API}/organizations/{org_id}/members/{team['member'].id}",
        headers=auth_headers(team["owner"]),
    )
    assert response.status_code == 204
    assert db.scalar(select(Task.assignee_id).where(Task.id == uuid.UUID(task["id"]))) is None


def test_member_who_left_cannot_be_assigned_again_until_rejoined(client, team):
    org_id = team["org"]["id"]
    client.delete(
        f"{API}/organizations/{org_id}/members/{team['member'].id}",
        headers=auth_headers(team["owner"]),
    )
    task = create_task(client, org_id, team["owner"], team["project"]["id"])
    response = client.put(
        turl(org_id, f"/{task['id']}/assignee"),
        json={"assignee_id": str(team["member"].id)},
        headers=auth_headers(team["owner"]),
    )
    assert response.status_code == 422
    join_org(client, org_id, team["owner"], team["member"])
    again = client.put(
        turl(org_id, f"/{task['id']}/assignee"),
        json={"assignee_id": str(team["member"].id)},
        headers=auth_headers(team["owner"]),
    )
    assert again.status_code == 200


# ---------------------------------------------------------------------- delete


def test_delete_permissions(client, team):
    org_id, project_id = team["org"]["id"], team["project"]["id"]
    by_owner = create_task(client, org_id, team["owner"], project_id)
    by_member = create_task(client, org_id, team["member"], project_id)

    # a member may not delete someone else's task, but may delete their own
    assert (
        client.delete(
            turl(org_id, f"/{by_owner['id']}"), headers=auth_headers(team["member"])
        ).status_code
        == 403
    )
    assert (
        client.delete(
            turl(org_id, f"/{by_member['id']}"), headers=auth_headers(team["member"])
        ).status_code
        == 204
    )
    # an admin may delete anyone's
    assert (
        client.delete(
            turl(org_id, f"/{by_owner['id']}"), headers=auth_headers(team["admin"])
        ).status_code
        == 204
    )
    assert (
        client.get(
            turl(org_id, f"/{by_owner['id']}"), headers=auth_headers(team["owner"])
        ).status_code
        == 404
    )


def test_delete_unknown_task_is_404(client, team):
    response = client.delete(
        turl(team["org"]["id"], f"/{uuid.uuid4()}"), headers=auth_headers(team["owner"])
    )
    assert response.status_code == 404


# ------------------------------------------------------------ archived projects


def test_tasks_of_archived_projects_are_read_only(client, team):
    org_id = team["org"]["id"]
    task = create_task(client, org_id, team["owner"], team["project"]["id"])
    client.post(
        f"{API}/organizations/{org_id}/projects/{team['project']['id']}/archive",
        headers=auth_headers(team["owner"]),
    )
    owner = auth_headers(team["owner"])
    assert client.get(turl(org_id, f"/{task['id']}"), headers=owner).status_code == 200
    assert (
        client.post(
            turl(org_id), json={"project_id": team["project"]["id"], "title": "n"}, headers=owner
        ).status_code
        == 409
    )
    assert (
        client.patch(turl(org_id, f"/{task['id']}"), json={"title": "n"}, headers=owner).status_code
        == 409
    )
    assert client.delete(turl(org_id, f"/{task['id']}"), headers=owner).status_code == 409


# ----------------------------------------------------------- tenant isolation


@pytest.fixture
def rival(client, make_user):
    """A second tenant (bob) with its own project and task, next to `team` (alice's org)."""
    bob = make_user()
    org = create_org(client, bob, "Rival")
    project = create_project(client, org["id"], bob, "Rival project")
    return {
        "bob": bob,
        "org": org,
        "project": project,
        "task": create_task(client, org["id"], bob, project["id"], "Rival secret"),
    }


def test_cannot_read_another_tenants_task(client, team, rival):
    own_task = create_task(client, team["org"]["id"], team["owner"], team["project"]["id"])
    for org_id in (team["org"]["id"], rival["org"]["id"]):
        # as a member of `team`, ask for the rival's task id through each org URL
        response = client.get(
            turl(org_id, f"/{rival['task']['id']}"), headers=auth_headers(team["owner"])
        )
        assert response.status_code == 404
        assert "Rival secret" not in response.text
    assert own_task["title"] == "Task"


def test_cannot_update_another_tenants_task(client, db, team, rival):
    for org_id in (team["org"]["id"], rival["org"]["id"]):
        response = client.patch(
            turl(org_id, f"/{rival['task']['id']}"),
            json={"title": "Hacked", "status": "DONE"},
            headers=auth_headers(team["owner"]),
        )
        assert response.status_code == 404
    stored = db.scalar(select(Task).where(Task.id == uuid.UUID(rival["task"]["id"])))
    assert (stored.title, stored.status.value) == ("Rival secret", "TODO")


def test_cannot_assign_or_delete_another_tenants_task(client, db, team, rival):
    for org_id in (team["org"]["id"], rival["org"]["id"]):
        assign = client.put(
            turl(org_id, f"/{rival['task']['id']}/assignee"),
            json={"assignee_id": str(team["owner"].id)},
            headers=auth_headers(team["owner"]),
        )
        delete = client.delete(
            turl(org_id, f"/{rival['task']['id']}"), headers=auth_headers(team["owner"])
        )
        assert assign.status_code == delete.status_code == 404
    stored = db.scalar(select(Task).where(Task.id == uuid.UUID(rival["task"]["id"])))
    assert stored is not None and stored.assignee_id is None


def test_cannot_create_a_task_in_another_tenants_project(client, db, team, rival):
    # my org URL, their project id
    mine = client.post(
        turl(team["org"]["id"]),
        json={"project_id": rival["project"]["id"], "title": "Plant"},
        headers=auth_headers(team["owner"]),
    )
    # their org URL
    theirs = client.post(
        turl(rival["org"]["id"]),
        json={"project_id": rival["project"]["id"], "title": "Plant"},
        headers=auth_headers(team["owner"]),
    )
    assert mine.status_code == 404 and theirs.status_code == 404
    assert db.scalar(select(Task.id).where(Task.title == "Plant")) is None


def test_cannot_list_another_tenants_tasks(client, team, rival):
    assert (
        client.get(turl(rival["org"]["id"]), headers=auth_headers(team["owner"])).status_code == 404
    )
    mine = client.get(
        turl(team["org"]["id"]) + f"?project_id={rival['project']['id']}",
        headers=auth_headers(team["owner"]),
    ).json()
    assert mine["total"] == 0  # filtering by a foreign project id yields nothing, never their data


def test_cannot_assign_a_user_from_another_tenant(client, team, rival):
    task = create_task(client, team["org"]["id"], team["owner"], team["project"]["id"])
    response = client.put(
        turl(team["org"]["id"], f"/{task['id']}/assignee"),
        json={"assignee_id": str(rival["bob"].id)},
        headers=auth_headers(team["owner"]),
    )
    assert response.status_code == 422


# ----------------------------------------------------------------- end to end


def test_full_workflow_register_to_archive(client, make_user):
    """Register -> login -> org -> invite -> project -> task -> assign -> update -> archive."""
    password = "Correct-Horse-9"
    for email, name in (("ada@example.com", "Ada"), ("bob@example.com", "Bob")):
        assert (
            client.post(
                f"{API}/auth/register",
                json={"email": email, "password": password, "full_name": name},
            ).status_code
            == 201
        )

    def login(email):
        token = client.post(
            f"{API}/auth/login", json={"email": email, "password": password}
        ).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    ada, bob = login("ada@example.com"), login("bob@example.com")
    org = client.post(f"{API}/organizations", json={"name": "Acme"}, headers=ada).json()
    invitation = client.post(
        f"{API}/organizations/{org['id']}/invitations",
        json={"email": "bob@example.com", "role": "MEMBER"},
        headers=ada,
    ).json()
    assert (
        client.post(
            f"{API}/invitations/accept", json={"token": invitation["token"]}, headers=bob
        ).status_code
        == 200
    )

    project = client.post(
        f"{API}/organizations/{org['id']}/projects", json={"name": "Launch"}, headers=ada
    ).json()
    task = client.post(
        turl(org["id"]),
        json={"project_id": project["id"], "title": "Ship v1", "priority": "HIGH"},
        headers=ada,
    ).json()
    bob_id = client.get(f"{API}/users/me", headers=bob).json()["id"]
    assigned = client.put(
        turl(org["id"], f"/{task['id']}/assignee"), json={"assignee_id": bob_id}, headers=ada
    )
    assert assigned.json()["assignee_id"] == bob_id

    done = client.patch(turl(org["id"], f"/{task['id']}"), json={"status": "DONE"}, headers=bob)
    assert done.json()["status"] == "DONE"
    mine = client.get(turl(org["id"]) + f"?assignee_id={bob_id}&status=DONE", headers=bob).json()
    assert mine["total"] == 1

    archived = client.post(
        f"{API}/organizations/{org['id']}/projects/{project['id']}/archive", headers=ada
    )
    assert archived.json()["archived_at"] is not None
    assert client.get(f"{API}/organizations/{org['id']}/projects", headers=ada).json()["total"] == 0
