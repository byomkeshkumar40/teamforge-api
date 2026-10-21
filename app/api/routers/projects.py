import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import DbSession, Pagination, Tenant
from app.schemas.common import NO_NUL, Page
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from app.services import projects as service
from app.services.projects import ProjectSortField
from app.services.query import SortOrder

router = APIRouter(prefix="/organizations/{org_id}/projects", tags=["projects"])


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(data: ProjectCreate, ctx: Tenant, db: DbSession):
    return service.create_project(db, ctx, data)


@router.get("", response_model=Page[ProjectRead])
def list_projects(
    ctx: Tenant,
    db: DbSession,
    page: Pagination,
    include_archived: bool = False,
    q: Annotated[str | None, Query(min_length=1, max_length=100, pattern=NO_NUL)] = None,
    sort_by: ProjectSortField = ProjectSortField.created_at,
    order: SortOrder = SortOrder.desc,
):
    items, total = service.list_projects(
        db, ctx, page, include_archived=include_archived, q=q, sort_by=sort_by, order=order
    )
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: uuid.UUID, ctx: Tenant, db: DbSession):
    return service.get_project(db, ctx, project_id)


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(project_id: uuid.UUID, data: ProjectUpdate, ctx: Tenant, db: DbSession):
    return service.update_project(db, ctx, project_id, data)


@router.post("/{project_id}/archive", response_model=ProjectRead)
def archive_project(project_id: uuid.UUID, ctx: Tenant, db: DbSession):
    return service.set_archived(db, ctx, project_id, archived=True)


@router.post("/{project_id}/unarchive", response_model=ProjectRead)
def unarchive_project(project_id: uuid.UUID, ctx: Tenant, db: DbSession):
    return service.set_archived(db, ctx, project_id, archived=False)
