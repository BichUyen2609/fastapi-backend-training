from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import (
    COLOR_MAX_LENGTH,
    COMMENT_MAX_LENGTH,
    DESCRIPTION_MAX_LENGTH,
    EMAIL_MAX_LENGTH,
    NAME_MAX_LENGTH,
    PASSWORD_HASH_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    TOKEN_HASH_LENGTH,
)
from app.core.enums import (
    ProjectStatus,
    TaskPriority,
    TaskStatus,
    UserRole,
    WorkspaceRole,
)
from app.database import Base, Entity


class User(Entity):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH), unique=True)
    full_name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH))
    hashed_password: Mapped[str] = mapped_column(String(PASSWORD_HASH_MAX_LENGTH))
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", native_enum=False, create_constraint=True),
        server_default=UserRole.MEMBER.value,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    owned_workspaces: Mapped[list[Workspace]] = relationship(
        back_populates="owner", passive_deletes="all", lazy="raise"
    )
    memberships: Mapped[list[WorkspaceMember]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    assigned_tasks: Mapped[list[Task]] = relationship(
        back_populates="assignee",
        foreign_keys="Task.assignee_id",
        passive_deletes="all",
        lazy="raise",
    )
    created_tasks: Mapped[list[Task]] = relationship(
        back_populates="creator",
        foreign_keys="Task.created_by",
        passive_deletes="all",
        lazy="raise",
    )
    comments: Mapped[list[Comment]] = relationship(
        back_populates="author", passive_deletes="all", lazy="raise"
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )


class RefreshToken(Entity):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(TOKEN_HASH_LENGTH), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship(back_populates="refresh_tokens", lazy="raise")


class Workspace(Entity):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH))
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    owner: Mapped[User] = relationship(back_populates="owned_workspaces", lazy="raise")
    members: Mapped[list[WorkspaceMember]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    projects: Mapped[list[Project]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[WorkspaceRole] = mapped_column(
        Enum(
            WorkspaceRole,
            name="workspace_role",
            native_enum=False,
            create_constraint=True,
        ),
        server_default=WorkspaceRole.VIEWER.value,
    )
    workspace: Mapped[Workspace] = relationship(back_populates="members", lazy="raise")
    user: Mapped[User] = relationship(back_populates="memberships", lazy="raise")


class Project(Entity):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH))
    description: Mapped[str | None] = mapped_column(String(DESCRIPTION_MAX_LENGTH))
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(
            ProjectStatus,
            name="project_status",
            native_enum=False,
            create_constraint=True,
        ),
        server_default=ProjectStatus.ACTIVE.value,
    )
    workspace: Mapped[Workspace] = relationship(back_populates="projects", lazy="raise")
    tasks: Mapped[list[Task]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    labels: Mapped[list[Label]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )


class Task(Entity):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("length(trim(title)) > 0", name="title_not_blank"),
    )

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(TITLE_MAX_LENGTH))
    description: Mapped[str | None] = mapped_column(String(DESCRIPTION_MAX_LENGTH))
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status", native_enum=False, create_constraint=True),
        server_default=TaskStatus.TODO.value,
    )
    priority: Mapped[TaskPriority] = mapped_column(
        Enum(
            TaskPriority,
            name="task_priority",
            native_enum=False,
            create_constraint=True,
        ),
        server_default=TaskPriority.MEDIUM.value,
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    project: Mapped[Project] = relationship(back_populates="tasks", lazy="raise")
    assignee: Mapped[User | None] = relationship(
        back_populates="assigned_tasks", foreign_keys=[assignee_id], lazy="raise"
    )
    creator: Mapped[User] = relationship(
        back_populates="created_tasks", foreign_keys=[created_by], lazy="raise"
    )
    label_links: Mapped[list[TaskLabel]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    comments: Mapped[list[Comment]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )


class Label(Entity):
    __tablename__ = "labels"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH))
    color: Mapped[str] = mapped_column(String(COLOR_MAX_LENGTH))
    project: Mapped[Project] = relationship(back_populates="labels", lazy="raise")
    task_links: Mapped[list[TaskLabel]] = relationship(
        back_populates="label",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )


class TaskLabel(Base):
    __tablename__ = "task_labels"

    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    label_id: Mapped[int] = mapped_column(
        ForeignKey("labels.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    task: Mapped[Task] = relationship(back_populates="label_links", lazy="raise")
    label: Mapped[Label] = relationship(back_populates="task_links", lazy="raise")


class Comment(Entity):
    __tablename__ = "comments"

    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    content: Mapped[str] = mapped_column(String(COMMENT_MAX_LENGTH))
    task: Mapped[Task] = relationship(back_populates="comments", lazy="raise")
    author: Mapped[User] = relationship(back_populates="comments", lazy="raise")
