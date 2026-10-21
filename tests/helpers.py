from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.models import User

TEST_PASSWORD = "Correct-Horse-9"
API = "/api/v1"


def auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def create_org(client: TestClient, user: User, name: str = "Acme") -> dict:
    response = client.post(f"{API}/organizations", json={"name": name}, headers=auth_headers(user))
    assert response.status_code == 201, response.text
    return response.json()


def join_org(
    client: TestClient, org_id: str, inviter: User, user: User, role: str = "MEMBER"
) -> None:
    """Invite `user` and accept the invitation, using the real endpoints."""
    created = client.post(
        f"{API}/organizations/{org_id}/invitations",
        json={"email": user.email, "role": role},
        headers=auth_headers(inviter),
    )
    assert created.status_code == 201, created.text
    accepted = client.post(
        f"{API}/invitations/accept",
        json={"token": created.json()["token"]},
        headers=auth_headers(user),
    )
    assert accepted.status_code == 200, accepted.text


def set_role(client: TestClient, org_id: str, actor: User, target: User, role: str):
    return client.patch(
        f"{API}/organizations/{org_id}/members/{target.id}",
        json={"role": role},
        headers=auth_headers(actor),
    )


def make_org_with_roles(client: TestClient, make_user) -> dict:
    """One org with an owner, an admin and a member. Returns users and the org dict."""
    owner, admin, member = make_user(), make_user(), make_user()
    org = create_org(client, owner)
    join_org(client, org["id"], owner, admin, "ADMIN")
    join_org(client, org["id"], owner, member, "MEMBER")
    return {"org": org, "owner": owner, "admin": admin, "member": member}


def create_project(client: TestClient, org_id: str, user: User, name: str = "Website", **extra):
    response = client.post(
        f"{API}/organizations/{org_id}/projects",
        json={"name": name, **extra},
        headers=auth_headers(user),
    )
    assert response.status_code == 201, response.text
    return response.json()
