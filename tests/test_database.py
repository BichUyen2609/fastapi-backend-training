from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, String, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.constants import DESCRIPTION_MAX_LENGTH, TITLE_MAX_LENGTH
from app.core.enums import TaskPriority, TaskStatus
from app.core.security import hash_password, verify_password
from app.database import Base
from app.models.entities import (
    Comment,
    Label,
    Project,
    Task,
    TaskLabel,
    User,
    Workspace,
)
from app.schemas.task import TaskCreate

pytestmark = pytest.mark.anyio


def migration_config(connection: Connection) -> Config:
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


async def test_migration_round_trip_and_model_metadata_match(
    database_engine: AsyncEngine,
) -> None:
    schema = f"migration_{uuid4().hex}"
    async with database_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))

            def run_cycle(sync_connection: Connection) -> None:
                config = migration_config(sync_connection)
                command.upgrade(config, "head")
                inspector = inspect(sync_connection)
                assert set(inspector.get_table_names()) - {"alembic_version"} == set(
                    Base.metadata.tables
                )
                command.check(config)
                command.downgrade(config, "base")
                assert set(inspect(sync_connection).get_table_names()) <= {
                    "alembic_version"
                }
                command.upgrade(config, "head")
                command.check(config)

            await connection.run_sync(run_cycle)
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_type t JOIN pg_namespace n "
                        "ON n.oid=t.typnamespace "
                        "WHERE n.nspname=:schema AND t.typtype='e'"
                    ),
                    {"schema": schema},
                )
                == 0
            )
        finally:
            await transaction.rollback()


def test_passwords_are_hashed_and_verifiable() -> None:
    password = "password_for_tests_only"
    hashed = hash_password(password)
    assert hashed != password
    assert hashed.startswith("$argon2id$")
    assert verify_password(password, hashed)
    assert not verify_password("wrong_password", hashed)
    assert not verify_password(password, password)


def test_model_lengths_match_schema_and_constants() -> None:
    title_type = Task.__table__.c.title.type
    description_type = Task.__table__.c.description.type
    assert isinstance(title_type, String)
    assert isinstance(description_type, String)
    assert title_type.length == TITLE_MAX_LENGTH
    assert description_type.length == DESCRIPTION_MAX_LENGTH
    properties = TaskCreate.model_json_schema()["properties"]
    assert properties["title"]["maxLength"] == TITLE_MAX_LENGTH
    assert properties["description"]["anyOf"][0]["maxLength"] == DESCRIPTION_MAX_LENGTH
    for foreign_key in Base.metadata.sorted_tables:
        for constraint in foreign_key.foreign_key_constraints:
            assert constraint.ondelete in {"CASCADE", "SET NULL", "RESTRICT"}


async def test_server_defaults_work_for_raw_sql(
    db_session: AsyncSession, project: Project
) -> None:
    owner_id = await db_session.scalar(
        select(Workspace.owner_id).where(Workspace.id == project.workspace_id)
    )
    row = (
        await db_session.execute(
            text(
                "INSERT INTO tasks (project_id, title, created_by) "
                "VALUES (:project, :title, :owner) "
                "RETURNING status, priority, created_at"
            ),
            {"project": project.id, "title": "SQL insert", "owner": owner_id},
        )
    ).one()
    assert row.status == TaskStatus.TODO.value
    assert row.priority == TaskPriority.MEDIUM.value
    assert row.created_at.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE projects SET status='INVALID' WHERE id=:id",
        "UPDATE projects SET workspace_id=-1 WHERE id=:id",
    ],
)
async def test_database_rejects_invalid_enum_and_foreign_key(
    db_session: AsyncSession, project: Project, statement: str
) -> None:
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(text(statement), {"id": project.id})


async def test_project_deletion_cascades_to_tasks_labels_and_comments(
    db_session: AsyncSession, project: Project
) -> None:
    owner_id = await db_session.scalar(
        select(Workspace.owner_id).where(Workspace.id == project.workspace_id)
    )
    task = Task(title="Cascade", project_id=project.id, created_by=owner_id)
    label = Label(name="Test", color="#ffffff", project_id=project.id)
    db_session.add_all([task, label])
    await db_session.flush()
    comment = Comment(task_id=task.id, author_id=owner_id, content="Test comment")
    db_session.add_all([TaskLabel(task_id=task.id, label_id=label.id), comment])
    await db_session.flush()
    task_id, label_id, comment_id = task.id, label.id, comment.id

    await db_session.delete(project)
    await db_session.flush()

    assert await db_session.scalar(select(Task.id).where(Task.id == task_id)) is None
    assert await db_session.scalar(select(Label.id).where(Label.id == label_id)) is None
    assert (
        await db_session.scalar(select(Comment.id).where(Comment.id == comment_id))
        is None
    )
    assert (
        await db_session.scalar(
            select(TaskLabel.task_id).where(TaskLabel.task_id == task_id)
        )
        is None
    )


async def test_deleting_assignee_clears_task_assignment(
    db_session: AsyncSession, project: Project
) -> None:
    owner_id = await db_session.scalar(
        select(Workspace.owner_id).where(Workspace.id == project.workspace_id)
    )
    assignee = User(
        email=f"{uuid4().hex}@example.test",
        full_name="Assignee",
        hashed_password=hash_password("test_password_only"),
    )
    db_session.add(assignee)
    await db_session.flush()
    task = Task(
        title="Assignment",
        project_id=project.id,
        created_by=owner_id,
        assignee_id=assignee.id,
    )
    db_session.add(task)
    await db_session.flush()
    await db_session.delete(assignee)
    await db_session.flush()
    await db_session.refresh(task)
    assert task.assignee_id is None


async def test_owner_delete_is_restricted(
    db_session: AsyncSession, project: Project
) -> None:
    owner_id = await db_session.scalar(
        select(Workspace.owner_id).where(Workspace.id == project.workspace_id)
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("DELETE FROM users WHERE id=:id"), {"id": owner_id}
            )


async def test_reverse_association_foreign_keys_have_indexes(
    db_session: AsyncSession,
) -> None:
    connection = await db_session.connection()

    def check_indexes(sync_connection: Connection) -> None:
        inspector = inspect(sync_connection)
        for table, column in [
            ("task_labels", "label_id"),
            ("workspace_members", "user_id"),
            ("tasks", "project_id"),
            ("tasks", "assignee_id"),
            ("tasks", "created_by"),
        ]:
            assert any(
                index["column_names"][0] == column
                for index in inspector.get_indexes(table)
            )

    await connection.run_sync(check_indexes)
