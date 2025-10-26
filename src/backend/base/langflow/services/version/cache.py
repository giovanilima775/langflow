from __future__ import annotations

from typing import Any
from uuid import UUID

from lfx.services.cache.utils import CACHE_MISS

from langflow.services.cache.base import AsyncBaseCacheService, CacheService
from langflow.services.deps import get_cache_service
from langflow.services.version.exceptions import VersionNotFoundError
from langflow.services.database.models.flow.version_models import FlowVersionRead


class VersionCacheService:
    """Cache helper for storing frequently accessed version data."""

    def __init__(self, cache_service: CacheService | AsyncBaseCacheService | None = None) -> None:
        self._cache = cache_service or get_cache_service()

    async def cache_active_version(self, flow_id: UUID, version_data: FlowVersionRead) -> None:
        await self._set(self._active_key(flow_id), version_data.model_dump(mode="json"))

    async def get_cached_active_version(self, flow_id: UUID) -> FlowVersionRead | None:
        cached = await self._get(self._active_key(flow_id))
        if cached in (None, CACHE_MISS):
            return None
        return FlowVersionRead.model_validate(cached)

    async def invalidate_flow_cache(self, flow_id: UUID) -> None:
        await self._delete(self._active_key(flow_id))

    async def cache_version_data(self, version_id: UUID, version_data: FlowVersionRead) -> None:
        await self._set(self._version_key(version_id), version_data.model_dump(mode="json"))

    async def get_cached_version(self, version_id: UUID) -> FlowVersionRead | None:
        cached = await self._get(self._version_key(version_id))
        if cached in (None, CACHE_MISS):
            return None
        return FlowVersionRead.model_validate(cached)

    async def invalidate_version(self, version_id: UUID) -> None:
        await self._delete(self._version_key(version_id))

    async def _get(self, key: str) -> Any:
        if isinstance(self._cache, AsyncBaseCacheService):
            return await self._cache.get(key)
        if isinstance(self._cache, CacheService):
            return self._cache.get(key)
        msg = "Cache service is not configured"
        raise VersionNotFoundError(msg)

    async def _set(self, key: str, value: Any) -> None:
        if isinstance(self._cache, AsyncBaseCacheService):
            await self._cache.set(key, value)
            return
        if isinstance(self._cache, CacheService):
            self._cache.set(key, value)
            return
        msg = "Cache service is not configured"
        raise VersionNotFoundError(msg)

    async def _delete(self, key: str) -> None:
        if isinstance(self._cache, AsyncBaseCacheService):
            await self._cache.delete(key)
            return
        if isinstance(self._cache, CacheService):
            self._cache.delete(key)
            return
        msg = "Cache service is not configured"
        raise VersionNotFoundError(msg)

    @staticmethod
    def _active_key(flow_id: UUID) -> str:
        return f"flow:{flow_id}:active_version"

    @staticmethod
    def _version_key(version_id: UUID) -> str:
        return f"flow_version:{version_id}"
