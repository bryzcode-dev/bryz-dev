from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from projectos.database import ProjectOSDatabase
from projectos.errors import ValidationError
from projectos.google.types import UserRole
from projectos.types import ConnectionRecord, ProjectRecord, ProjectVisibility, ResourceRecord
from projectos.users import UserRepository

from .types import (
    AuthorizationContext,
    Capability,
    OperationRequest,
    OwnerProjectFields,
    RoleSafeConnection,
    RoleSafeProject,
)


ROLE_CAPABILITIES: dict[UserRole, tuple[Capability, ...]] = {
    UserRole.OWNER: (
        Capability.VIEW_PUBLIC,
        Capability.EDIT_PUBLIC,
        Capability.VIEW_PRIVATE,
        Capability.EDIT_PRIVATE,
        Capability.MANAGE_USERS,
        Capability.RESOLVE_CONFLICTS,
        Capability.ADMIN_MENU,
    ),
    UserRole.ADMIN: (Capability.VIEW_PUBLIC, Capability.EDIT_PUBLIC),
    UserRole.USER: (Capability.VIEW_PUBLIC,),
}


@dataclass(frozen=True)
class FieldPolicy:
    admin_fields: frozenset[str]
    owner_fields: frozenset[str]


FIELD_POLICIES: dict[str, FieldPolicy] = {
    "project": FieldPolicy(
        frozenset({"name", "description", "status", "tags"}),
        frozenset(
            {
                "name",
                "description",
                "project_type",
                "status",
                "tags",
                "visibility",
                "context_os_registered",
                "context_os_project_id",
                "owner_notes",
            }
        ),
    ),
    "location": FieldPolicy(
        frozenset({"drive_folder_url", "environment", "discovery_status"}),
        frozenset(
            {
                "machine_id",
                "location_type",
                "path",
                "repository_root",
                "drive_folder_id",
                "drive_folder_url",
                "environment",
                "discovery_status",
            }
        ),
    ),
    "resource": FieldPolicy(
        frozenset({"name", "url", "environment", "role", "status", "metadata"}),
        frozenset(
            {
                "resource_type",
                "provider",
                "external_id",
                "name",
                "url",
                "environment",
                "role",
                "status",
                "metadata",
            }
        ),
    ),
    "deployment": FieldPolicy(
        frozenset({"environment", "deployment_url", "active_version", "status", "notes"}),
        frozenset(
            {
                "environment",
                "script_id",
                "external_deployment_id",
                "deployment_url",
                "active_version",
                "status",
                "notes",
                "resource_id",
            }
        ),
    ),
    "connection": FieldPolicy(
        frozenset({"connection_type", "implementation_method", "purpose", "notes", "status"}),
        frozenset(
            {
                "source_project_id",
                "source_resource_id",
                "target_project_id",
                "target_resource_id",
                "connection_type",
                "direction",
                "implementation_method",
                "purpose",
                "notes",
                "status",
                "health_status",
            }
        ),
    ),
    "user": FieldPolicy(frozenset(), frozenset({"email", "display_name", "role", "active", "notes"})),
}


