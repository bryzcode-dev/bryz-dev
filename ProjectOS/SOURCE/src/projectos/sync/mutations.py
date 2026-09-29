from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from uuid import UUID

from projectos.database import ProjectOSDatabase
from projectos.errors import ValidationError
from projectos.google.types import UserCreate, UserPatch, UserRole
from projectos.repositories import (
    ConnectionRepository,
    DeploymentRepository,
    LocationRepository,
    ProjectRepository,
    ResourceRepository,
)
from projectos.types import (
    ConnectionPatch,
    ConnectionUpsert,
    DeploymentEnvironment,
    DeploymentPatch,
    DeploymentUpsert,
    LocationPatch,
    LocationUpsert,
    ProjectCreate,
    ProjectPatch,
    ProjectType,
    ProjectVisibility,
    ResourcePatch,
    ResourceUpsert,
)
from projectos.users import UserRepository

from .types import AuthorizationContext


@dataclass(frozen=True)
class MutationResult:
    entity_type: str
    entity_id: UUID
    version: int


class MutationRegistry:
    def __init__(self, database: ProjectOSDatabase, protected_owner_email: str):
        self.database = database
        self.projects = ProjectRepository(database)
        self.locations = LocationRepository(database)
        self.resources = ResourceRepository(database)
        self.deployments = DeploymentRepository(database)
        self.connections = ConnectionRepository(database)
        self.users = UserRepository(database, protected_owner_email)

    def current(self, entity_type: str, entity_id: UUID):
        repositories = {
            "project": self.projects,
            "location": self.locations,
            "resource": self.resources,
            "deployment": self.deployments,
            "connection": self.connections,
            "user": self.users,
        }
        repository = repositories.get(entity_type.lower())
        return repository.get(entity_id) if repository else None

    def visibility(self, entity_type: str, entity_id: UUID) -> ProjectVisibility | None:
        current = self.current(entity_type, entity_id)
        if current is None:
            return None
        if entity_type == "project":
            return current.visibility
        if entity_type in {"location", "resource", "deployment"}:
            return self.projects.get(current.project_id).visibility
        if entity_type == "connection":
            project_ids: list[UUID] = []
            for project_id in (current.source_project_id, current.target_project_id):
                if project_id:
                    project_ids.append(project_id)
            for resource_id in (current.source_resource_id, current.target_resource_id):
                if resource_id:
                    resource = self.resources.get(resource_id)
                    if resource:
                        project_ids.append(resource.project_id)
            if not project_ids:
                return None
            visibilities = {self.projects.get(project_id).visibility for project_id in project_ids}
            return next(iter(visibilities)) if len(visibilities) == 1 else None
        return None

    def apply(self, request: Any, context: AuthorizationContext) -> MutationResult:
        entity_type = request.entity_type.lower()
        operation = request.operation.upper()
        if operation == "CREATE":
            return self._create(entity_type, request.changes, context.email or "")
        if request.entity_id is None:
            raise ValidationError("entity_id is required")
        if operation == "UPDATE":
            return self._update(
                entity_type,
                request.entity_id,
                request.base_version,
                request.changes,
                context.email or "",
            )
        if operation == "ARCHIVE":
            return self._archive(
                entity_type, request.entity_id, request.base_version, context.email or ""
            )
        raise ValidationError("operation is unsupported")

    def _create(
        self, entity_type: str, changes: Mapping[str, Any], actor: str
    ) -> MutationResult:
        if entity_type == "project":
            record = self.projects.create(
                ProjectCreate(
                    slug=str(changes["slug"]),
                    name=str(changes["name"]),
                    project_type=ProjectType(str(changes["project_type"])),
                    visibility=ProjectVisibility(str(changes.get("visibility", "PUBLIC"))),
                    description=str(changes.get("description", "")),
                    tags=tuple(changes.get("tags", ())),
                ),
                actor,
            )
        elif entity_type == "location":
            project_id = UUID(str(changes["project_id"]))
            record = self.locations.upsert(
                project_id,
                LocationUpsert(
                    machine_id=str(changes["machine_id"]),
                    location_type=str(changes["location_type"]),
                    path=changes.get("path"),
                    repository_root=changes.get("repository_root"),
                    drive_folder_id=changes.get("drive_folder_id"),
                    drive_folder_url=changes.get("drive_folder_url"),
                    environment=str(changes.get("environment", "")),
                ),
                actor,
            )
        elif entity_type == "resource":
            project_id = UUID(str(changes["project_id"]))
            record = self.resources.upsert(
                project_id,
                ResourceUpsert(
                    resource_type=str(changes["resource_type"]),
                    provider=str(changes["provider"]),
                    name=str(changes["name"]),
                    external_id=changes.get("external_id"),
                    url=changes.get("url"),
                    environment=str(changes.get("environment", "")),
                    role=str(changes.get("role", "USES")),
                    status=str(changes.get("status", "ACTIVE")),
                    metadata=dict(changes.get("metadata", {})),
                ),
                actor,
            )
        elif entity_type == "deployment":
            project_id = UUID(str(changes["project_id"]))
            record = self.deployments.upsert(
                project_id,
                DeploymentUpsert(
                    environment=DeploymentEnvironment(str(changes["environment"])),
                    external_deployment_id=str(changes["external_deployment_id"]),
                    script_id=changes.get("script_id"),
                    deployment_url=changes.get("deployment_url"),
                    status=str(changes.get("status", "ACTIVE")),
                    notes=str(changes.get("notes", "")),
                ),
                actor,
            )
        elif entity_type == "connection":
            record = self.connections.upsert(
                ConnectionUpsert(
                    connection_type=str(changes["connection_type"]),
                    implementation_method=str(changes["implementation_method"]),
                    source_project_id=changes.get("source_project_id"),
                    source_resource_id=changes.get("source_resource_id"),
                    target_project_id=changes.get("target_project_id"),
                    target_resource_id=changes.get("target_resource_id"),
                    purpose=str(changes.get("purpose", "")),
                    notes=str(changes.get("notes", "")),
                ),
                actor,
            )
        elif entity_type == "user":
            record = self.users.create(
                UserCreate(
                    email=str(changes["email"]),
                    display_name=str(changes["display_name"]),
                    role=UserRole(str(changes["role"])),
                    notes=str(changes.get("notes", "")),
                ),
                actor,
            )
        else:
            raise ValidationError("entity type is unsupported")
        return MutationResult(entity_type, self._id(record), record.version)

    def _update(
        self,
        entity_type: str,
        entity_id: UUID,
        expected_version: int,
        changes: Mapping[str, Any],
        actor: str,
    ) -> MutationResult:
        if entity_type == "project":
            converted = dict(changes)
            if "project_type" in converted:
                converted["project_type"] = ProjectType(str(converted["project_type"]))
            if "visibility" in converted:
                converted["visibility"] = ProjectVisibility(str(converted["visibility"]))
            if "tags" in converted:
                converted["tags"] = tuple(converted["tags"])
            record = self.projects.update(entity_id, expected_version, ProjectPatch(**converted), actor)
        elif entity_type == "location":
            record = self.locations.update(entity_id, expected_version, LocationPatch(**changes), actor)
        elif entity_type == "resource":
            record = self.resources.update(entity_id, expected_version, ResourcePatch(**changes), actor)
        elif entity_type == "deployment":
            converted = dict(changes)
            if "environment" in converted:
                converted["environment"] = DeploymentEnvironment(str(converted["environment"]))
            if "resource_id" in converted:
                converted["resource_id"] = UUID(str(converted["resource_id"]))
            record = self.deployments.update(
                entity_id, expected_version, DeploymentPatch(**converted), actor
            )
        elif entity_type == "connection":
            record = self.connections.update(
                entity_id, expected_version, ConnectionPatch(**changes), actor
            )
        elif entity_type == "user":
            converted = dict(changes)
            if "role" in converted:
                converted["role"] = UserRole(str(converted["role"]))
            record = self.users.update(entity_id, expected_version, UserPatch(**converted), actor)
        else:
            raise ValidationError("entity type is unsupported")
        return MutationResult(entity_type, entity_id, record.version)

    def _archive(
        self, entity_type: str, entity_id: UUID, expected_version: int, actor: str
    ) -> MutationResult:
        repositories = {
            "project": self.projects,
            "location": self.locations,
            "resource": self.resources,
            "deployment": self.deployments,
            "connection": self.connections,
        }
        repository = repositories.get(entity_type)
        if repository is None:
            if entity_type == "user":
                record = self.users.deactivate(entity_id, expected_version, actor)
            else:
                raise ValidationError("entity type cannot be archived")
        else:
            record = repository.archive(entity_id, expected_version, actor)
        return MutationResult(entity_type, entity_id, record.version)

    @staticmethod
    def _id(record: Any) -> UUID:
        for name in (
            "project_id",
            "location_id",
            "resource_id",
            "deployment_id",
            "connection_id",
            "user_id",
        ):
            value = getattr(record, name, None)
            if value is not None:
                return value
        raise ValidationError("mutation result has no entity identifier")
