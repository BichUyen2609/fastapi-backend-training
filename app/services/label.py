from app.core.constants import (
    LABEL_NAME_TAKEN,
    LABEL_NOT_FOUND,
    LABEL_PROJECT_MISMATCH,
    TASK_NOT_FOUND,
)
from app.core.exceptions import InvalidReferenceException, NotFoundException
from app.models.entities import Label, User
from app.repositories.label import LabelRepository
from app.schemas.label import LabelCreate, LabelUpdate
from app.services.base import authorize_project, transaction


class LabelService:
    def __init__(self, repository: LabelRepository, actor: User) -> None:
        self.repository = repository
        self.actor = actor

    async def get_label(self, label_id: int) -> Label:
        label = await self.repository.get(label_id)
        if label is None:
            raise NotFoundException(LABEL_NOT_FOUND)
        return label

    async def task_project(self, task_id: int) -> int:
        project_id = await self.repository.task_project(task_id)
        if project_id is None:
            raise NotFoundException(TASK_NOT_FOUND)
        return project_id

    async def create_label(self, project_id: int, data: LabelCreate) -> Label:
        async with transaction(self.repository.session, LABEL_NAME_TAKEN):
            await authorize_project(self.repository, self.actor, project_id, write=True)
            label = await self.repository.create(
                data.model_dump() | {"project_id": project_id}
            )
        await self.repository.session.refresh(label)
        return label

    async def list_labels(self, project_id: int) -> list[Label]:
        await authorize_project(self.repository, self.actor, project_id)
        return await self.repository.for_project(project_id)

    async def update_label(self, label_id: int, data: LabelUpdate) -> Label:
        changes = data.model_dump(exclude_unset=True)
        async with transaction(self.repository.session, LABEL_NAME_TAKEN):
            label = await self.get_label(label_id)
            await authorize_project(
                self.repository, self.actor, label.project_id, write=True
            )
            if changes:
                updated = await self.repository.update(label_id, changes)
                if updated is None:
                    raise NotFoundException(LABEL_NOT_FOUND)
                label = updated
        return label

    async def delete_label(self, label_id: int) -> None:
        async with transaction(self.repository.session):
            label = await self.get_label(label_id)
            await authorize_project(
                self.repository, self.actor, label.project_id, write=True
            )
            await self.repository.delete(label_id)

    async def task_labels(self, task_id: int) -> list[Label]:
        project_id = await self.task_project(task_id)
        await authorize_project(self.repository, self.actor, project_id)
        return await self.repository.for_task(task_id)

    async def attach(self, task_id: int, label_id: int) -> list[Label]:
        async with transaction(self.repository.session):
            project_id = await self.task_project(task_id)
            await authorize_project(self.repository, self.actor, project_id, write=True)
            label = await self.get_label(label_id)
            if label.project_id != project_id:
                raise InvalidReferenceException(LABEL_PROJECT_MISMATCH)
            await self.repository.attach(task_id, label_id)
        return await self.repository.for_task(task_id)

    async def detach(self, task_id: int, label_id: int) -> None:
        async with transaction(self.repository.session):
            project_id = await self.task_project(task_id)
            await authorize_project(self.repository, self.actor, project_id, write=True)
            await self.repository.detach(task_id, label_id)
