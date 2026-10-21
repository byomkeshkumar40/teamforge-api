import logging
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select, text

from app.core.config import Settings
from app.main import create_app
from app.models import Organization, Task, User
from tests.helpers import (
    API,
    TEST_PASSWORD,
    auth_headers,
    create_org,
    create_project,
    create_task,
)

INJECTIONS = ["'; DROP TABLE tasks; --", "' OR '1'='1", '" OR 1=1 --', "%' OR title LIKE '%", "\\"]


# ------------------------------------------------------------------- headers


def test_api_responses_carry_security_headers(client):
    for path in ("/health", "/api/v1/users/me"):
        response = client.get(path)
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Frame-Options"] == "DENY"


def test_api_docs_can_be_disabled_by_configuration(monkeypatch):
    monkeypatch.setenv("ENABLE_API_DOCS", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as c:
            assert c.get("/docs").status_code == 404
            assert c.get("/openapi.json").status_code == 404
            assert c.get("/health").status_code == 200
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


# ------------------------------------------------------ unexpected failures


def test_unhandled_errors_return_generic_500_without_leaking_details(caplog):
    app = create_app()

    @app.get("/boom")
    def boom():
        raise RuntimeError("db password is hunter2")

    caplog.set_level(logging.ERROR)
    with TestClient(app, raise_server_exceptions=False) as c:
        response = c.get("/boom")
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Internal server error"}
    }
    assert "hunter2" not in response.text  # not leaked to the client
    assert any(r.exc_info for r in caplog.records)  # but recorded server-side for debugging


def test_failed_organization_creation_leaves_nothing_behind(client, db, make_user, monkeypatch):
    """Both rows are written in one transaction: if the membership insert fails, no org exists."""
    import app.services.organizations as org_service

    class ExplodingMembership:
        def __init__(self, **_):
            raise RuntimeError("simulated failure after the organization row was flushed")

    monkeypatch.setattr(org_service, "Membership", ExplodingMembership)
    user = make_user()
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        response = c.post(
            f"{API}/organizations", json={"name": "Ghost"}, headers=auth_headers(user)
        )
    assert response.status_code == 500
    assert db.scalar(select(func.count()).select_from(Organization)) == 0


# -------------------------------------------------------------- hostile input


@pytest.mark.parametrize("payload", INJECTIONS)
def test_sql_injection_shaped_input_is_treated_as_data(client, db, make_user, payload):
    user = make_user()
    org = create_org(client, user, f"Org {payload}"[:100])
    project = create_project(client, org["id"], user, payload[:100])
    task = create_task(client, org["id"], user, project["id"], payload[:200])
    headers = auth_headers(user)

    for path in (
        f"/organizations/{org['id']}/tasks",
        f"/organizations/{org['id']}/projects",
    ):
        response = client.get(f"{API}{path}", params={"q": payload}, headers=headers)
        assert response.status_code == 200

    stored = client.get(
        f"{API}/organizations/{org['id']}/tasks/{task['id']}", headers=headers
    ).json()
    assert stored["title"] == payload[:200].strip()
    assert "tasks" in inspect(db.get_bind()).get_table_names()  # nothing was dropped


def test_injection_in_login_does_not_authenticate(client, make_user):
    make_user("ada@example.com")
    for email in ("ada@example.com' OR '1'='1", "' OR 1=1 --@example.com"):
        response = client.post(f"{API}/auth/login", json={"email": email, "password": "x"})
        assert response.status_code in (401, 422)
    wrong_password = client.post(
        f"{API}/auth/login", json={"email": "ada@example.com", "password": "' OR '1'='1"}
    )
    assert wrong_password.status_code == 401