class AuthorizationService:
    def __init__(self, database: ProjectOSDatabase, protected_owner_email: str):
        self.database = database
        self.users = UserRepository(database, protected_owner_email)

    def resolve(self, email: str | None) -> AuthorizationContext:
        if not email or not email.strip():
            return self._denied()
        try:
            user = self.users.get_by_email(email)
        except ValidationError:
            return self._denied()
        if user is None or not user.active:
            return self._denied()
        return AuthorizationContext(
            True,
            user.user_id,
            user.email,
            user.role,
            ROLE_CAPABILITIES[user.role],
        )

    @staticmethod
    def _denied() -> AuthorizationContext:
        return AuthorizationContext(False, None, None, None, ())

    def authorize_operation(
        self, context: AuthorizationContext, request: OperationRequest
    ) -> bool:
        if not context.authorized or context.role is None:
            return False
        policy = FIELD_POLICIES.get(request.entity_type.lower())
        if policy is None or request.operation not in {"CREATE", "UPDATE", "ARCHIVE"}:
            return False
        if context.role is UserRole.OWNER:
            return request.fields.issubset(policy.owner_fields)
        if context.role is not UserRole.ADMIN:
            return False
        return (
            request.visibility is ProjectVisibility.PUBLIC
            and request.entity_type.lower() != "user"
            and request.fields.issubset(policy.admin_fields)
        )

    def filter_entity(
        self, context: AuthorizationContext, entity: ProjectRecord | None
    ) -> RoleSafeProject | None:
        if entity is None or not self._can_view_project(context, entity):
            return None
        owner = None
        if context.role is UserRole.OWNER:
            owner = OwnerProjectFields(
                owner_notes=entity.owner_notes,
                context_os_registered=entity.context_os_registered,
                context_os_project_id=entity.context_os_project_id,
                slug=entity.slug,
            )
        return RoleSafeProject(
            project_id=entity.project_id,
            name=entity.name,
            description=entity.description,
            project_type=entity.project_type,
            status=entity.status,
            visibility=entity.visibility,
            tags=entity.tags,
            version=entity.version,
            updated_at=entity.updated_at,
            owner=owner,
        )

    @staticmethod
    def _can_view_project(context: AuthorizationContext, entity: ProjectRecord) -> bool:
        if not context.authorized:
            return False
        if entity.visibility is ProjectVisibility.PUBLIC:
            return Capability.VIEW_PUBLIC in context.capabilities
        return Capability.VIEW_PRIVATE in context.capabilities

    def filter_search(
        self,
        context: AuthorizationContext,
        entities: Iterable[ProjectRecord],
        query: str,
    ) -> tuple[RoleSafeProject, ...]:
        needle = query.casefold().strip()
        visible = [self.filter_entity(context, entity) for entity in entities]
        results = []
        for dto in visible:
            if dto is None:
                continue
            safe_text = " ".join(
                (dto.name, dto.description, dto.project_type.value, dto.status.value, *dto.tags)
            ).casefold()
            if not needle or needle in safe_text:
                results.append(dto)
        return tuple(results)

    def filter_counts(
        self, context: AuthorizationContext, entities: Iterable[ProjectRecord]
    ) -> dict[str, object]:
        by_status: dict[str, int] = {}
        total = 0
        for entity in entities:
            dto = self.filter_entity(context, entity)
            if dto is None:
                continue
            total += 1
            by_status[dto.status.value] = by_status.get(dto.status.value, 0) + 1
        return {"total": total, "by_status": dict(sorted(by_status.items()))}

    def filter_connections(
        self,
        context: AuthorizationContext,
        connections: Iterable[ConnectionRecord],
        projects: Iterable[ProjectRecord],
        resources: Iterable[ResourceRecord] = (),
    ) -> tuple[RoleSafeConnection, ...]:
        visible_ids = {
            project.project_id
            for project in projects
            if self.filter_entity(context, project) is not None
        }
        resource_projects = {resource.resource_id: resource.project_id for resource in resources}
        result: list[RoleSafeConnection] = []
        for connection in connections:
            project_endpoints = [
                item
                for item in (connection.source_project_id, connection.target_project_id)
                if item is not None
            ]
            for resource_id in (connection.source_resource_id, connection.target_resource_id):
                if resource_id is None:
                    continue
                parent_id = resource_projects.get(resource_id)
                if parent_id is None:
                    project_endpoints = []
                    break
                project_endpoints.append(parent_id)
            if not project_endpoints or any(item not in visible_ids for item in project_endpoints):
                continue
            result.append(
                RoleSafeConnection(
                    connection.connection_id,
                    connection.source_project_id,
                    connection.source_resource_id,
                    connection.target_project_id,
                    connection.target_resource_id,
                    connection.connection_type,
                    connection.direction.value,
                    connection.implementation_method,
                    connection.purpose,
                    connection.status,
                    connection.version,
                )
            )
        return tuple(result)

    def safe_not_found(
        self, context: AuthorizationContext, entity: object | None
    ) -> dict[str, str]:
        return {"code": "NOT_FOUND", "message": "Record not found"}
