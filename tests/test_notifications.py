import asyncio
import logging
import smtplib
import threading
from collections.abc import AsyncIterator
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiosmtpd.smtp import SMTP, Envelope, Session
from fastapi import BackgroundTasks, FastAPI
from httpx2 import AsyncClient
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import WorkspaceRole
from app.core.logging import request_id_context
from app.models.entities import Project, User
from app.services.notification import AssignmentNotifier, TaskAssignment
from tests.test_auth import new_user
from tests.test_workspaces import join

pytestmark = pytest.mark.anyio


@pytest.fixture
async def smtp_server() -> AsyncIterator[tuple[int, list[EmailMessage]]]:
    messages: list[EmailMessage] = []

    class Inbox:
        async def handle_DATA(
            self, server: SMTP, session: Session, envelope: Envelope
        ) -> str:
            assert isinstance(envelope.content, bytes)
            messages.append(
                BytesParser(policy=policy.default).parsebytes(envelope.content)
            )
            return "250 Accepted"

    server = await asyncio.get_running_loop().create_server(
        lambda: SMTP(Inbox(), hostname="localhost"), "127.0.0.1", 0
    )
    try:
        yield server.sockets[0].getsockname()[1], messages
    finally:
        server.close()
        await server.wait_closed()


@pytest.fixture
async def notification_client(
    client: AsyncClient,
    application: FastAPI,
    smtp_server: tuple[int, list[EmailMessage]],
) -> AsyncIterator[AsyncClient]:
    original: Settings = application.state.settings
    application.state.settings = Settings.model_validate(
        original.model_dump()
        | {
            "notifications_enabled": True,
            "smtp_host": "127.0.0.1",
            "smtp_port": smtp_server[0],
            "smtp_sender": "notifications@example.com",
            "smtp_security": "none",
            "smtp_username": None,
            "smtp_password": None,
        }
    )
    try:
        yield client
    finally:
        application.state.settings = original


async def test_assignment_delivers_real_smtp_email(
    notification_client: AsyncClient,
    smtp_server: tuple[int, list[EmailMessage]],
    project: Project,
    current_user: User,
) -> None:
    response = await notification_client.post(
        "/api/v1/tasks",
        json={
            "project_id": project.id,
            "title": "Nhiệm vụ mới",
            "assignee_id": current_user.id,
        },
    )
    assert response.status_code == 201
    messages = smtp_server[1]
    assert len(messages) == 1
    message = messages[0]
    assert message["To"] == current_user.email
    assert message["From"] == "notifications@example.com"
    assert message["Subject"] == f"TaskHub: Task #{response.json()['id']} assigned"
    body = message.get_content()
    assert "Nhiệm vụ mới" in body
    assert str(project.id) in body
    assert "Bearer" not in body and "password" not in body


async def test_only_new_non_null_assignments_send_email(
    notification_client: AsyncClient,
    smtp_server: tuple[int, list[EmailMessage]],
    project: Project,
    current_user: User,
    db_session: AsyncSession,
) -> None:
    response = await notification_client.post(
        "/api/v1/tasks", json={"project_id": project.id, "title": "Unassigned"}
    )
    task_url = f"/api/v1/tasks/{response.json()['id']}"
    messages = smtp_server[1]
    assert not messages
    assert (
        await notification_client.patch(task_url, json={"assignee_id": current_user.id})
    ).status_code == 200
    assert len(messages) == 1
    for changes in (
        {},
        {"assignee_id": current_user.id},
        {"title": "Rename"},
        {"assignee_id": None},
    ):
        assert (
            await notification_client.patch(task_url, json=changes)
        ).status_code == 200
        assert len(messages) == 1
    other = await join(db_session, project.workspace_id, WorkspaceRole.EDITOR)
    assert (
        await notification_client.patch(task_url, json={"assignee_id": other.id})
    ).status_code == 200
    assert len(messages) == 2
    assert messages[-1]["To"] == other.email


async def test_rejected_assignment_does_not_send_email(
    notification_client: AsyncClient,
    smtp_server: tuple[int, list[EmailMessage]],
    project: Project,
    db_session: AsyncSession,
) -> None:
    outsider = await new_user(db_session)
    response = await notification_client.post(
        "/api/v1/tasks",
        json={"project_id": project.id, "title": "Invalid", "assignee_id": outsider.id},
    )
    assert response.status_code == 422
    assert not smtp_server[1]


