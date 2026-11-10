from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.constants import (
    COLOR_MAX_LENGTH,
    COMMENT_MAX_LENGTH,
    DESCRIPTION_MAX_LENGTH,
    EMAIL_MAX_LENGTH,
    NAME_MAX_LENGTH,
    PASSWORD_HASH_MAX_LENGTH,
    TITLE_MAX_LENGTH,
)

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=EMAIL_MAX_LENGTH), nullable=False),
        sa.Column("full_name", sa.String(length=NAME_MAX_LENGTH), nullable=False),
        sa.Column(
            "hashed_password",
            sa.String(length=PASSWORD_HASH_MAX_LENGTH),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.Enum(
                "ADMIN",
                "MEMBER",
                name="user_role",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="MEMBER",
            nullable=False,
        ),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "workspaces",
        sa.Column("name", sa.String(length=NAME_MAX_LENGTH), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_workspaces_owner_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspaces")),
    )
    op.create_index(
        op.f("ix_workspaces_owner_id"), "workspaces", ["owner_id"], unique=False
    )
    op.create_table(
        "projects",
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=NAME_MAX_LENGTH), nullable=False),
        sa.Column(
            "description", sa.String(length=DESCRIPTION_MAX_LENGTH), nullable=True
        ),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE",
                "ARCHIVED",
                name="project_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_projects_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
        sa.UniqueConstraint(
            "workspace_id", "name", name=op.f("uq_projects_workspace_id")
        ),
    )
    op.create_index(
        op.f("ix_projects_workspace_id"), "projects", ["workspace_id"], unique=False
    )
    op.create_table(
        "workspace_members",
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "OWNER",
                "EDITOR",
                "VIEWER",
                name="workspace_role",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="VIEWER",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_workspace_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_workspace_members_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "user_id", name=op.f("pk_workspace_members")
        ),
    )
    op.create_index(
        op.f("ix_workspace_members_user_id"),
        "workspace_members",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "labels",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=NAME_MAX_LENGTH), nullable=False),
        sa.Column("color", sa.String(length=COLOR_MAX_LENGTH), nullable=False),
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_labels_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_labels")),
        sa.UniqueConstraint("project_id", "name", name=op.f("uq_labels_project_id")),
    )
    op.create_index(
        op.f("ix_labels_project_id"), "labels", ["project_id"], unique=False
    )
    op.create_table(
        "tasks",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("assignee_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=TITLE_MAX_LENGTH), nullable=False),
        sa.Column(
            "description", sa.String(length=DESCRIPTION_MAX_LENGTH), nullable=True
        ),
        sa.Column(
            "status",
            sa.Enum(
                "TODO",
                "IN_PROGRESS",
                "IN_REVIEW",
                "DONE",
                name="task_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="TODO",
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.Enum(
                "LOW",
                "MEDIUM",
                "HIGH",
                "URGENT",
                name="task_priority",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="MEDIUM",
            nullable=False,
        ),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(title)) > 0", name=op.f("ck_tasks_title_not_blank")
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id"],
            ["users.id"],
            name=op.f("fk_tasks_assignee_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_tasks_created_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_tasks_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    op.create_index(
        op.f("ix_tasks_assignee_id"), "tasks", ["assignee_id"], unique=False
    )
    op.create_index(op.f("ix_tasks_created_by"), "tasks", ["created_by"], unique=False)
    op.create_index(op.f("ix_tasks_project_id"), "tasks", ["project_id"], unique=False)
    op.create_table(
        "comments",
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.String(length=COMMENT_MAX_LENGTH), nullable=False),
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name=op.f("fk_comments_author_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_comments_task_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comments")),
    )
    op.create_index(
        op.f("ix_comments_author_id"), "comments", ["author_id"], unique=False
    )
    op.create_index(op.f("ix_comments_task_id"), "comments", ["task_id"], unique=False)
    op.create_table(
        "task_labels",
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("label_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["label_id"],
            ["labels.id"],
            name=op.f("fk_task_labels_label_id_labels"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_task_labels_task_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("task_id", "label_id", name=op.f("pk_task_labels")),
    )
    op.create_index(
        op.f("ix_task_labels_label_id"), "task_labels", ["label_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_task_labels_label_id"), table_name="task_labels")
    op.drop_table("task_labels")
    op.drop_index(op.f("ix_comments_task_id"), table_name="comments")
    op.drop_index(op.f("ix_comments_author_id"), table_name="comments")
    op.drop_table("comments")
    op.drop_index(op.f("ix_tasks_project_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_created_by"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_assignee_id"), table_name="tasks")
    op.drop_table("tasks")
    op.drop_index(op.f("ix_labels_project_id"), table_name="labels")
    op.drop_table("labels")
    op.drop_index(op.f("ix_workspace_members_user_id"), table_name="workspace_members")
    op.drop_table("workspace_members")
    op.drop_index(op.f("ix_projects_workspace_id"), table_name="projects")
    op.drop_table("projects")
    op.drop_index(op.f("ix_workspaces_owner_id"), table_name="workspaces")
    op.drop_table("workspaces")
    op.drop_table("users")
