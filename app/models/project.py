import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import TaskPriority, TaskStatus


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
        # Lets child tables reference (id, organization_id) so a task can never
        # point at a project that belongs to a different organization.
        UniqueConstraint("id", "organization_id", name="uq_projects_id_organization_id"),
        Index("ix_projects_organization_id_created_at", "organization_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("length(trim(title)) > 0", name="title_not_blank"),
        # Tenant consistency enforced by the database itself:
        # 1) the project must belong to the SAME organization as the task
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_tasks_project_id_projects",
            ondelete="CASCADE",
        ),
        # 2) the assignee must be a MEMBER of that organization (not just any user).
        #    MATCH SIMPLE (default): the check is skipped when assignee_id is NULL.
        ForeignKeyConstraint(
            ["organization_id", "assignee_id"],
            ["memberships.organization_id", "memberships.user_id"],
            name="fk_tasks_assignee_id_memberships",
        ),
        Index(
            "ix_tasks_organization_id_project_id_status", "organization_id", "project_id", "status"
        ),
        Index("ix_tasks_organization_id_assignee_id", "organization_id", "assignee_id"),
        Index("ix_tasks_organization_id_due_date", "organization_id", "due_date"),
        Index("ix_tasks_organization_id_created_at", "organization_id", "created_at"),
        Index("ix_tasks_project_id", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    project_id: Mapped[uuid.UUID]
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status"), server_default=TaskStatus.TODO.value
    )
    priority: Mapped[TaskPriority] = mapped_column(
        Enum(TaskPriority, name="task_priority"), server_default=TaskPriority.MEDIUM.value
    )
    assignee_id: Mapped[uuid.UUID | None]
    due_date: Mapped[date | None] = mapped_column(Date)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
