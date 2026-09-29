from __future__ import annotations

import json
import sqlite3
from dataclasses import fields
from uuid import UUID, uuid4

from .audit import AuditLog
from .database import ProjectOSDatabase, utc_now
from .errors import ValidationError, VersionConflict
from .types import (
    ConnectionDirection,
    ConnectionPatch,
    ConnectionRecord,
    ConnectionUpsert,
    DeploymentEnvironment,
    DeploymentPatch,
    DeploymentRecord,
    DeploymentUpsert,
    ImpactReport,
    LocationRecord,
    LocationPatch,
    LocationUpsert,
    ProjectCreate,
    ProjectPatch,
    ProjectRecord,
    ProjectStatus,
    ProjectType,
    ProjectVisibility,
    ResourceRecord,
    ResourcePatch,
    ResourceUpsert,
)
from .validation import canonical_json, normalize_path, require_text, validate_slug


class ProjectRepository:
    def __init__(self, database: ProjectOSDatabase, audit: AuditLog | None = None):
        self.database = database
        self.audit = audit or AuditLog()

    def create(self, command: ProjectCreate, actor: str) -> ProjectRecord:
        slug = validate_slug(command.slug)
        name = require_text(command.name, "name")
        if command.source_key:
            existing = self.database.connection.execute(
                "SELECT * FROM projects WHERE source_key=?", (command.source_key,)
            ).fetchone()
            if existing:
                record = self._record(existing)
                if self._matches_create(record, command, slug, name):
                    return record
                raise VersionConflict("source_key already identifies a different project state")

        project_id = str(uuid4())
        now = utc_now()
        values = (
            project_id,
            slug,
            name,
            command.description,
            command.project_type.value,
            command.status.value,
            command.visibility.value,
            int(command.context_os_registered),
            command.context_os_project_id,
            command.owner_notes,
            canonical_json(list(command.tags)),
            canonical_json(dict(command.provenance)),
            command.source_key,
            now,
            now,
        )
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    "INSERT INTO projects "
                    "(project_id,slug,name,description,project_type,status,visibility,"
                    "context_os_registered,context_os_project_id,owner_notes,tags_json,"
                    "provenance_json,source_key,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    values,
                )
                self.audit.append(
                    connection,
                    "project.created",
                    actor,
                    "project",
                    project_id,
                    {"slug": slug, "version": 1},
                )
        except sqlite3.IntegrityError as exc:
            raise ValidationError(f"project conflicts with an existing record: {exc}") from exc
        result = self.get(UUID(project_id))
        assert result is not None
        return result

    def get(self, project_id: UUID) -> ProjectRecord | None:
        row = self.database.connection.execute(
            "SELECT * FROM projects WHERE project_id=?", (str(project_id),)
        ).fetchone()
        return self._record(row) if row else None

    def list(self, include_archived: bool = False) -> list[ProjectRecord]:
        sql = "SELECT * FROM projects"
        parameters: tuple[str, ...] = ()
        if not include_archived:
            sql += " WHERE status != ?"
            parameters = (ProjectStatus.ARCHIVED.value,)
        sql += " ORDER BY name, project_id"
        return [self._record(row) for row in self.database.connection.execute(sql, parameters)]

    def update(
        self,
        project_id: UUID,
        expected_version: int,
        patch: ProjectPatch,
        actor: str,
    ) -> ProjectRecord:
        changes: dict[str, object] = {}
        for definition in fields(patch):
            value = getattr(patch, definition.name)
            if value is None:
                continue
            column = definition.name
            if isinstance(value, (ProjectType, ProjectStatus, ProjectVisibility)):
                changes[column] = value.value
            elif definition.name == "tags":
                changes["tags_json"] = canonical_json(list(value))
            elif definition.name == "provenance":
                changes["provenance_json"] = canonical_json(dict(value))
            elif definition.name == "context_os_registered":
                changes[column] = int(value)
            else:
                changes[column] = value
        if not changes:
            current = self.get(project_id)
            if current is None:
                raise ValidationError("project does not exist")
            return current
        if "name" in changes:
            changes["name"] = require_text(str(changes["name"]), "name")
        changes["updated_at"] = utc_now()
        changes["version"] = expected_version + 1
        assignments = ",".join(f"{column}=?" for column in changes)
        parameters = [*changes.values(), str(project_id), expected_version]
        with self.database.transaction() as connection:
            if "visibility" in changes:
                self._assert_connected_visibility(
                    connection, project_id, ProjectVisibility(str(changes["visibility"]))
                )
            cursor = connection.execute(
                f"UPDATE projects SET {assignments} WHERE project_id=? AND version=?",
                parameters,
            )
            if cursor.rowcount != 1:
                raise VersionConflict("project version is stale or project does not exist")
            self.audit.append(
                connection,
                "project.updated",
                actor,
                "project",
                str(project_id),
                {"changed_fields": sorted(changes), "version": expected_version + 1},
            )
        result = self.get(project_id)
        assert result is not None
        return result

    @staticmethod
    def _matches_create(
        record: ProjectRecord, command: ProjectCreate, slug: str, name: str
    ) -> bool:
        return (
            record.slug == slug
            and record.name == name
            and record.description == command.description
            and record.project_type == command.project_type
            and record.status == command.status
            and record.visibility == command.visibility
            and record.context_os_registered == command.context_os_registered
            and record.context_os_project_id == command.context_os_project_id
            and record.owner_notes == command.owner_notes
            and record.tags == tuple(command.tags)
            and dict(record.provenance) == dict(command.provenance)
        )

    @staticmethod
    def _assert_connected_visibility(
        connection: sqlite3.Connection,
        project_id: UUID,
        proposed_visibility: ProjectVisibility,
    ) -> None:
        project_text = str(project_id)
        rows = connection.execute(
            "SELECT COALESCE(c.source_project_id,sr.project_id) AS source_project_id,"
            "COALESCE(c.target_project_id,tr.project_id) AS target_project_id "
            "FROM connections c "
            "LEFT JOIN resources sr ON sr.resource_id=c.source_resource_id "
            "LEFT JOIN resources tr ON tr.resource_id=c.target_resource_id "
            "WHERE COALESCE(c.source_project_id,sr.project_id)=? "
            "OR COALESCE(c.target_project_id,tr.project_id)=?",
            (project_text, project_text),
        )
        for row in rows:
            other_id = (
                row["target_project_id"]
                if row["source_project_id"] == project_text
                else row["source_project_id"]
            )
            if other_id is None or other_id == project_text:
                continue
            other = connection.execute(
                "SELECT visibility FROM projects WHERE project_id=?", (other_id,)
            ).fetchone()
            if other and ProjectVisibility(other["visibility"]) != proposed_visibility:
                raise ValidationError(
                    "project visibility would broaden an existing private connection"
                )

    def archive(self, project_id: UUID, expected_version: int, actor: str) -> ProjectRecord:
        now = utc_now()
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE projects SET status=?, archived_at=?, updated_at=?, version=? "
                "WHERE project_id=? AND version=?",
                (
                    ProjectStatus.ARCHIVED.value,
                    now,
                    now,
                    expected_version + 1,
                    str(project_id),
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise VersionConflict("project version is stale or project does not exist")
            self.audit.append(
                connection,
                "project.archived",
                actor,
                "project",
                str(project_id),
                {"version": expected_version + 1},
            )
        result = self.get(project_id)
        assert result is not None
        return result

    @staticmethod
    def _record(row: sqlite3.Row) -> ProjectRecord:
        return ProjectRecord(
            project_id=UUID(row["project_id"]),
            slug=row["slug"],
            name=row["name"],
            description=row["description"],
            project_type=ProjectType(row["project_type"]),
            status=ProjectStatus(row["status"]),
            visibility=ProjectVisibility(row["visibility"]),
            context_os_registered=bool(row["context_os_registered"]),
            context_os_project_id=row["context_os_project_id"],
            owner_notes=row["owner_notes"],
            tags=tuple(json.loads(row["tags_json"])),
            provenance=json.loads(row["provenance_json"]),
            source_key=row["source_key"],
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            archived_at=row["archived_at"],
        )


def _uuid(value: object | None) -> UUID | None:
    return UUID(str(value)) if value is not None else None


class LocationRepository:
    def __init__(self, database: ProjectOSDatabase, audit: AuditLog | None = None):
        self.database = database
        self.audit = audit or AuditLog()

    def upsert(self, project_id: UUID, command: LocationUpsert, actor: str) -> LocationRecord:
        if ProjectRepository(self.database).get(project_id) is None:
            raise ValidationError("project does not exist")
        machine_id = require_text(command.machine_id, "machine_id")
        location_type = require_text(command.location_type, "location_type")
        normalized = normalize_path(command.path) if command.path else None
        existing = self.database.connection.execute(
            "SELECT * FROM project_locations WHERE project_id=? AND machine_id=? "
            "AND location_type=? AND normalized_path IS ? AND drive_folder_id IS ?",
            (str(project_id), machine_id, location_type, normalized, command.drive_folder_id),
        ).fetchone()
        if existing:
            return self._record(existing)
        location_id = str(uuid4())
        now = utc_now()
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO project_locations "
                "(location_id,project_id,machine_id,original_path,normalized_path,repository_root,"
                "drive_folder_id,drive_folder_url,location_type,environment,discovery_status,"
                "provenance_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    location_id,
                    str(project_id),
                    machine_id,
                    command.path,
                    normalized,
                    command.repository_root,
                    command.drive_folder_id,
                    command.drive_folder_url,
                    location_type,
                    command.environment,
                    command.discovery_status,
                    canonical_json(dict(command.provenance)),
                    now,
                    now,
                ),
            )
            self.audit.append(connection, "location.created", actor, "location", location_id, {})
        return self.get(UUID(location_id))

    def get(self, location_id: UUID) -> LocationRecord | None:
        row = self.database.connection.execute(
            "SELECT * FROM project_locations WHERE location_id=?", (str(location_id),)
        ).fetchone()
        return self._record(row) if row else None

    def list(self, project_id: UUID) -> list[LocationRecord]:
        return [
            self._record(row)
            for row in self.database.connection.execute(
                "SELECT * FROM project_locations WHERE project_id=? ORDER BY machine_id,location_id",
                (str(project_id),),
            )
        ]

    def update(
        self, location_id: UUID, expected_version: int, patch: LocationPatch, actor: str
    ) -> LocationRecord:
        current = self.get(location_id)
        if current is None:
            raise ValidationError("location does not exist")
        if current.version != expected_version:
            raise VersionConflict("location version conflict")
        values = {
            "drive_folder_url": patch.drive_folder_url,
            "environment": patch.environment,
            "discovery_status": patch.discovery_status,
            "original_path": patch.path,
            "normalized_path": normalize_path(patch.path) if patch.path is not None else None,
            "repository_root": patch.repository_root,
            "drive_folder_id": patch.drive_folder_id,
        }
        changes = {key: value for key, value in values.items() if value is not None}
        if not changes:
            return current
        changes.update({"updated_at": utc_now(), "version": expected_version + 1})
        with self.database.transaction() as connection:
            assignments = ",".join(f"{key}=?" for key in changes)
            cursor = connection.execute(
                f"UPDATE project_locations SET {assignments} WHERE location_id=? AND version=?",
                (*changes.values(), str(location_id), expected_version),
            )
            if cursor.rowcount != 1:
                raise VersionConflict("location version conflict")
            self.audit.append(connection, "location.updated", actor, "location", str(location_id), {})
        return self.get(location_id)

    def archive(self, location_id: UUID, expected_version: int, actor: str) -> LocationRecord:
        return self.update(
            location_id, expected_version, LocationPatch(discovery_status="ARCHIVED"), actor
        )

    @staticmethod
    def _record(row: sqlite3.Row) -> LocationRecord:
        return LocationRecord(
            location_id=UUID(row["location_id"]),
            project_id=UUID(row["project_id"]),
            machine_id=row["machine_id"],
            location_type=row["location_type"],
            original_path=row["original_path"],
            normalized_path=row["normalized_path"],
            repository_root=row["repository_root"],
            drive_folder_id=row["drive_folder_id"],
            drive_folder_url=row["drive_folder_url"],
            environment=row["environment"],
            version=row["version"],
        )


