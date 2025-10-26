from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload
from sqlmodel.ext.asyncio.session import AsyncSession

from langflow.services.base import Service
from langflow.services.database.models.flow.model import Flow
from langflow.services.database.models.flow.version_models import (
    FlowVersion,
    FlowVersionRead,
    FlowVersionSummary,
    FlowWithVersions,
    VersionComparisonResult,
    VersionMetadata,
    VersionMetrics,
)
from langflow.services.deps import session_scope
from langflow.services.version.cache import VersionCacheService
from langflow.services.version.exceptions import (
    ActiveVersionNotSetError,
    InvalidVersionOperationError,
    VersionConflictError,
    VersionNotFoundError,
)


class VersionService(Service):
    """Service responsible for managing flow versions."""

    name = "version_service"

    def __init__(self, cache_service: VersionCacheService | None = None) -> None:
        self._cache = cache_service or VersionCacheService()

    async def publish_version(
        self,
        flow_id: UUID,
        user_id: UUID,
        *,
        description: str | None = None,
        version_tag: str | None = None,
        changelog: str | None = None,
        created_from_version_id: UUID | None = None,
        activate: bool = True,
    ) -> FlowVersionRead:
        async with session_scope() as session:
            flow = await session.get(Flow, flow_id)
            if flow is None:
                msg = f"Flow {flow_id} not found"
                raise VersionNotFoundError(msg)

            if flow.data is None:
                msg = "Cannot publish a flow without data"
                raise InvalidVersionOperationError(msg)

            await session.refresh(flow)

            if version_tag:
                stmt = select(FlowVersion.id).where(
                    FlowVersion.flow_id == flow_id, FlowVersion.version_tag == version_tag
                )
                existing = (await session.exec(stmt)).first()
                if existing:
                    msg = f"Version tag {version_tag} already exists for flow {flow_id}"
                    raise VersionConflictError(msg)

            next_version_number = await self._get_next_version_number(session, flow_id)
            now = datetime.now(timezone.utc)
            parent_hash = self._hash_flow_data(flow.data)

            new_version = FlowVersion(
                flow_id=flow_id,
                version_number=next_version_number,
                version_tag=version_tag,
                name=flow.name,
                description=flow.description,
                data=json.loads(json.dumps(flow.data)),
                icon=flow.icon,
                icon_bg_color=flow.icon_bg_color,
                gradient=flow.gradient,
                endpoint_name=flow.endpoint_name,
                tags=flow.tags or [],
                mcp_enabled=bool(flow.mcp_enabled),
                run_in_background=False,
                action_name=flow.action_name,
                action_description=flow.action_description,
                access_type=flow.access_type,
                published_by=user_id,
                published_at=now,
                description_version=description,
                changelog=changelog,
                created_from_version_id=created_from_version_id,
                parent_flow_data_hash=parent_hash,
                is_active=False,
                created_at=now,
                updated_at=now,
            )

            session.add(new_version)
            await session.flush()

            metadata = VersionMetadata(version_id=new_version.id, created_at=now, updated_at=now)
            session.add(metadata)

            flow.version_count = (flow.version_count or 0) + 1
            flow.last_published_at = now
            flow.is_draft = True

            await session.flush()

            if activate or flow.active_version_id is None:
                await self._activate_version(session, flow, new_version)

            await session.refresh(new_version)
            await session.refresh(flow)
            await session.refresh(metadata)

        read = self._to_read_model(new_version, metadata)
        await self._cache.invalidate_flow_cache(flow_id)
        if new_version.is_active:
            await self._cache.cache_active_version(flow_id, read)
        await self._cache.cache_version_data(new_version.id, read)
        return read

    async def get_version(self, flow_id: UUID, identifier: str) -> FlowVersionRead:
        try:
            version_uuid = UUID(identifier)
        except ValueError:
            version_uuid = None

        if version_uuid:
            cached = await self._cache.get_cached_version(version_uuid)
            if cached:
                return cached

        async with session_scope() as session:
            query = select(FlowVersion).options(selectinload(FlowVersion.metadata))
            if version_uuid:
                query = query.where(FlowVersion.id == version_uuid, FlowVersion.flow_id == flow_id)
            elif identifier.isdigit() or (identifier.lower().startswith("v") and identifier[1:].isdigit()):
                number_value = int(identifier[1:]) if identifier.lower().startswith("v") else int(identifier)
                query = query.where(
                    FlowVersion.flow_id == flow_id, FlowVersion.version_number == number_value
                )
            else:
                query = query.where(
                    FlowVersion.flow_id == flow_id, FlowVersion.version_tag == identifier
                )
            version = (await session.exec(query)).one_or_none()

        if version is None:
            msg = f"Version {identifier} not found for flow {flow_id}"
            raise VersionNotFoundError(msg)

        read = self._to_read_model(version)
        await self._cache.cache_version_data(read.id, read)
        return read

    async def get_active_version(self, flow_id: UUID) -> FlowVersionRead | None:
        cached = await self._cache.get_cached_active_version(flow_id)
        if cached:
            return cached

        async with session_scope() as session:
            stmt = (
                select(FlowVersion)
                .options(selectinload(FlowVersion.metadata))
                .where(FlowVersion.flow_id == flow_id, FlowVersion.is_active.is_(True))
            )
            version = (await session.exec(stmt)).first()
            if version is None:
                return None
            read = self._to_read_model(version)

        await self._cache.cache_active_version(flow_id, read)
        await self._cache.cache_version_data(read.id, read)
        return read

    async def set_active_version(self, flow_id: UUID, version_id: UUID, user_id: UUID | None = None) -> FlowVersionRead:
        async with session_scope() as session:
            flow = await session.get(Flow, flow_id)
            if flow is None:
                msg = f"Flow {flow_id} not found"
                raise VersionNotFoundError(msg)

            stmt = (
                select(FlowVersion)
                .options(selectinload(FlowVersion.metadata))
                .where(FlowVersion.id == version_id, FlowVersion.flow_id == flow_id)
            )
            version = (await session.exec(stmt)).first()
            if version is None:
                msg = f"Version {version_id} not found for flow {flow_id}"
                raise VersionNotFoundError(msg)

            await self._activate_version(session, flow, version)
            await session.refresh(version)

        read = self._to_read_model(version)
        await self._cache.invalidate_flow_cache(flow_id)
        await self._cache.cache_active_version(flow_id, read)
        await self._cache.cache_version_data(version_id, read)
        return read

    async def get_version_history(
        self, flow_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> list[FlowVersionSummary]:
        async with session_scope() as session:
            stmt = (
                select(FlowVersion)
                .options(selectinload(FlowVersion.metadata))
                .where(FlowVersion.flow_id == flow_id)
                .order_by(FlowVersion.version_number.desc())
                .offset(offset)
                .limit(limit)
            )
            versions = (await session.exec(stmt)).all()
        return [self._to_summary_model(version) for version in versions]

    async def create_draft_from_version(
        self, flow_id: UUID, version_id: UUID, user_id: UUID | None = None
    ) -> dict[str, Any]:
        async with session_scope() as session:
            flow = await session.get(Flow, flow_id)
            if flow is None:
                msg = f"Flow {flow_id} not found"
                raise VersionNotFoundError(msg)

            version = await session.get(FlowVersion, version_id)
            if version is None or version.flow_id != flow_id:
                msg = f"Version {version_id} not found for flow {flow_id}"
                raise VersionNotFoundError(msg)

            flow.data = json.loads(json.dumps(version.data))
            flow.name = version.name
            flow.description = version.description
            flow.icon = version.icon
            flow.icon_bg_color = version.icon_bg_color
            flow.gradient = version.gradient
            flow.endpoint_name = version.endpoint_name
            flow.tags = version.tags
            flow.mcp_enabled = version.mcp_enabled
            flow.action_name = version.action_name
            flow.action_description = version.action_description
            flow.access_type = version.access_type
            flow.is_draft = True
            flow.updated_at = datetime.now(timezone.utc)

            await session.flush()
            await session.refresh(flow)

        return json.loads(json.dumps(flow.data)) if flow.data else {}

    async def compare_versions(self, version_a_id: UUID, version_b_id: UUID) -> VersionComparisonResult:
        async with session_scope() as session:
            stmt = (
                select(FlowVersion)
                .options(selectinload(FlowVersion.metadata))
                .where(FlowVersion.id.in_([version_a_id, version_b_id]))
            )
            versions = (await session.exec(stmt)).all()

        if len(versions) != 2:
            msg = "Both versions must exist for comparison"
            raise VersionNotFoundError(msg)

        version_map = {version.id: version for version in versions}
        version_a = version_map[version_a_id]
        version_b = version_map[version_b_id]

        differences = self._diff(version_a.data, version_b.data)
        change_count = sum(1 for _ in self._flatten_diff(differences))
        summary = f"{change_count} changes detected"

        return VersionComparisonResult(
            version_a=self._to_read_model(version_a),
            version_b=self._to_read_model(version_b),
            differences=differences,
            summary=summary,
        )

    async def get_version_metrics(self, version_id: UUID) -> VersionMetrics:
        async with session_scope() as session:
            stmt = select(VersionMetadata).where(VersionMetadata.version_id == version_id)
            metadata = (await session.exec(stmt)).one_or_none()
        if metadata is None:
            msg = f"Metrics not found for version {version_id}"
            raise VersionNotFoundError(msg)
        return self._to_metrics_model(metadata)

    async def rollback_to_version(self, flow_id: UUID, version_id: UUID, user_id: UUID | None = None) -> FlowVersionRead:
        return await self.set_active_version(flow_id, version_id, user_id)

    async def record_execution_metrics(
        self,
        version_id: UUID,
        execution_time_ms: int,
        *,
        success: bool,
        endpoint_type: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        async with session_scope() as session:
            stmt = select(VersionMetadata).where(VersionMetadata.version_id == version_id)
            metadata = (await session.exec(stmt)).one_or_none()
            if metadata is None:
                metadata = VersionMetadata(version_id=version_id, created_at=now, updated_at=now)
                session.add(metadata)
            metadata.execution_count = (metadata.execution_count or 0) + 1
            metadata.total_execution_time_ms = (metadata.total_execution_time_ms or 0) + int(execution_time_ms)
            metadata.avg_execution_time_ms = (
                metadata.total_execution_time_ms / metadata.execution_count if metadata.execution_count else 0
            )
            metadata.last_executed_at = now
            if not success:
                metadata.error_count = (metadata.error_count or 0) + 1
                metadata.last_error_at = now

            counter_field = self._endpoint_counter_name(endpoint_type)
            if counter_field:
                current_value = getattr(metadata, counter_field)
                setattr(metadata, counter_field, (current_value or 0) + 1)

            metadata.updated_at = now
            await session.flush()

            stmt_version = select(FlowVersion).where(FlowVersion.id == version_id)
            version = (await session.exec(stmt_version)).one_or_none()

        if version:
            read = self._to_read_model(version, metadata)
            await self._cache.cache_version_data(version_id, read)
            if version.is_active:
                await self._cache.cache_active_version(version.flow_id, read)

    async def get_flow_with_versions(self, flow_id: UUID) -> FlowWithVersions:
        async with session_scope() as session:
            stmt = (
                select(Flow)
                .options(selectinload(Flow.versions).selectinload(FlowVersion.metadata))
                .where(Flow.id == flow_id)
            )
            flow = (await session.exec(stmt)).one_or_none()
        if flow is None:
            msg = f"Flow {flow_id} not found"
            raise VersionNotFoundError(msg)

        active_version = next((version for version in flow.versions if version.is_active), None)
        return FlowWithVersions(
            id=flow.id,
            name=flow.name,
            description=flow.description,
            is_draft=flow.is_draft,
            active_version_id=flow.active_version_id,
            version_count=flow.version_count,
            last_published_at=flow.last_published_at,
            versions=[self._to_summary_model(version) for version in sorted(flow.versions, key=lambda v: v.version_number, reverse=True)],
            active_version=self._to_read_model(active_version) if active_version else None,
            draft_data=json.loads(json.dumps(flow.data)) if flow.data else None,
        )

    async def _activate_version(self, session: AsyncSession, flow: Flow, version: FlowVersion) -> None:
        await session.exec(
            update(FlowVersion)
            .where(FlowVersion.flow_id == flow.id, FlowVersion.id != version.id, FlowVersion.is_active.is_(True))
            .values(is_active=False, updated_at=datetime.now(timezone.utc))
        )
        version.is_active = True
        version.updated_at = datetime.now(timezone.utc)
        flow.active_version_id = version.id
        flow.last_published_at = version.published_at
        flow.is_draft = False
        await session.flush()

    async def _get_next_version_number(self, session, flow_id: UUID) -> int:
        stmt = select(func.max(FlowVersion.version_number)).where(FlowVersion.flow_id == flow_id)
        result = (await session.exec(stmt)).one()
        current = result or 0
        return current + 1

    def _to_read_model(self, version: FlowVersion | None, metadata: VersionMetadata | None = None) -> FlowVersionRead:
        if version is None:
            raise ActiveVersionNotSetError("No active version available")
        read = FlowVersionRead.model_validate(version, from_attributes=True)
        meta = metadata or version.metadata
        if meta:
            read.execution_count = meta.execution_count or 0
            read.last_executed_at = meta.last_executed_at
            read.avg_execution_time_ms = meta.avg_execution_time_ms
            read.error_count = meta.error_count or 0
        return read

    def _to_summary_model(self, version: FlowVersion) -> FlowVersionSummary:
        summary = FlowVersionSummary.model_validate(version, from_attributes=True)
        metadata = version.metadata
        if metadata:
            summary.execution_count = metadata.execution_count or 0
            summary.error_count = metadata.error_count or 0
        return summary

    def _to_metrics_model(self, metadata: VersionMetadata) -> VersionMetrics:
        return VersionMetrics(
            version_id=metadata.version_id,
            execution_count=metadata.execution_count or 0,
            error_count=metadata.error_count or 0,
            avg_execution_time_ms=metadata.avg_execution_time_ms,
            last_executed_at=metadata.last_executed_at,
            api_executions=metadata.api_executions or 0,
            mcp_executions=metadata.mcp_executions or 0,
            public_executions=metadata.public_executions or 0,
            webhook_executions=metadata.webhook_executions or 0,
        )

    def _hash_flow_data(self, data: dict[str, Any]) -> str:
        serialized = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(serialized).hexdigest()

    def _diff(self, data_a: Any, data_b: Any) -> dict[str, Any]:
        if isinstance(data_a, dict) and isinstance(data_b, dict):
            diff: dict[str, Any] = {}
            keys = set(data_a) | set(data_b)
            for key in keys:
                if key not in data_a:
                    diff[key] = {"added": data_b[key]}
                elif key not in data_b:
                    diff[key] = {"removed": data_a[key]}
                else:
                    child_diff = self._diff(data_a[key], data_b[key])
                    if child_diff:
                        diff[key] = child_diff
            return diff
        if isinstance(data_a, list) and isinstance(data_b, list):
            if data_a != data_b:
                return {"from": data_a, "to": data_b}
            return {}
        if data_a != data_b:
            return {"from": data_a, "to": data_b}
        return {}

    def _flatten_diff(self, diff: Any) -> Iterable[Any]:
        if isinstance(diff, dict):
            for value in diff.values():
                if isinstance(value, dict):
                    yield from self._flatten_diff(value)
                else:
                    yield value
        else:
            yield diff

    def _endpoint_counter_name(self, endpoint_type: str) -> str | None:
        normalized = endpoint_type.lower()
        mapping = {
            "api": "api_executions",
            "mcp": "mcp_executions",
            "public": "public_executions",
            "public_flow": "public_executions",
            "webhook": "webhook_executions",
        }
        return mapping.get(normalized)
