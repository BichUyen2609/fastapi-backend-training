import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

from fastapi import BackgroundTasks

from app.core.config import Settings

logger = logging.getLogger("taskhub.notifications")


@dataclass(frozen=True)
class TaskAssignment:
    task_id: int
    project_id: int
    assignee_id: int
    recipient: str
    title: str
    assigned_by: str


class AssignmentNotifier:
    def __init__(self, settings: Settings, background_tasks: BackgroundTasks) -> None:
        self.settings = settings
        self.background_tasks = background_tasks

    def schedule(self, assignment: TaskAssignment | None) -> None:
        if self.settings.notifications_enabled and assignment is not None:
            self.background_tasks.add_task(self.send, assignment)

    def send(self, assignment: TaskAssignment) -> None:
        try:
            message = EmailMessage()
            message["From"] = str(self.settings.smtp_sender)
            message["To"] = assignment.recipient
            message["Subject"] = f"TaskHub: Task #{assignment.task_id} assigned"
            message.set_content(
                f"{assignment.assigned_by} assigned a task to you.\n\n"
                f"Task: {assignment.title}\n"
                f"Task ID: {assignment.task_id}\n"
                f"Project ID: {assignment.project_id}\n"
            )
            host = self.settings.smtp_host
            if host is None:
                return
            client: smtplib.SMTP
            if self.settings.smtp_security == "ssl":
                client = smtplib.SMTP_SSL(
                    host,
                    self.settings.smtp_port,
                    timeout=self.settings.smtp_timeout_seconds,
                    context=ssl.create_default_context(),
                )
            else:
                client = smtplib.SMTP(
                    host,
                    self.settings.smtp_port,
                    timeout=self.settings.smtp_timeout_seconds,
                )
            with client:
                if self.settings.smtp_security == "starttls":
                    client.starttls(context=ssl.create_default_context())
                if self.settings.smtp_username and self.settings.smtp_password:
                    client.login(
                        self.settings.smtp_username,
                        self.settings.smtp_password.get_secret_value(),
                    )
                client.send_message(message)
            logger.info(
                "Assignment email delivered task_id=%s assignee_id=%s",
                assignment.task_id,
                assignment.assignee_id,
            )
        except (OSError, smtplib.SMTPException, ValueError) as exc:
            logger.warning(
                "Assignment email failed task_id=%s error=%s",
                assignment.task_id,
                type(exc).__name__,
            )
