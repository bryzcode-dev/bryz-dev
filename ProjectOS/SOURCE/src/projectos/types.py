from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping
from uuid import UUID

from .errors import ValidationError


class ProjectStatus(StrEnum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"


class ProjectVisibility(StrEnum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"


class ProjectType(StrEnum):
    GAS = "GAS"
    SHEET_GCP = "SHEET_GCP"
    LOOKER = "LOOKER"
    GIT = "GIT"
    LOCAL = "LOCAL"
    MIXED = "MIXED"
    OTHER = "OTHER"


class DeploymentEnvironment(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    STAGING = "STAGING"
    PRODUCTION = "PRODUCTION"
    OTHER = "OTHER"


class ConnectionDirection(StrEnum):
    DIRECTED = "DIRECTED"
    BIDIRECTIONAL = "BIDIRECTIONAL"


@dataclass(frozen=True)
class ProjectCreate:
    slug: str
    name: str
    project_type: ProjectType
    visibility: ProjectVisibility
    description: str = ""
    status: ProjectStatus = ProjectStatus.ACTIVE
    context_os_registered: bool = False
    context_os_project_id: str | None = None
    owner_notes: str = ""
    tags: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)
    source_key: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.project_type, ProjectType):
            raise ValidationError("project_type must be a ProjectType")
        if not isinstance(self.visibility, ProjectVisibility):
            raise ValidationError("visibility must be PUBLIC or PRIVATE")
        if not isinstance(self.status, ProjectStatus):
            raise ValidationError("status must be a ProjectStatus")


@dataclass(frozen=True)
class ProjectPatch:
    name: str | None = None
    description: str | None = None
    project_type: ProjectType | None = None
    status: ProjectStatus | None = None
    visibility: ProjectVisibility | None = None
    context_os_registered: bool | None = None
    context_os_project_id: str | None = None
    owner_notes: str | None = None
    tags: tuple[str, ...] | None = None
    provenance: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ProjectRecord:
    project_id: UUID
    slug: str
    name: str
    description: str
    project_type: ProjectType
    status: ProjectStatus
    visibility: ProjectVisibility
    context_os_registered: bool
    context_os_project_id: str | None
    owner_notes: str
    tags: tuple[str, ...]
    provenance: Mapping[str, Any]
    source_key: str | None
    version: int
    created_at: str
    updated_at: str
    archived_at: str | None


@dataclass(frozen=True)
class LocationUpsert:
    machine_id: str
    location_type: str
    path: str | None = None
    repository_root: str | None = None
    drive_folder_id: str | None = None
    drive_folder_url: str | None = None
    environment: str = ""
    discovery_status: str = "VERIFIED"
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LocationPatch:
    drive_folder_url: str | None = None
    environment: str | None = None
    discovery_status: str | None = None
    path: str | None = None
    repository_root: str | None = None
    drive_folder_id: str | None = None


@dataclass(frozen=True)
class LocationRecord:
    location_id: UUID
    project_id: UUID
    machine_id: str
    location_type: str
    original_path: str | None
    normalized_path: str | None
    repository_root: str | None
    drive_folder_id: str | None
    drive_folder_url: str | None
    environment: str
    version: int


@dataclass(frozen=True)
class ResourceUpsert:
    resource_type: str
    provider: str
    name: str
    external_id: str | None = None
    url: str | None = None
    environment: str = ""
    role: str = "USES"
    status: str = "ACTIVE"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResourcePatch:
    name: str | None = None
    url: str | None = None
    environment: str | None = None
    role: str | None = None
    status: str | None = None
    metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ResourceRecord:
    resource_id: UUID
    project_id: UUID
    resource_type: str
    provider: str
    external_id: str | None
    name: str
    url: str | None
    environment: str
    role: str
    status: str
    metadata: Mapping[str, Any]
    version: int


@dataclass(frozen=True)
class DeploymentUpsert:
    environment: DeploymentEnvironment
    external_deployment_id: str
    script_id: str | None = None
    deployment_url: str | None = None
    resource_id: UUID | None = None
    active_version: str | None = None
    status: str = "ACTIVE"
    notes: str = ""
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeploymentPatch:
    environment: DeploymentEnvironment | None = None
    script_id: str | None = None
    deployment_url: str | None = None
    resource_id: UUID | None = None
    active_version: str | None = None
    status: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class DeploymentRecord:
    deployment_id: UUID
    project_id: UUID
    resource_id: UUID | None
    environment: DeploymentEnvironment
    script_id: str | None
    external_deployment_id: str
    deployment_url: str | None
    active_version: str | None
    status: str
    version: int


@dataclass(frozen=True)
class ConnectionUpsert:
    connection_type: str
    implementation_method: str
    source_project_id: UUID | str | None = None
    source_resource_id: UUID | str | None = None
    target_project_id: UUID | str | None = None
    target_resource_id: UUID | str | None = None
    direction: ConnectionDirection = ConnectionDirection.DIRECTED
    purpose: str = ""
    notes: str = ""
    status: str = "ACTIVE"
    health_status: str = "UNKNOWN"
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConnectionPatch:
    connection_type: str | None = None
    implementation_method: str | None = None
    purpose: str | None = None
    notes: str | None = None
    status: str | None = None
    health_status: str | None = None


@dataclass(frozen=True)
class ConnectionRecord:
    connection_id: UUID
    source_project_id: UUID | None
    source_resource_id: UUID | None
    target_project_id: UUID | None
    target_resource_id: UUID | None
    connection_type: str
    direction: ConnectionDirection
    implementation_method: str
    purpose: str
    status: str
    version: int


@dataclass(frozen=True)
class ImpactReport:
    resource_id: UUID
    direct_project_ids: tuple[UUID, ...]
    related_project_ids: tuple[UUID, ...]