def test_nul_bytes_are_rejected_not_crashing_the_database(client, make_user):
    """PostgreSQL text cannot hold U+0000; unvalidated, this would surface as a 500."""
    user = make_user()
    org = create_org(client, user)
    project = create_project(client, org["id"], user)
    headers = auth_headers(user)
    oid = org["id"]
    attempts = [
        client.post(
            f"{API}/auth/register",
            json={"email": "n@example.com", "password": TEST_PASSWORD, "full_name": "a\u0000b"},
        ),
        client.post(f"{API}/organizations", json={"name": "a\u0000b"}, headers=headers),
        client.post(
            f"{API}/organizations/{oid}/projects", json={"name": "a\u0000b"}, headers=headers
        ),
        client.post(
            f"{API}/organizations/{oid}/projects",
            json={"name": "ok", "description": "a\u0000b"},
            headers=headers,
        ),
        client.post(
            f"{API}/organizations/{oid}/tasks",
            json={"project_id": project["id"], "title": "a\u0000b"},
            headers=headers,
        ),
        client.post(
            f"{API}/organizations/{oid}/tasks",
            json={"project_id": project["id"], "title": "ok", "description": "a\u0000b"},
            headers=headers,
        ),
        client.get(f"{API}/organizations/{oid}/tasks", params={"q": "a\u0000b"}, headers=headers),
        client.get(
            f"{API}/organizations/{oid}/projects", params={"q": "a\u0000b"}, headers=headers
        ),
    ]
    assert [r.status_code for r in attempts] == [422] * len(attempts)


def test_unicode_input_round_trips(client, make_user):
    user = make_user()
    org = create_org(client, user, "Équipe 日本語 🚀")
    assert org["name"] == "Équipe 日本語 🚀"


# -------------------------------------------------------- mass assignment


def test_registration_ignores_attempts_to_set_server_controlled_fields(client, db):
    forged_id = str(uuid.uuid4())
    response = client.post(
        f"{API}/auth/register",
        json={
            "email": "mallory@example.com",
            "password": TEST_PASSWORD,
            "full_name": "Mallory",
            "id": forged_id,
            "is_active": False,
            "password_hash": "x",
        },
    )
    assert response.status_code == 201
    user = db.scalar(select(User).where(User.email == "mallory@example.com"))
    assert str(user.id) != forged_id and user.is_active is True
    assert user.password_hash.startswith("$argon2id$")


def test_task_creation_cannot_be_redirected_to_another_organization(client, db, make_user):
    alice, bob = make_user(), make_user()
    org_a, org_b = create_org(client, alice, "A"), create_org(client, bob, "B")
    project_a = create_project(client, org_a["id"], alice)
    response = client.post(
        f"{API}/organizations/{org_a['id']}/tasks",
        json={
            "project_id": project_a["id"],
            "title": "T",
            "organization_id": org_b["id"],  # attempt to smuggle the task into B
            "created_by": str(bob.id),
        },
        headers=auth_headers(alice),
    )
    assert response.status_code == 201
    task = db.scalar(select(Task))
    assert str(task.organization_id) == org_a["id"] and task.created_by == alice.id


def test_membership_role_cannot_be_chosen_at_organization_creation(client, make_user):
    response = client.post(
        f"{API}/organizations",
        json={"name": "X", "role": "MEMBER"},
        headers=auth_headers(make_user()),
    )
    assert response.json()["role"] == "OWNER"


# ------------------------------------------------------------- credentials


def test_user_responses_never_contain_password_material(client, make_user):
    user = make_user()
    bodies = [
        client.get(f"{API}/users/me", headers=auth_headers(user)).text,
        client.post(
            f"{API}/auth/register",
            json={"email": "z@example.com", "password": TEST_PASSWORD, "full_name": "Z"},
        ).text,
    ]
    for body in bodies:
        assert "argon2" not in body and "password" not in body


def test_error_responses_never_echo_credentials(client):
    response = client.post(
        f"{API}/auth/login", json={"email": "not-an-email", "password": "my-secret-pw"}
    )
    assert response.status_code == 422 and "my-secret-pw" not in response.text


