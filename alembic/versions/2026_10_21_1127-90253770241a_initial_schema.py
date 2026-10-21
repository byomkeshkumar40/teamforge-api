"""initial schema

Revision ID: 90253770241a
Revises: 
Create Date: 2026-10-21 11:27:27.273700

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '90253770241a'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Hand-edited: the "role" enum is shared by two tables, so it is created once, explicitly.
    postgresql.ENUM('OWNER', 'ADMIN', 'MEMBER', name='role').create(op.get_bind())
    op.create_table('users',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('full_name', sa.String(length=120), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('email = lower(email)', name=op.f('ck_users_email_lowercase')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email'))
    )
    op.create_table('organizations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('slug', sa.String(length=120), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('length(trim(name)) > 0', name=op.f('ck_organizations_name_not_blank')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_organizations_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_organizations')),
    sa.UniqueConstraint('slug', name=op.f('uq_organizations_slug'))
    )
    op.create_table('invitations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('role', postgresql.ENUM('OWNER', 'ADMIN', 'MEMBER', name='role', create_type=False), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('invited_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role <> 'OWNER'", name=op.f('ck_invitations_role_not_owner')),
    sa.ForeignKeyConstraint(['invited_by'], ['users.id'], name=op.f('fk_invitations_invited_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_invitations_organization_id_organizations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_invitations')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_invitations_token_hash'))
    )
    op.create_index('uq_invitations_pending_organization_id_email', 'invitations', ['organization_id', 'email'], unique=True, postgresql_where=sa.text('accepted_at IS NULL'))
    op.create_table('memberships',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('role', postgresql.ENUM('OWNER', 'ADMIN', 'MEMBER', name='role', create_type=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_memberships_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_memberships_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_memberships'))
    )
    op.create_index('ix_memberships_user_id', 'memberships', ['user_id'], unique=False)
    op.create_index('uq_memberships_organization_id_user_id', 'memberships', ['organization_id', 'user_id'], unique=True)
    op.create_table('projects',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('length(trim(name)) > 0', name=op.f('ck_projects_name_not_blank')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_projects_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_projects_organization_id_organizations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_projects')),
    sa.UniqueConstraint('id', 'organization_id', name='uq_projects_id_organization_id')
    )
    op.create_index('ix_projects_organization_id_created_at', 'projects', ['organization_id', 'created_at'], unique=False)
    op.create_table('tasks',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.Enum('TODO', 'IN_PROGRESS', 'IN_REVIEW', 'DONE', name='task_status'), server_default='TODO', nullable=False),
    sa.Column('priority', sa.Enum('LOW', 'MEDIUM', 'HIGH', 'URGENT', name='task_priority'), server_default='MEDIUM', nullable=False),
    sa.Column('assignee_id', sa.Uuid(), nullable=True),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('length(trim(title)) > 0', name=op.f('ck_tasks_title_not_blank')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_tasks_created_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id', 'assignee_id'], ['memberships.organization_id', 'memberships.user_id'], name='fk_tasks_assignee_id_memberships'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_tasks_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['project_id', 'organization_id'], ['projects.id', 'projects.organization_id'], name='fk_tasks_project_id_projects', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tasks'))
    )
    op.create_index('ix_tasks_organization_id_assignee_id', 'tasks', ['organization_id', 'assignee_id'], unique=False)
    op.create_index('ix_tasks_organization_id_created_at', 'tasks', ['organization_id', 'created_at'], unique=False)
    op.create_index('ix_tasks_organization_id_due_date', 'tasks', ['organization_id', 'due_date'], unique=False)
    op.create_index('ix_tasks_organization_id_project_id_status', 'tasks', ['organization_id', 'project_id', 'status'], unique=False)
    op.create_index('ix_tasks_project_id', 'tasks', ['project_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_tasks_project_id', table_name='tasks')
    op.drop_index('ix_tasks_organization_id_project_id_status', table_name='tasks')
    op.drop_index('ix_tasks_organization_id_due_date', table_name='tasks')
    op.drop_index('ix_tasks_organization_id_created_at', table_name='tasks')
    op.drop_index('ix_tasks_organization_id_assignee_id', table_name='tasks')
    op.drop_table('tasks')
    op.drop_index('ix_projects_organization_id_created_at', table_name='projects')
    op.drop_table('projects')
    op.drop_index('uq_memberships_organization_id_user_id', table_name='memberships')
    op.drop_index('ix_memberships_user_id', table_name='memberships')
    op.drop_table('memberships')
    op.drop_index('uq_invitations_pending_organization_id_email', table_name='invitations', postgresql_where=sa.text('accepted_at IS NULL'))
    op.drop_table('invitations')
    op.drop_table('organizations')
    op.drop_table('users')
    for enum_name in ('task_priority', 'task_status', 'role'):
        postgresql.ENUM(name=enum_name).drop(op.get_bind())
