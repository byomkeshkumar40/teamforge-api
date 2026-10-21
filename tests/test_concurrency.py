"""Last-owner protection under real concurrent requests against PostgreSQL.

Two owners try to remove each other's ownership at the same moment. Without row locking,
both requests would see "another owner exists", both would succeed, and the organization
would be left with zero owners. The organization-row lock in `services/members.py`
serialises them, so exactly one wins.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app.main import create_app
from app.models import Membership, Role, User
from tests.helpers import API, auth_headers, create_org, join_org

ROUNDS = 12


def owners(db, org_id) -> int:
    db.expire_all()
    return db.scalar(
        select(func.count())
        .select_from(Membership)
        .where(Membership.organization_id == org_id, Membership.role == Role.OWNER)
    )


def race(requests: list) -> list[int]:
    """Fire the callables at the same instant, each with its own client; return status codes."""
    barrier = threading.Barrier(len(requests))
    app = create_app()

    def run(make_request):
        with TestClient(app) as thread_client:
            barrier.wait()
            return make_request(thread_client).status_code

    with ThreadPoolExecutor(max_workers=len(requests)) as pool:
        return list(pool.map(run, requests))


def demote(org_id, actor, target):
    return lambda c: c.patch(
        f"{API}/organizations/{org_id}/members/{target.id}",
        json={"role": "MEMBER"},
        headers=auth_headers(actor),
    )


def remove(org_id, actor, target):
    return lambda c: c.delete(
        f"{API}/organizations/{org_id}/members/{target.id}", headers=auth_headers(actor)
    )


@pytest.fixture
def two_owners(client, make_user):
    def build():
        a, b = make_user(), make_user()
        org = create_org(client, a)
        join_org(client, org["id"], a, b, "ADMIN")
        client.patch(
            f"{API}/organizations/{org['id']}/members/{b.id}",
            json={"role": "OWNER"},
            headers=auth_headers(a),
        )
        return org["id"], a, b

    return build


def test_two_owners_demoting_each_other_never_leaves_zero_owners(two_owners, db):
    for _ in range(ROUNDS):
        org_id, a, b = two_owners()

        statuses = sorted(race([demote(org_id, a, b), demote(org_id, b, a)]))
        assert owners(db, org_id) == 1
        assert statuses[0] == 200 and statuses[1] in (403, 409)


def test_two_owners_leaving_at_once_never_leaves_zero_owners(two_owners, db):
    for _ in range(ROUNDS):
        org_id, a, b = two_owners()

        statuses = sorted(race([remove(org_id, a, a), remove(org_id, b, b)]))
        assert owners(db, org_id) == 1
        assert statuses == [204, 409]


def test_owners_removing_each_other_at_once_never_leaves_zero_owners(two_owners, db):
    for _ in range(ROUNDS):
        org_id, a, b = two_owners()

        statuses = sorted(race([remove(org_id, a, b), remove(org_id, b, a)]))
        assert owners(db, org_id) == 1
        assert statuses[0] == 204 and statuses[1] in (404, 409)


def test_same_invitation_accepted_twice_at_once_creates_one_membership(client, make_user, db):
    owner, invitee = make_user(), make_user("race@example.com")
    org = create_org(client, owner)
    token = client.post(
        f"{API}/organizations/{org['id']}/invitations",
        json={"email": invitee.email},
        headers=auth_headers(owner),
    ).json()["token"]

    def accept(c):
        return c.post(
            f"{API}/invitations/accept", json={"token": token}, headers=auth_headers(invitee)
        )

    statuses = sorted(race([accept, accept]))
    assert statuses == [200, 400]
    memberships = db.scalars(select(Membership).where(Membership.user_id == invitee.id)).all()
    assert len(memberships) == 1


def test_simultaneous_registration_with_same_email_creates_one_account(db):
    def register(c):
        return c.post(
            f"{API}/auth/register",
            json={"email": "twin@example.com", "password": "Correct-Horse-9", "full_name": "Twin"},
        )

    for _ in range(5):
        statuses = sorted(race([register, register]))
        assert statuses == [201, 409]
        count = db.scalar(
            select(func.count()).select_from(User).where(User.email == "twin@example.com")
        )
        assert count == 1
        db.execute(text("DELETE FROM users"))
        db.commit()