class ResourceRepository:
    def __init__(self, database: ProjectOSDatabase, audit: AuditLog | None = None):
        self.database = database
        self.audit = audit or AuditLog()

    def upsert(self, project_id: UUID, command: ResourceUpsert, actor: str) -> ResourceRecord:
        if ProjectRepository(self.database).get(project_id) is None:
            raise ValidationError("project does not exist")
        resource_type = require_text(command.resource_type, "resource_type")
        provider = require_text(command.provider, "provider")
        name = require_text(command.name, "name")
        existing = self.database.connection.execute(
            "SELECT * FROM resources WHERE project_id=? AND provider=? AND resource_type=? "
            "AND external_id IS ?",
            (str(project_id), provider, resource_type, command.external_id),
        ).fetchone()
        now = utc_now()
        if existing:
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE resources SET name=?,url=?,environment=?,role=?,status=?,metadata_json=?,"
                    "provenance_json=?,version=version+1,updated_at=? WHERE resource_id=?",
                    (
                        name,
                        command.url,
                        command.environment,
                        command.role,
                        command.status,
                        canonical_json(dict(command.metadata)),
                        canonical_json(dict(command.provenance)),
                        now,
                        existing["resource_id"],
                    ),
                )
                self.audit.append(
                    connection, "resource.updated", actor, "resource", existing["resource_id"], {}
                )
            return self.get(UUID(existing["resource_id"]))
        resource_id = str(uuid4())
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO resources "
                "(resource_id,project_id,resource_type,provider,external_id,name,url,environment,role,"
                "status,metadata_json,provenance_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    resource_id,
                    str(project_id),
                    resource_type,
                    provider,
                    command.external_id,
                    name,
                    command.url,
                    command.environment,
                    command.role,
                    command.status,
                    canonical_json(dict(command.metadata)),
                    canonical_json(dict(command.provenance)),
                    now,
                    now,
                ),
            )
            self.audit.append(connection, "resource.created", actor, "resource", resource_id, {})
        return self.get(UUID(resource_id))

    def get(self, resource_id: UUID) -> ResourceRecord | None:
        row = self.database.connection.execute(
            "SELECT * FROM resources WHERE resource_id=?", (str(resource_id),)
        ).fetchone()
        return self._record(row) if row else None

    def list(self, project_id: UUID) -> list[ResourceRecord]:
        return [
            self._record(row)
            for row in self.database.connection.execute(
                "SELECT * FROM resources WHERE project_id=? ORDER BY name,resource_id",
                (str(project_id),),
            )
        ]

    def update(
        self, resource_id: UUID, expected_version: int, patch: ResourcePatch, actor: str
    ) -> ResourceRecord:
        current = self.get(resource_id)
        if current is None:
            raise ValidationError("resource does not exist")
        if current.version != expected_version:
            raise VersionConflict("resource version conflict")
        values = {
            "name": require_text(patch.name, "name") if patch.name is not None else None,
            "url": patch.url,
            "environment": patch.environment,
            "role": patch.role,
            "status": patch.status,
            "metadata_json": canonical_json(dict(patch.metadata)) if patch.metadata is not None else None,
        }
        changes = {key: value for key, value in values.items() if value is not None}
        if not changes:
            return current
        changes.update({"updated_at": utc_now(), "version": expected_version + 1})
        with self.database.transaction() as connection:
            assignments = ",".join(f"{key}=?" for key in changes)
            cursor = connection.execute(
                f"UPDATE resources SET {assignments} WHERE resource_id=? AND version=?",
                (*changes.values(), str(resource_id), expected_version),
            )
            if cursor.rowcount != 1:
                raise VersionConflict("resource version conflict")
            self.audit.append(connection, "resource.updated", actor, "resource", str(resource_id), {})
        return self.get(resource_id)

    def archive(self, resource_id: UUID, expected_version: int, actor: str) -> ResourceRecord:
        return self.update(resource_id, expected_version, ResourcePatch(status="ARCHIVED"), actor)

    @staticmethod
    def _record(row: sqlite3.Row) -> ResourceRecord:
        return ResourceRecord(
            resource_id=UUID(row["resource_id"]),
            project_id=UUID(row["project_id"]),
            resource_type=row["resource_type"],
            provider=row["provider"],
            external_id=row["external_id"],
            name=row["name"],
            url=row["url"],
            environment=row["environment"],
            role=row["role"],
            status=row["status"],
            metadata=json.loads(row["metadata_json"]),
            version=row["version"],
        )


