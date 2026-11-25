import hashlib
import json
import logging

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import RedisError

from app.core.config import Settings
from app.schemas.task import TaskFilters, TaskPage

logger = logging.getLogger("taskhub.cache")


class TaskCache:
    def __init__(self, settings: Settings) -> None:
        self.namespace = settings.cache_namespace
        self.ttl = settings.cache_ttl_seconds
        self.client = (
            Redis.from_url(
                str(settings.redis_url),
                socket_timeout=settings.redis_timeout_seconds,
                socket_connect_timeout=settings.redis_timeout_seconds,
                retry=Retry(NoBackoff(), 0),
                protocol=2,
            )
            if settings.redis_url is not None
            else None
        )

    def key(
        self,
        project_id: int,
        version: int,
        page: int,
        limit: int,
        filters: TaskFilters,
    ) -> str:
        query = filters.model_dump(mode="json") | {"page": page, "limit": limit}
        digest = hashlib.sha256(json.dumps(query, sort_keys=True).encode()).hexdigest()
        return f"{self.namespace}:tasks:v1:{project_id}:{version}:{digest}"

    async def get(self, key: str) -> TaskPage | None:
        if self.client is None:
            return None
        try:
            payload = await self.client.get(key)
            if payload is not None:
                return TaskPage.model_validate_json(payload)
        except (RedisError, ValidationError, UnicodeError):
            logger.warning("Task cache read failed; using database")
        return None

    async def set(self, key: str, page: TaskPage) -> None:
        if self.client is None:
            return
        try:
            await self.client.set(key, page.model_dump_json(), ex=self.ttl)
        except RedisError:
            logger.warning("Task cache write failed; response served from database")

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()
