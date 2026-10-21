"""Every tenant-scoped endpoint x every kind of caller, against a fresh world each time.

Callers: owner, admin, member (all of the organization), outsider (authenticated but in no
organization shown here) and anonymous. Expected status codes encode the documented policy:
  - anonymous            -> 401 everywhere
  - outsider             -> 404 everywhere (the organization's existence is not confirmed)
  - member               -> reads and task work; 403 on management actions
  - admin                -> everything except deleting the organization
  - owner                -> everything
"""

import pytest

from tests.helpers import (
    API,
    auth_headers,
    create_org,
    create_project,
    create_task,
    make_org_with_roles,
)

ACTORS = ["owner", "admin", "member", "outsider", "anonymous"]

# (name, method, path template, body factory, expected status per actor in ACTORS order)
# Path placeholders: {org} {project} {task} {member} {admin} {invitation}
CASES = [
    ("get org", "GET", "/organizations/{org}", None, (200, 200, 200, 404, 401)),
    (
        "rename org",
        "PATCH",
        "/organizations/{org}",
        lambda w: {"name": "N"},
        (200, 200, 403, 404, 401),
    ),
    ("delete org", "DELETE", "/organizations/{org}", None, (204, 403, 403, 404, 401)),
    ("list members", "GET", "/organizations/{org}/members", None, (200, 200, 200, 404, 401)),
    (
        "change role",
        "PATCH",
        "/organizations/{org}/members/{member}",
        lambda w: {"role": "ADMIN"},
        (200, 200, 403, 404, 401),
    ),
    # a member may remove themselves, so the target here is the admin
    (
        "remove member",
        "DELETE",
        "/organizations/{org}/members/{admin}",
        None,
        (204, 204, 403, 404, 401),
    ),
    (
        "invite",
        "POST",
        "/organizations/{org}/invitations",
        lambda w: {"email": "new@example.com"},
        (201, 201, 403, 404, 401),
    ),
    (
        "list invitations",
        "GET",
        "/organizations/{org}/invitations",
        None,
        (200, 200, 403, 404, 401),
    ),
    (
        "revoke invitation",
        "DELETE",
        "/organizations/{org}/invitations/{invitation}",
        None,
        (204, 204, 403, 404, 401),
    ),
    (
        "create project",
        "POST",
        "/organizations/{org}/projects",
        lambda w: {"name": "P2"},
        (201, 201, 403, 404, 401),
    ),
    ("list projects", "GET", "/organizations/{org}/projects", None, (200, 200, 200, 404, 401)),
    (
        "get project",
        "GET",
        "/organizations/{org}/projects/{project}",
        None,
        (200, 200, 200, 404, 401),
    ),
    (
        "update project",
        "PATCH",
        "/organizations/{org}/projects/{project}",
        lambda w: {"name": "Renamed"},
        (200, 200, 403, 404, 401),
    ),
    (
        "archive project",
        "POST",
        "/organizations/{org}/projects/{project}/archive",
        None,
        (200, 200, 403, 404, 401),
    ),
    (
        "unarchive project",
        "POST",
        "/organizations/{org}/projects/{project}/unarchive",
        None,
        (200, 200, 403, 404, 401),
    ),
    (
        "create task",
        "POST",
        "/organizations/{org}/tasks",
        lambda w: {"project_id": w["project"], "title": "T2"},
        (201, 201, 201, 404, 401),
    ),
    ("list tasks", "GET", "/organizations/{org}/tasks", None, (200, 200, 200, 404, 401)),
    ("get task", "GET", "/organizations/{org}/tasks/{task}", None, (200, 200, 200, 404, 401)),
    (
        "update task",
        "PATCH",
        "/organizations/{org}/tasks/{task}",
        lambda w: {"status": "DONE"},
        (200, 200, 200, 404, 401),
    ),
    (
        "assign task",
        "PUT",
        "/organizations/{org}/tasks/{task}/assignee",
        lambda w: {"assignee_id": w["member"]},
        (200, 200, 200, 404, 401),
    ),
    # the task was created by the owner, so a member may not delete it
    ("delete task", "DELETE", "/organizations/{org}/tasks/{task}", None, (204, 204, 403, 404, 401)),
]

PARAMS = [
    pytest.param(case, actor, id=f"{case[0].replace(' ', '-')}:{ACTORS[actor]}")
    for case in CASES
    for actor in range(len(ACTORS))
]


@pytest.fixture
def world(client, make_user):
    ctx = make_org_with_roles(client, make_user)
    org_id = ctx["org"]["id"]
    project = create_project(client, org_id, ctx["owner"])
    task = create_task(client, org_id, ctx["owner"], project["id"])
    invitation = client.post(
        f"{API}/organizations/{org_id}/invitations",
        json={"email": "pending@example.com"},
        headers=auth_headers(ctx["owner"]),
    ).json()
    outsider = make_user()
    create_org(client, outsider, "Elsewhere")  # the outsider has an organization of their own
    return {
        "users": {**{k: ctx[k] for k in ("owner", "admin", "member")}, "outsider": outsider},
        "ids": {
            "org": org_id,
            "project": project["id"],
            "task": task["id"],
            "member": str(ctx["member"].id),
            "admin": str(ctx["admin"].id),
            "invitation": invitation["id"],
        },
    }


@pytest.mark.parametrize(("case", "actor"), PARAMS)
def test_authorization_matrix(client, world, case, actor):
    name, method, template, body_factory, expected = case
    actor_name = ACTORS[actor]
    headers = {} if actor_name == "anonymous" else auth_headers(world["users"][actor_name])
    body = body_factory(world["ids"]) if body_factory else None

    response = client.request(
        method, API + template.format(**world["ids"]), json=body, headers=headers
    )

    assert response.status_code == expected[actor], (
        f"{actor_name} {method} {template}: expected {expected[actor]}, "
        f"got {response.status_code} {response.text}"
    )