def test_production_settings_reject_unsafe_combinations():
    with pytest.raises(ValueError):
        Settings(
            postgres_password="p",
            jwt_secret_key="k" * 32,
            app_env="production",
            expose_invitation_tokens=True,
        )


# ------------------------------------------------------------------- indexes


EXPECTED_INDEXES = {
    "memberships": {"uq_memberships_organization_id_user_id", "ix_memberships_user_id"},
    "projects": {"ix_projects_organization_id_created_at"},
    "tasks": {
        "ix_tasks_organization_id_project_id_status",
        "ix_tasks_organization_id_assignee_id",
        "ix_tasks_organization_id_due_date",
        "ix_tasks_organization_id_created_at",
        "ix_tasks_project_id",
    },
}


def test_expected_indexes_exist(db):
    inspector = inspect(db.get_bind())
    for table, expected in EXPECTED_INDEXES.items():
        actual = {i["name"] for i in inspector.get_indexes(table)}
        assert expected <= actual, f"{table} is missing {expected - actual}"


@pytest.fixture
def populated_tasks(db):
    """40 tenants x 1,000 tasks, then ANALYZE, so the planner has real statistics to work with."""
    statements = [
        "INSERT INTO users (id, email, password_hash, full_name) "
        "SELECT gen_random_uuid(), 'u' || g || '@example.com', 'x', 'U' "
        "FROM generate_series(1, 40) g",
        "INSERT INTO organizations (id, name, slug) "
        "SELECT gen_random_uuid(), 'O' || g, 'o' || g FROM generate_series(1, 40) g",
        "INSERT INTO memberships (id, organization_id, user_id, role) "
        "SELECT gen_random_uuid(), o.id, u.id, 'OWNER' FROM organizations o "
        "JOIN users u ON substr(o.slug, 2) = substr(split_part(u.email, '@', 1), 2)",
        "INSERT INTO projects (id, organization_id, name) "
        "SELECT gen_random_uuid(), id, 'P' FROM organizations",
        "INSERT INTO tasks "
        "(id, organization_id, project_id, title, status, priority, assignee_id, due_date) "
        "SELECT gen_random_uuid(), p.organization_id, p.id, 'T' || g, "
        "(ARRAY['TODO','IN_PROGRESS','IN_REVIEW','DONE'])[1 + g % 4]::task_status, "
        "(ARRAY['LOW','MEDIUM','HIGH','URGENT'])[1 + g % 4]::task_priority, "
        "CASE WHEN g % 3 = 0 THEN m.user_id END, DATE '2030-01-01' + (g % 365) "
        "FROM projects p JOIN memberships m ON m.organization_id = p.organization_id "
        "CROSS JOIN generate_series(1, 1000) g",
    ]
    for statement in statements:
        db.execute(text(statement))
    db.commit()
    db.execute(text("ANALYZE tasks"))
    db.commit()
    org_id, project_id, user_id = db.execute(
        text(
            "SELECT p.organization_id, p.id, m.user_id FROM projects p "
            "JOIN memberships m ON m.organization_id = p.organization_id LIMIT 1"
        )
    ).one()
    return {"o": org_id, "p": project_id, "u": user_id}


@pytest.mark.parametrize(
    "query",
    [
        "WHERE organization_id = :o ORDER BY created_at DESC LIMIT 20",
        "WHERE organization_id = :o AND project_id = :p AND status = 'TODO'",
        "WHERE organization_id = :o AND assignee_id = :u",
        "WHERE organization_id = :o AND due_date BETWEEN '2030-01-01' AND '2030-01-07'",
    ],
)
def test_tenant_scoped_task_queries_avoid_sequential_scans(db, populated_tasks, query):
    plan = "\n".join(
        db.execute(text(f"EXPLAIN SELECT * FROM tasks {query}"), populated_tasks).scalars().all()
    )
    assert "Seq Scan on tasks" not in plan, plan