class DeploymentRepository:
    def __init__(self, database: ProjectOSDatabase, audit: AuditLog | None = None):
        self.database = database
        self.audit = audit or AuditLog()

    def upsert(self, project_id: UUID, command: DeploymentUpsert, actor: str) -> DeploymentRecord:
        if ProjectRepository(self.database).get(project_id) is None:
            raise ValidationError("project does not exist")
        if not isinstance(command.environment, DeploymentEnvironment):
            raise ValidationError("environment is invalid")
        if command.resource_id and ResourceRepository(self.database).get(command.resource_id) is None:
            raise ValidationError("resource does not exist")
        existing = self.database.connection.execute(
            "SELECT * FROM deployments WHERE project_id=? AND environment=? "
            "AND external_deployment_id=?",
            (str(project_id), command.environment.value, command.external_deployment_id),
        ).fetchone()
        now = utc_now()
        if existing:
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE deployments SET resource_id=?,script_id=?,deployment_url=?,active_version=?,"
                    "status=?,notes=?,provenance_json=?,version=version+1,updated_at=? WHERE deployment_id=?",
                    (
                        str(command.resource_id) if command.resource_id else None,
                        command.script_id,
                        command.deployment_url,
                        command.active_version,
                        command.status,
                        command.notes,
                        canonical_json(dict(command.provenance)),
                        now,
                        existing["deployment_id"],
                    ),
                )
                self.audit.append(
                    connection, "deployment.updated", actor, "deployment", existing["deployment_id"], {}
                )
            return self.get(UUID(existing["deployment_id"]))
        deployment_id = str(uuid4())
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO deployments "
                "(deployment_id,project_id,resource_id,environment,script_id,external_deployment_id,"
                "deployment_url,active_version,status,notes,provenance_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    deployment_id,
                    str(project_id),
                    str(command.resource_id) if command.resource_id else None,
                    command.environment.value,
                    command.script_id,
                    require_text(command.external_deployment_id, "external_deployment_id"),
                    command.deployment_url,
                    command.active_version,
                    command.status,
                    command.notes,
                    canonical_json(dict(command.provenance)),
                    now,
                    now,
                ),
            )
            self.audit.append(connection, "deployment.created", actor, "deployment", deployment_id, {})
        return self.get(UUID(deployment_id))

    def get(self, deployment_id: UUID) -> DeploymentRecord | None:
        row = self.database.connection.execute(
            "SELECT * FROM deployments WHERE deployment_id=?", (str(deployment_id),)
        ).fetchone()
        return self._record(row) if row else None

    def list(self, project_id: UUID) -> list[DeploymentRecord]:
        return [
            self._record(row)
            for row in self.database.connection.execute(
                "SELECT * FROM deployments WHERE project_id=? ORDER BY environment,deployment_id",
                (str(project_id),),
            )
        ]

    def update(
        self, deployment_id: UUID, expected_version: int, patch: DeploymentPatch, actor: str
    ) -> DeploymentRecord:
        current = self.get(deployment_id)
        if current is None:
            raise ValidationError("deployment does not exist")
        if current.version != expected_version:
            raise VersionConflict("deployment version conflict")
        if patch.resource_id and ResourceRepository(self.database).get(patch.resource_id) is None:
            raise ValidationError("resource does not exist")
        values = {
            "environment": patch.environment.value if patch.environment is not None else None,
            "script_id": patch.script_id,
            "deployment_url": patch.deployment_url,
            "resource_id": str(patch.resource_id) if patch.resource_id is not None else None,
            "active_version": patch.active_version,
            "status": patch.status,
            "notes": patch.notes,
        }
        changes = {key: value for key, value in values.items() if value is not None}
        if not changes:
            return current
        changes.update({"updated_at": utc_now(), "version": expected_version + 1})
        with self.database.transaction() as connection:
            assignments = ",".join(f"{key}=?" for key in changes)
            cursor = connection.execute(
                f"UPDATE deployments SET {assignments} WHERE deployment_id=? AND version=?",
                (*changes.values(), str(deployment_id), expected_version),
            )
            if cursor.rowcount != 1:
                raise VersionConflict("deployment version conflict")
            self.audit.append(
                connection, "deployment.updated", actor, "deployment", str(deployment_id), {}
            )
        return self.get(deployment_id)

    def archive(self, deployment_id: UUID, expected_version: int, actor: str) -> DeploymentRecord:
        return self.update(deployment_id, expected_version, DeploymentPatch(status="ARCHIVED"), actor)

    @staticmethod
    def _record(row: sqlite3.Row) -> DeploymentRecord:
        return DeploymentRecord(
            deployment_id=UUID(row["deployment_id"]),
            project_id=UUID(row["project_id"]),
            resource_id=_uuid(row["resource_id"]),
            environment=DeploymentEnvironment(row["environment"]),
            script_id=row["script_id"],
            external_deployment_id=row["external_deployment_id"],
            deployment_url=row["deployment_url"],
            active_version=row["active_version"],
            status=row["status"],
            version=row["version"],
        )


