from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from projectos.google.types import UserRole
from projectos.types import ProjectStatus, ProjectType, ProjectVisibility


class Capability(StrEnum):
    VIEW_PUBLIC = "VIEW_PUBLIC"
    EDIT_PUBLIC = "EDIT_PUBLIC"
    VIEW_PRIVATE = "VIEW_PRIVATE"
    EDIT_PRIVATE = "EDIT_PRIVATE"
    MANAGE_USERS = "MANAGE_USERS"
    RESOLVE_CONFLICTS = "RESOLVE_CONFLICTS"
    ADMIN_MENU = "ADMIN_MENU"


@dataclass(frozen=True)
class AuthorizationContext:
    authorized: bool
    user_id: UUID | None
    email: str | None
    role: UserRole | None
    capabilities: tuple[Capability, ...]


@dataclass(frozen=True)
class OperationRequest:
    entity_type: str
    operation: str
    visibility: ProjectVisibility | None
    fields: frozenset[str]


@dataclass(frozen=True)
class OwnerProjectFields:
    owner_notes: str
    context_os_registered: bool
    context_os_project_id: str | None
    slug: str


@dataclass(frozen=True)
class RoleSafeProject:
    project_id: UUID
    name: str
    description: str
    project_type: ProjectType
    status: ProjectStatus
    visibility: ProjectVisibility
    tags: tuple[str, ...]
    version: int
    updated_at: str
    owner: OwnerProjectFields | None = None


@dataclass(frozen=True)
class RoleSafeConnection:
    connection_id: UUID
    source_project_id: UUID | None
    source_resource_id: UUID | None
    target_project_id: UUID | None
    target_resource_id: UUID | None
    connection_type: str
    direction: str
    implementation_method: str
    purpose: str
    status: str
    version: int