async def test_commit_failure_rolls_back_and_does_not_schedule_email(
    application: FastAPI,
    notification_client: AsyncClient,
    smtp_server: tuple[int, list[EmailMessage]],
    project: Project,
    current_user: User,
) -> None:
    failure = IntegrityError("private SQL", {}, ValueError("private constraint"))
    with patch.object(AsyncSession, "commit", AsyncMock(side_effect=failure)):
        response = await notification_client.post(
            "/api/v1/tasks",
            json={
                "project_id": project.id,
                "title": "Rollback",
                "assignee_id": current_user.id,
            },
        )
    assert response.status_code == 409
    assert not smtp_server[1]
    assert (
        await notification_client.get(f"/api/v1/projects/{project.id}/tasks")
    ).json()["total"] == 0


async def test_smtp_failure_preserves_task_and_redacts_log_values(
    notification_client: AsyncClient,
    project: Project,
    current_user: User,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        patch(
            "app.services.notification.smtplib.SMTP",
            side_effect=smtplib.SMTPException("smtp-password-private"),
        ),
        caplog.at_level(logging.WARNING, logger="taskhub.notifications"),
    ):
        response = await notification_client.post(
            "/api/v1/tasks",
            json={
                "project_id": project.id,
                "title": "Still committed",
                "assignee_id": current_user.id,
            },
        )
    assert response.status_code == 201
    assert (
        await notification_client.get(f"/api/v1/tasks/{response.json()['id']}")
    ).json() == response.json()
    assert "Assignment email failed" in caplog.text
    assert "smtp-password-private" not in caplog.text
    assert current_user.email not in caplog.text


async def test_background_email_runs_after_commit_in_thread_with_request_context(
    application: FastAPI,
    notification_client: AsyncClient,
    project: Project,
    current_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    event_threads: list[int] = []
    contexts: list[str | None] = []
    main_thread = threading.get_ident()

    async def record_commit(session: AsyncSession) -> None:
        await original_commit(session)
        events.append("commit")

    def send(notifier: AssignmentNotifier, assignment: TaskAssignment) -> None:
        events.append("send")
        event_threads.append(threading.get_ident())
        contexts.append(request_id_context.get())
        assert isinstance(assignment, TaskAssignment)

    original_commit = AsyncSession.commit
    monkeypatch.setattr(AsyncSession, "commit", record_commit)
    monkeypatch.setattr(AssignmentNotifier, "send", send)
    response = await notification_client.post(
        "/api/v1/tasks",
        headers={"X-Request-ID": "background-request-0001"},
        json={
            "project_id": project.id,
            "title": "Background",
            "assignee_id": current_user.id,
        },
    )
    assert response.status_code == 201
    assert events == ["commit", "send"]
    assert event_threads[0] != main_thread
    assert contexts == ["background-request-0001"]
    assert request_id_context.get() is None


async def test_disabled_notifications_never_connect_to_smtp(
    client: AsyncClient, project: Project, current_user: User
) -> None:
    with patch("app.services.notification.smtplib.SMTP") as smtp:
        response = await client.post(
            "/api/v1/tasks",
            json={
                "project_id": project.id,
                "title": "Disabled",
                "assignee_id": current_user.id,
            },
        )
    assert response.status_code == 201
    smtp.assert_not_called()


@pytest.mark.parametrize("security", ["starttls", "ssl"])
def test_smtp_tls_and_authentication_are_configurable(
    test_settings: Settings, security: str
) -> None:
    settings = Settings.model_validate(
        test_settings.model_dump()
        | {
            "notifications_enabled": True,
            "smtp_host": "smtp.example.com",
            "smtp_sender": "notifications@example.com",
            "smtp_security": security,
            "smtp_username": "smtp-user",
            "smtp_password": SecretStr("smtp-password-private"),
        }
    )
    client = MagicMock()
    client.__enter__.return_value = client
    with (
        patch("app.services.notification.smtplib.SMTP", return_value=client) as plain,
        patch(
            "app.services.notification.smtplib.SMTP_SSL", return_value=client
        ) as encrypted,
    ):
        notifier = AssignmentNotifier(settings, BackgroundTasks())
        notifier.send(TaskAssignment(1, 2, 3, "recipient@example.com", "TLS", "Owner"))
    client.login.assert_called_once_with("smtp-user", "smtp-password-private")
    client.send_message.assert_called_once()
    if security == "starttls":
        plain.assert_called_once()
        encrypted.assert_not_called()
        client.starttls.assert_called_once()
    else:
        encrypted.assert_called_once()
        plain.assert_not_called()
        client.starttls.assert_not_called()
