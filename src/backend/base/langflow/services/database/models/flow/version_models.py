from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlmodel import JSON, Column, Field as SQLField, Relationship, SQLModel, UniqueConstraint
from sqlalchemy import Index

from langflow.services.database.models.flow.model import AccessTypeEnum

if TYPE_CHECKING:  # pragma: no cover
    from langflow.services.database.models.flow.model import Flow
    from langflow.services.database.models.user.model import User


class VersionStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ACTIVE = "active"
    ARCHIVED = "archived"


class FlowVersionBase(BaseModel):
    version_number: int
    version_tag: str | None = None
    description_version: str | None = None
    changelog: str | None = None

    name: str
    description: str | None = None
    data: dict[str, Any]
    icon: str | None = None
    icon_bg_color: str | None = None
    gradient: str | None = None
    endpoint_name: str | None = None
    tags: list[str] = Field(default_factory=list)

    mcp_enabled: bool = False
    run_in_background: bool = False
    action_name: str | None = None
    action_description: str | None = None
    access_type: AccessTypeEnum = AccessTypeEnum.PRIVATE


class FlowVersionCreate(FlowVersionBase):
    flow_id: UUID
    published_by: UUID
    created_from_version_id: UUID | None = None


class FlowVersionRead(FlowVersionBase):
    id: UUID
    flow_id: UUID
    is_active: bool
    published_by: UUID
    published_at: datetime
    created_from_version_id: UUID | None = None

    execution_count: int = 0
    last_executed_at: datetime | None = None
    avg_execution_time_ms: float | None = None
    error_count: int = 0


class FlowVersionUpdate(BaseModel):
    description_version: str | None = None
    changelog: str | None = None
    is_active: bool | None = None


class FlowVersionSummary(BaseModel):
    id: UUID
    version_number: int
    version_tag: str | None = None
    is_active: bool
    published_at: datetime
    description_version: str | None = None
    execution_count: int = 0
    error_count: int = 0


class FlowWithVersions(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    is_draft: bool = True
    active_version_id: UUID | None = None
    version_count: int = 0
    last_published_at: datetime | None = None

    versions: list[FlowVersionSummary] = Field(default_factory=list)
    active_version: FlowVersionRead | None = None
    draft_data: dict[str, Any] | None = None


class VersionComparisonResult(BaseModel):
    version_a: FlowVersionRead
    version_b: FlowVersionRead
    differences: dict[str, Any]
    summary: str


class VersionMetrics(BaseModel):
    version_id: UUID
    execution_count: int
    error_count: int
    avg_execution_time_ms: float | None
    last_executed_at: datetime | None
    api_executions: int
    mcp_executions: int
    public_executions: int
    webhook_executions: int


class VersionMetadata(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "version_metadata"

    id: UUID = SQLField(default_factory=uuid4, primary_key=True, unique=True)
    version_id: UUID = SQLField(foreign_key="flow_version.id", unique=True, nullable=False)

    execution_count: int = SQLField(default=0, nullable=False)
    last_executed_at: datetime | None = SQLField(default=None, nullable=True)
    total_execution_time_ms: int = SQLField(default=0, nullable=False)
    avg_execution_time_ms: float | None = SQLField(default=None, nullable=True)

    error_count: int = SQLField(default=0, nullable=False)
    last_error_at: datetime | None = SQLField(default=None, nullable=True)

    api_executions: int = SQLField(default=0, nullable=False)
    mcp_executions: int = SQLField(default=0, nullable=False)
    public_executions: int = SQLField(default=0, nullable=False)
    webhook_executions: int = SQLField(default=0, nullable=False)

    deployment_environment: str | None = SQLField(default="production", nullable=True)
    rollback_count: int = SQLField(default=0, nullable=False)

    created_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc), nullable=False)

    version: "FlowVersion" = Relationship(back_populates="metadata")


class FlowVersion(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "flow_version"

    id: UUID = SQLField(default_factory=uuid4, primary_key=True, unique=True)
    flow_id: UUID = SQLField(foreign_key="flow.id", index=True, nullable=False)
    version_number: int = SQLField(nullable=False)
    version_tag: str | None = SQLField(default=None, nullable=True)

    name: str = SQLField(nullable=False)
    description: str | None = SQLField(default=None, nullable=True)
    data: dict[str, Any] = SQLField(sa_column=Column(JSON), nullable=False)
    icon: str | None = SQLField(default=None, nullable=True)
    icon_bg_color: str | None = SQLField(default=None, nullable=True)
    gradient: str | None = SQLField(default=None, nullable=True)
    endpoint_name: str | None = SQLField(default=None, nullable=True, index=True)
    tags: list[str] = SQLField(default_factory=list, sa_column=Column(JSON), nullable=False)

    mcp_enabled: bool = SQLField(default=False, nullable=False)
    run_in_background: bool = SQLField(default=False, nullable=False)
    action_name: str | None = SQLField(default=None, nullable=True)
    action_description: str | None = SQLField(default=None, nullable=True)
    access_type: AccessTypeEnum = SQLField(default=AccessTypeEnum.PRIVATE, nullable=False)

    is_active: bool = SQLField(default=False, nullable=False)
    published_by: UUID = SQLField(foreign_key="user.id", nullable=False)
    published_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc), nullable=False)
    description_version: str | None = SQLField(default=None, nullable=True)
    changelog: str | None = SQLField(default=None, nullable=True)

    created_from_version_id: UUID | None = SQLField(foreign_key="flow_version.id", default=None, nullable=True)
    parent_flow_data_hash: str | None = SQLField(default=None, nullable=True)

    created_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: datetime = SQLField(default_factory=lambda: datetime.now(timezone.utc), nullable=False)

    flow: "Flow" = Relationship(back_populates="versions")
    published_by_user: "User" = Relationship()
    metadata: Optional[VersionMetadata] = Relationship(back_populates="version")

    __table_args__ = (
        UniqueConstraint("flow_id", "version_number", name="unique_flow_version_number"),
        UniqueConstraint("flow_id", "version_tag", name="unique_flow_version_tag"),
        Index("idx_flow_version_active", "flow_id", "is_active"),
        Index("idx_flow_version_published_at", "published_at"),
    )


__all__ = [
    "FlowVersion",
    "FlowVersionBase",
    "FlowVersionCreate",
    "FlowVersionRead",
    "FlowVersionSummary",
    "FlowVersionUpdate",
    "FlowWithVersions",
    "VersionComparisonResult",
    "VersionMetrics",
    "VersionMetadata",
    "VersionStatus",
]
