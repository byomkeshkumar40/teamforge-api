import logging
import uuid
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, UnprocessableError
from app.core.permissions import Permission, TenantContext, authorize
from app.models import Membership, Project, Task, TaskPriority, TaskStatus
from app.schemas.common import PageParams
from app.schemas.task import TaskCreate, TaskUpdate
from app.services.query import SortOrder, escape_like

logger = logging.getLogger(__name__)

BAD_ASSIGNEE = "Assignee must be a member of the organization"


class TaskSortField(StrEnum):
    """Allowlist of sortable columns: the enum doubles as the validator for `sort_by`."""

    created_at = "created_at"
    updated_at = "updated_at"
    due_date = "due_date"
    priority = "priority"  # PostgreSQL orders enums by declaration: LOW < ... < URGENT
    status = "status"  # TODO < IN_PROGRESS < IN_REVIEW < DONE
    title = "title"


_SORT_COLUMNS = {
    TaskSortField.created_at: Task.created_at,
    TaskSortField.updated_at: Task.updated_at,
    TaskSortField.due_date: Task.due_date,
    TaskSortField.priority: Task.priority,
    TaskSortField.status: Task.status,
    TaskSortField.title: Task.title,
}


@dataclass(frozen=True)
class TaskFilters:
    statuses: list[TaskStatus] = field(default_factory=list)
    priorities: list[TaskPriority] = field(default_factory=list)
    project_id: uuid.UUID | None = None
    assignee_id: uuid.UUID | None = None
    unassigned: bool = False
    due_after: date | None = None  # inclusive
    due_before: date | None = None  # inclusive
    q: str | None = None


# ------------------------------------------------------------------- lookups


def _get_task(db: Session, ctx: TenantContext, task_id: uuid.UUID) -> Task:
    """Tenant-scoped lookup: a task id from another organization simply does not exist."""
    task = db.scalar(
        select(Task).where(Task.id == task_id, Task.organization_id == ctx.organization_id)
    )
    if task is None:
        raise NotFoundError("Task not found")
    return task


def _get_project_for_write(db: Session, ctx: TenantContext, project_id: uuid.UUID) -> Project:
    project = db.scalar(
        select(Project).where(
            Project.id == project_id, Project.organization_id == ctx.organization_id
        )
    )
    if project is None:
        raise NotFoundError("Project not found")
    if project.archived_at is not None:
        raise ConflictError("The project is archived; unarchive it to change its tasks")
    return project


def _require_member_assignee(db: Session, ctx: TenantContext, assignee_id: uuid.UUID) -> None:
    """Application-level check (friendly 422); the composite FK is the safety net behind it."""
    is_member = db.scalar(
        select(Membership.id).where(
            Membership.organization_id == ctx.organization_id, Membership.user_id == assignee_id
        )
    )
    if not is_member:
        # Same message whether the user is unknown or belongs to another tenant.
        raise UnprocessableError(BAD_ASSIGNEE)


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        # e.g. the assignee was removed between our check and the commit
        db.rollback()
        raise UnprocessableError(BAD_ASSIGNEE) from None


# ------------------------------------------------------------------- queries


def get_task(db: Session, ctx: TenantContext, task_id: uuid.UUID) -> Task:
    return _get_task(db, ctx, task_id)


def list_tasks(
    db: Session,
    ctx: TenantContext,
    page: PageParams,
    filters: TaskFilters,
    *,
    sort_by: TaskSortField,
    order: SortOrder,
) -> tuple[list[Task], int]:
    if filters.assignee_id and filters.unassigned:
        raise UnprocessableError("assignee_id and unassigned cannot be combined")
    if filters.due_after and filters.due_before and filters.due_after > filters.due_before:
        raise UnprocessableError("due_after must not be later than due_before")

    where = [Task.organization_id == ctx.organization_id]  # the tenant filter, always first
    if filters.statuses:
        where.append(Task.status.in_(filters.statuses))
    if filters.priorities:
        where.append(Task.priority.in_(filters.priorities))
    if filters.project_id:
        where.append(Task.project_id == filters.project_id)
    if filters.assignee_id:
        where.append(Task.assignee_id == filters.assignee_id)
    if filters.unassigned:
        where.append(Task.assignee_id.is_(None))
    if filters.due_after:
        where.append(Task.due_date >= filters.due_after)
    if filters.due_before:
        where.append(Task.due_date <= filters.due_before)
    if filters.q:
        where.append(Task.title.ilike(f"%{escape_like(filters.q)}%", escape="\\"))

    column = _SORT_COLUMNS[sort_by]
    ordering = (column.asc() if order == SortOrder.asc else column.desc()).nulls_last()
    total = db.scalar(select(func.count()).select_from(Task).where(*where)) or 0
    rows = db.scalars(
        select(Task)
        .where(*where)
        .order_by(ordering, Task.id)  # id breaks ties so pages are stable
        .limit(page.limit)
        .offset(page.offset)
    ).all()
    return list(rows), total


# -------------------------------------------------------------------- writes


def create_task(db: Session, ctx: TenantContext, data: TaskCreate) -> Task:
    authorize(ctx, Permission.TASKS_WRITE)
    _get_project_for_write(db, ctx, data.project_id)
    if data.assignee_id:
        _require_member_assignee(db, ctx, data.assignee_id)
    task = Task(
        organization_id=ctx.organization_id,
        created_by=ctx.user.id,
        **data.model_dump(),
    )
    db.add(task)
    _commit(db)
    logger.info(
        "task_created", extra={"organization_id": str(ctx.organization_id), "task_id": str(task.id)}
    )
    return task


def update_task(db: Session, ctx: TenantContext, task_id: uuid.UUID, data: TaskUpdate) -> Task:
    authorize(ctx, Permission.TASKS_WRITE)
    task = _get_task(db, ctx, task_id)
    _get_project_for_write(db, ctx, task.project_id)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("assignee_id"):
        _require_member_assignee(db, ctx, changes["assignee_id"])
    for name, value in changes.items():
        setattr(task, name, value)
    _commit(db)
    return task


def assign_task(
    db: Session, ctx: TenantContext, task_id: uuid.UUID, assignee_id: uuid.UUID | None
) -> Task:
    authorize(ctx, Permission.TASKS_WRITE)
    task = _get_task(db, ctx, task_id)
    _get_project_for_write(db, ctx, task.project_id)
    if assignee_id:
        _require_member_assignee(db, ctx, assignee_id)
    task.assignee_id = assignee_id
    _commit(db)
    logger.info(
        "task_assigned",
        extra={"organization_id": str(ctx.organization_id), "task_id": str(task.id)},
    )
    return task


def delete_task(db: Session, ctx: TenantContext, task_id: uuid.UUID) -> None:
    """Owners/admins can delete any task; members only tasks they created."""
    authorize(ctx, Permission.TASKS_WRITE)
    task = _get_task(db, ctx, task_id)
    if not ctx.can(Permission.TASKS_DELETE_ANY) and task.created_by != ctx.user.id:
        raise PermissionDeniedError("Members can only delete tasks they created")
    _get_project_for_write(db, ctx, task.project_id)
    db.delete(task)
    db.commit()
    logger.info(
        "task_deleted", extra={"organization_id": str(ctx.organization_id), "task_id": str(task_id)}
    )
