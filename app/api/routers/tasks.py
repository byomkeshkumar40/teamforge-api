import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import DbSession, Pagination, Tenant
from app.models import TaskPriority, TaskStatus
from app.schemas.common import Page
from app.schemas.task import TaskAssign, TaskCreate, TaskRead, TaskUpdate
from app.services import tasks as service
from app.services.query import SortOrder
from app.services.tasks import TaskFilters, TaskSortField

router = APIRouter(prefix="/organizations/{org_id}/tasks", tags=["tasks"])


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(data: TaskCreate, ctx: Tenant, db: DbSession):
    return service.create_task(db, ctx, data)


@router.get("", response_model=Page[TaskRead])
def list_tasks(
    ctx: Tenant,
    db: DbSession,
    page: Pagination,
    status_: Annotated[list[TaskStatus] | None, Query(alias="status")] = None,
    priority: Annotated[list[TaskPriority] | None, Query()] = None,
    project_id: uuid.UUID | None = None,
    assignee_id: uuid.UUID | None = None,
    unassigned: bool = False,
    due_after: date | None = None,
    due_before: date | None = None,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    sort_by: TaskSortField = TaskSortField.created_at,
    order: SortOrder = SortOrder.desc,
):
    """Filter with `status`/`priority` (repeatable), `project_id`, `assignee_id`, `unassigned`,
    `due_after`/`due_before` (inclusive) and `q` (title contains)."""
    filters = TaskFilters(
        statuses=status_ or [],
        priorities=priority or [],
        project_id=project_id,
        assignee_id=assignee_id,
        unassigned=unassigned,
        due_after=due_after,
        due_before=due_before,
        q=q,
    )
    items, total = service.list_tasks(db, ctx, page, filters, sort_by=sort_by, order=order)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.get("/{task_id}", response_model=TaskRead)
def get_task(task_id: uuid.UUID, ctx: Tenant, db: DbSession):
    return service.get_task(db, ctx, task_id)


@router.patch("/{task_id}", response_model=TaskRead)
def update_task(task_id: uuid.UUID, data: TaskUpdate, ctx: Tenant, db: DbSession):
    return service.update_task(db, ctx, task_id, data)


@router.put("/{task_id}/assignee", response_model=TaskRead)
def assign_task(task_id: uuid.UUID, data: TaskAssign, ctx: Tenant, db: DbSession):
    return service.assign_task(db, ctx, task_id, data.assignee_id)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: uuid.UUID, ctx: Tenant, db: DbSession):
    service.delete_task(db, ctx, task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
