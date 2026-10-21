"""Database-level guarantees. These hold even if application code has a bug."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import DataError, IntegrityError

from alembic import command
from app.models import (
    Invitation,
    Membership,
    Organization,
    Project,
    Role,
    Task,
    User,
)
from tests.conftest import ROOT


def make_user(db, email: str | None = None) -> User:
    user = User(
        email=email or f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash="not-a-real-hash",
        full_name="Test User",
    )
    db.add(user)
    db.flush()
    return user


def make_org(db, name: str = "Acme") -> Organization:
    org = Organization(name=name, slug=f"{name.lower()}-{uuid.uuid4().hex[:6]}")
    db.add(org)
    db.flush()
    return org


def make_member(db, org: Organization, user: User, role: Role = Role.MEMBER) -> Membership:
    membership = Membership(organization_id=org.id, user_id=user.id, role=role)
    db.add(membership)
    db.flush()
    return membership


def make_project(db, org: Organization, name: str = "Website") -> Project:
    project = Project(organization_id=org.id, name=name)
    db.add(project)
    db.flush()
    return project


def test_migrations_match_models_and_are_reversible():
    cfg = Config(str(ROOT / "alembic.ini"))
    command.check(cfg)  # raises if the models and the migrations have drifted apart
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


def test_email_must_be_lowercase(db):
    db.add(User(email="Mixed@Example.com", password_hash="x", full_name="A"))
    with pytest.raises(IntegrityError, match="email_lowercase"):
        db.flush()


def test_email_is_unique(db):
    make_user(db, "dup@example.com")
    db.add(User(email="dup@example.com", password_hash="x", full_name="B"))
    with pytest.raises(IntegrityError, match="uq_users_email"):
        db.flush()


def test_membership_is_unique_per_user_and_org(db):
    org, user = make_org(db), make_user(db)
    make_member(db, org, user)
    db.add(Membership(organization_id=org.id, user_id=user.id, role=Role.ADMIN))
    with pytest.raises(IntegrityError, match="uq_memberships_organization_id_user_id"):
        db.flush()


def test_task_cannot_reference_project_of_another_org(db):
    org_a, org_b = make_org(db, "A"), make_org(db, "B")
    project_b = make_project(db, org_b)
    db.add(Task(organization_id=org_a.id, project_id=project_b.id, title="Sneaky"))
    with pytest.raises(IntegrityError, match="fk_tasks_project_id_projects"):
        db.flush()


def test_task_assignee_must_be_member_of_same_org(db):
    org_a, org_b = make_org(db, "A"), make_org(db, "B")
    outsider = make_user(db)
    make_member(db, org_b, outsider)  # member of B only
    project = make_project(db, org_a)
    db.add(
        Task(organization_id=org_a.id, project_id=project.id, title="T", assignee_id=outsider.id)
    )
    with pytest.raises(IntegrityError, match="fk_tasks_assignee_id_memberships"):
        db.flush()


def test_task_with_member_assignee_and_with_no_assignee_is_allowed(db):
    org, user = make_org(db), make_user(db)
    make_member(db, org, user)
    project = make_project(db, org)
    db.add_all(
        [
            Task(
                organization_id=org.id, project_id=project.id, title="Assigned", assignee_id=user.id
            ),
            Task(organization_id=org.id, project_id=project.id, title="Unassigned"),
        ]
    )
    db.flush()
    assert db.scalar(select(Task.status).where(Task.title == "Unassigned")).value == "TODO"


def test_membership_cannot_be_deleted_while_tasks_are_assigned(db):
    org, user = make_org(db), make_user(db)
    membership = make_member(db, org, user)
    project = make_project(db, org)
    db.add(Task(organization_id=org.id, project_id=project.id, title="T", assignee_id=user.id))
    db.flush()
    db.delete(membership)
    with pytest.raises(IntegrityError, match="fk_tasks_assignee_id_memberships"):
        db.flush()


def test_invitation_cannot_grant_owner_role(db):
    org = make_org(db)
    db.add(
        Invitation(
            organization_id=org.id,
            email="x@example.com",
            role=Role.OWNER,
            token_hash="a" * 64,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    with pytest.raises(IntegrityError, match="role_not_owner"):
        db.flush()


def test_only_one_pending_invitation_per_org_and_email(db):
    org = make_org(db)
    expires = datetime.now(UTC) + timedelta(days=1)
    db.add(
        Invitation(
            organization_id=org.id,
            email="x@example.com",
            role=Role.MEMBER,
            token_hash="a" * 64,
            expires_at=expires,
            accepted_at=datetime.now(UTC),  # accepted invitations don't count as pending
        )
    )
    db.add(
        Invitation(
            organization_id=org.id,
            email="x@example.com",
            role=Role.MEMBER,
            token_hash="b" * 64,
            expires_at=expires,
        )
    )
    db.flush()
    db.add(
        Invitation(
            organization_id=org.id,
            email="x@example.com",
            role=Role.ADMIN,
            token_hash="c" * 64,
            expires_at=expires,
        )
    )
    with pytest.raises(IntegrityError, match="uq_invitations_pending"):
        db.flush()


def test_blank_names_and_titles_are_rejected(db):
    org = make_org(db)
    db.add(Project(organization_id=org.id, name="   "))
    with pytest.raises(IntegrityError, match="name_not_blank"):
        db.flush()


def test_invalid_enum_value_is_rejected(db):
    org = make_org(db)
    project = make_project(db, org)
    with pytest.raises(DataError):
        db.execute(
            text(
                "INSERT INTO tasks (id, organization_id, project_id, title, status) "
                "VALUES (gen_random_uuid(), :o, :p, 't', 'BOGUS')"
            ),
            {"o": org.id, "p": project.id},
        )


def test_deleting_an_organization_cascades_to_everything_it_owns(db):
    org, user = make_org(db), make_user(db)
    make_member(db, org, user, Role.OWNER)
    project = make_project(db, org)
    db.add(Task(organization_id=org.id, project_id=project.id, title="T", assignee_id=user.id))
    db.flush()
    db.delete(org)
    db.flush()
    for model in (Membership, Project, Task):
        assert db.scalar(select(model.id).limit(1)) is None
    assert db.get(User, user.id) is not None  # users are global, not tenant-owned