class ConnectionRepository:
    def __init__(self, database: ProjectOSDatabase, audit: AuditLog | None = None):
        self.database = database
        self.audit = audit or AuditLog()

    def upsert(self, command: ConnectionUpsert, actor: str) -> ConnectionRecord:
        endpoint_projects = self._endpoint_projects(command)
        if not endpoint_projects:
            raise ValidationError("connection endpoints do not exist")
        visibilities = {
            ProjectRepository(self.database).get(project_id).visibility for project_id in endpoint_projects
        }
        if len(visibilities) > 1:
            raise ValidationError("connection cannot cross PUBLIC and PRIVATE project visibility")
        connection_id = str(uuid4())
        now = utc_now()
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO connections "
                "(connection_id,source_project_id,source_resource_id,target_project_id,target_resource_id,"
                "connection_type,direction,implementation_method,purpose,notes,status,health_status,"
                "provenance_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    connection_id,
                    self._text(command.source_project_id),
                    self._text(command.source_resource_id),
                    self._text(command.target_project_id),
                    self._text(command.target_resource_id),
                    require_text(command.connection_type, "connection_type"),
                    command.direction.value,
                    require_text(command.implementation_method, "implementation_method"),
                    command.purpose,
                    command.notes,
                    command.status,
                    command.health_status,
                    canonical_json(dict(command.provenance)),
                    now,
                    now,
                ),
            )
            self.audit.append(connection, "connection.created", actor, "connection", connection_id, {})
        return self.get(UUID(connection_id))

    def _endpoint_projects(self, command: ConnectionUpsert) -> set[UUID]:
        projects: set[UUID] = set()
        project_repository = ProjectRepository(self.database)
        resource_repository = ResourceRepository(self.database)
        for value in (command.source_project_id, command.target_project_id):
            if value is None:
                continue
            project_id = UUID(str(value))
            if project_repository.get(project_id) is None:
                raise ValidationError("project endpoint does not exist")
            projects.add(project_id)
        for value in (command.source_resource_id, command.target_resource_id):
            if value is None:
                continue
            resource = resource_repository.get(UUID(str(value)))
            if resource is None:
                raise ValidationError("resource endpoint does not exist")
            projects.add(resource.project_id)
        return projects

    def get(self, connection_id: UUID) -> ConnectionRecord | None:
        row = self.database.connection.execute(
            "SELECT * FROM connections WHERE connection_id=?", (str(connection_id),)
        ).fetchone()
        return self._record(row) if row else None

    def list(self, project_id: UUID) -> list[ConnectionRecord]:
        rows = self.database.connection.execute(
            "SELECT DISTINCT c.* FROM connections c "
            "LEFT JOIN resources sr ON sr.resource_id=c.source_resource_id "
            "LEFT JOIN resources tr ON tr.resource_id=c.target_resource_id "
            "WHERE c.source_project_id=? OR c.target_project_id=? OR sr.project_id=? OR tr.project_id=? "
            "ORDER BY c.connection_id",
            (str(project_id),) * 4,
        )
        return [self._record(row) for row in rows]

    def update(
        self, connection_id: UUID, expected_version: int, patch: ConnectionPatch, actor: str
    ) -> ConnectionRecord:
        current = self.get(connection_id)
        if current is None:
            raise ValidationError("connection does not exist")
        if current.version != expected_version:
            raise VersionConflict("connection version conflict")
        values = {
            "connection_type": require_text(patch.connection_type, "connection_type")
            if patch.connection_type is not None
            else None,
            "implementation_method": require_text(
                patch.implementation_method, "implementation_method"
            )
            if patch.implementation_method is not None
            else None,
            "purpose": patch.purpose,
            "notes": patch.notes,
            "status": patch.status,
            "health_status": patch.health_status,
        }
        changes = {key: value for key, value in values.items() if value is not None}
        if not changes:
            return current
        changes.update({"updated_at": utc_now(), "version": expected_version + 1})
        with self.database.transaction() as connection:
            assignments = ",".join(f"{key}=?" for key in changes)
            cursor = connection.execute(
                f"UPDATE connections SET {assignments} WHERE connection_id=? AND version=?",
                (*changes.values(), str(connection_id), expected_version),
            )
            if cursor.rowcount != 1:
                raise VersionConflict("connection version conflict")
            self.audit.append(
                connection, "connection.updated", actor, "connection", str(connection_id), {}
            )
        return self.get(connection_id)

    def archive(self, connection_id: UUID, expected_version: int, actor: str) -> ConnectionRecord:
        return self.update(connection_id, expected_version, ConnectionPatch(status="ARCHIVED"), actor)

    def impact(self, resource_id: UUID) -> ImpactReport:
        resource = ResourceRepository(self.database).get(resource_id)
        if resource is None:
            raise ValidationError("resource does not exist")
        related: set[UUID] = set()
        rows = self.database.connection.execute(
            "SELECT * FROM connections WHERE source_resource_id=? OR target_resource_id=?",
            (str(resource_id), str(resource_id)),
        )
        for row in rows:
            for column in ("source_project_id", "target_project_id"):
                if row[column]:
                    related.add(UUID(row[column]))
            other_resource = row["target_resource_id"] if row["source_resource_id"] == str(resource_id) else row["source_resource_id"]
            if other_resource:
                other = ResourceRepository(self.database).get(UUID(other_resource))
                if other:
                    related.add(other.project_id)
        related.discard(resource.project_id)
        return ImpactReport(resource_id, (resource.project_id,), tuple(sorted(related, key=str)))

    @staticmethod
    def _text(value: UUID | str | None) -> str | None:
        return str(value) if value is not None else None

    @staticmethod
    def _record(row: sqlite3.Row) -> ConnectionRecord:
        return ConnectionRecord(
            connection_id=UUID(row["connection_id"]),
            source_project_id=_uuid(row["source_project_id"]),
            source_resource_id=_uuid(row["source_resource_id"]),
            target_project_id=_uuid(row["target_project_id"]),
            target_resource_id=_uuid(row["target_resource_id"]),
            connection_type=row["connection_type"],
            direction=ConnectionDirection(row["direction"]),
            implementation_method=row["implementation_method"],
            purpose=row["purpose"],
            status=row["status"],
            version=row["version"],
        )
