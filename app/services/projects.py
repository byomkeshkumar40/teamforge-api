import logging
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.core.permissions import Permission, TenantContext, authorize
from app.models import Project
from app.schemas.common import PageParams
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.services.query import SortOrder, escape_like

logger = logging.getLogger(__name__)


class ProjectSortField(StrEnum):
    """Allowlist of sortable columns: the enum doubles as the validator for `sort_by`."""

    created_at = "created_at"
    updated_at = "updated_at"
    name = "name"


_SORT_COLUMNS = {
    ProjectSortField.created_at: Project.created_at,
    ProjectSortField.updated_at: Project.updated_at,
    ProjectSortField.name: Project.name,
}


def get_project(db: Session, ctx: TenantContext, project_id: uuid.UUID) -> Project:
    """Tenant-scoped lookup: a project id from another organization simply does not exist."""
    project = db.scalar(
        select(Project).where(
            Project.id == project_id, Project.organization_id == ctx.organization_id
        )
    )
    if project is None:
        raise NotFoundError("Project not found")
    return project


def list_projects(
    db: Session,
    ctx: TenantContext,
    page: PageParams,
    *,
    include_archived: bool,
    q: str | None,
    sort_by: ProjectSortField,
    order: SortOrder,
) -> tuple[list[Project], int]:
    where = [Project.organization_id == ctx.organization_id]
    if not include_archived:
        where.append(Project.archived_at.is_(None))
    if q:
        where.append(Project.name.ilike(f"%{escape_like(q)}%", escape="\\"))

    column = _SORT_COLUMNS[sort_by]
    ordering = column.asc() if order == SortOrder.asc else column.desc()
    total = db.scalar(select(func.count()).select_from(Project).where(*where)) or 0
    rows = db.scalars(
        select(Project)
        .where(*where)
        .order_by(ordering, Project.id)  # id breaks ties so pages are stable
        .limit(page.limit)
        .offset(page.offset)
    ).all()
    return list(rows), total


def create_project(db: Session, ctx: TenantContext, data: ProjectCreate) -> Project:
    authorize(ctx, Permission.PROJECTS_WRITE)
    project = Project(
        organization_id=ctx.organization_id,
        name=data.name,
        description=data.description,
        created_by=ctx.user.id,
    )
    db.add(project)
    db.commit()
    logger.info(
        "project_created",
        extra={"organization_id": str(ctx.organization_id), "project_id": str(project.id)},
    )
    return project


def update_project(
    db: Session, ctx: TenantContext, project_id: uuid.UUID, data: ProjectUpdate
) -> Project:
    authorize(ctx, Permission.PROJECTS_WRITE)
    project = get_project(db, ctx, project_id)
    if project.archived_at is not None:
        raise ConflictError("Archived projects are read-only; unarchive the project first")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    db.commit()
    return project


def set_archived(
    db: Session, ctx: TenantContext, project_id: uuid.UUID, *, archived: bool
) -> Project:
    """Idempotent: archiving an archived project (or the reverse) is a no-op."""
    authorize(ctx, Permission.PROJECTS_WRITE)
    project = get_project(db, ctx, project_id)
    if archived and project.archived_at is None:
        project.archived_at = datetime.now(UTC)
    elif not archived and project.archived_at is not None:
        project.archived_at = None
    db.commit()
    logger.info(
        "project_archived" if archived else "project_unarchived",
        extra={"organization_id": str(ctx.organization_id), "project_id": str(project_id)},
    )
    return project
