from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping
from uuid import UUID, uuid4

from .audit import AuditLog
from .database import ProjectOSDatabase, utc_now
from .errors import ValidationError
from .repositories import ProjectRepository, ResourceRepository
from .validation import canonical_json, reject_secret_material, require_text


@dataclass(frozen=True)
class CredentialReferenceCreate:
    provider: str
    label: str
    credential_type: str
    purpose: str
    storage_system: str
    storage_reference: str
    owner_project_id: UUID | None = None
    scope_description: str = ""
    rotation_due_at: str | None = None
    status: str = "ACTIVE"
    notes: str = ""
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CredentialReferenceRecord:
    credential_id: UUID
    provider: str
    label: str
    credential_type: str
    purpose: str
    storage_system: str
    storage_reference: str
    owner_project_id: UUID | None
    version: int


@dataclass(frozen=True)
class CredentialUsageRecord:
    usage_id: UUID
    credential_id: UUID
    project_id: UUID
    resource_id: UUID | None
    purpose: str


@dataclass(frozen=True)
class CredentialImpactReport:
    credential_id: UUID
    project_ids: tuple[UUID, ...]
    resource_ids: tuple[UUID, ...]


class CredentialReferenceService:
    def __init__(self, database: ProjectOSDatabase, audit: AuditLog | None = None):
        self.database = database
        self.audit = audit or AuditLog()

    def create(self, command: CredentialReferenceCreate, actor: str) -> CredentialReferenceRecord:
        reject_secret_material(asdict(command))
        if command.owner_project_id and ProjectRepository(self.database).get(command.owner_project_id) is None:
            raise ValidationError("owner project does not exist")
        credential_id = str(uuid4())
        now = utc_now()
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    "INSERT INTO credential_references "
                    "(credential_id,provider,label,credential_type,purpose,scope_description,storage_system,"
                    "storage_reference,owner_project_id,rotation_due_at,status,notes,provenance_json,"
                    "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        credential_id,
                        require_text(command.provider, "provider"),
                        require_text(command.label, "label"),
                        require_text(command.credential_type, "credential_type"),
                        require_text(command.purpose, "purpose"),
                        command.scope_description,
                        require_text(command.storage_system, "storage_system"),
                        require_text(command.storage_reference, "storage_reference"),
                        str(command.owner_project_id) if command.owner_project_id else None,
                        command.rotation_due_at,
                        command.status,
                        command.notes,
                        canonical_json(dict(command.provenance)),
                        now,
                        now,
                    ),
                )
                self.audit.append(
                    connection,
                    "credential_reference.created",
                    actor,
                    "credential_reference",
                    credential_id,
                    {"provider": command.provider, "label": command.label},
                )
        except sqlite3.IntegrityError as exc:
            raise ValidationError("credential reference conflicts with an existing record") from exc
        return self.get(UUID(credential_id))

    def get(self, credential_id: UUID) -> CredentialReferenceRecord | None:
        row = self.database.connection.execute(
            "SELECT * FROM credential_references WHERE credential_id=?", (str(credential_id),)
        ).fetchone()
        if not row:
            return None
        return CredentialReferenceRecord(
            credential_id=UUID(row["credential_id"]),
            provider=row["provider"],
            label=row["label"],
            credential_type=row["credential_type"],
            purpose=row["purpose"],
            storage_system=row["storage_system"],
            storage_reference=row["storage_reference"],
            owner_project_id=UUID(row["owner_project_id"]) if row["owner_project_id"] else None,
            version=row["version"],
        )

    def link_usage(
        self,
        credential_id: UUID,
        project_id: UUID,
        resource_id: UUID | None,
        purpose: str,
        actor: str,
    ) -> CredentialUsageRecord:
        if self.get(credential_id) is None:
            raise ValidationError("credential reference does not exist")
        if ProjectRepository(self.database).get(project_id) is None:
            raise ValidationError("project does not exist")
        if resource_id:
            resource = ResourceRepository(self.database).get(resource_id)
            if resource is None or resource.project_id != project_id:
                raise ValidationError("resource does not belong to project")
        existing = self.database.connection.execute(
            "SELECT * FROM credential_usage WHERE credential_id=? AND project_id=? "
            "AND resource_id IS ? AND purpose=?",
            (str(credential_id), str(project_id), str(resource_id) if resource_id else None, purpose),
        ).fetchone()
        if existing:
            return self._usage(existing)
        usage_id = str(uuid4())
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO credential_usage "
                "(usage_id,credential_id,project_id,resource_id,purpose,created_at) VALUES(?,?,?,?,?,?)",
                (
                    usage_id,
                    str(credential_id),
                    str(project_id),
                    str(resource_id) if resource_id else None,
                    require_text(purpose, "purpose"),
                    utc_now(),
                ),
            )
            self.audit.append(
                connection,
                "credential_usage.linked",
                actor,
                "credential_reference",
                str(credential_id),
                {"project_id": str(project_id), "resource_id": str(resource_id) if resource_id else None},
            )
        row = self.database.connection.execute(
            "SELECT * FROM credential_usage WHERE usage_id=?", (usage_id,)
        ).fetchone()
        return self._usage(row)

    def impact(self, credential_id: UUID) -> CredentialImpactReport:
        if self.get(credential_id) is None:
            raise ValidationError("credential reference does not exist")
        rows = self.database.connection.execute(
            "SELECT project_id,resource_id FROM credential_usage WHERE credential_id=?",
            (str(credential_id),),
        )
        projects: set[UUID] = set()
        resources: set[UUID] = set()
        for row in rows:
            projects.add(UUID(row["project_id"]))
            if row["resource_id"]:
                resources.add(UUID(row["resource_id"]))
        return CredentialImpactReport(
            credential_id,
            tuple(sorted(projects, key=str)),
            tuple(sorted(resources, key=str)),
        )

    @staticmethod
    def _usage(row) -> CredentialUsageRecord:
        return CredentialUsageRecord(
            usage_id=UUID(row["usage_id"]),
            credential_id=UUID(row["credential_id"]),
            project_id=UUID(row["project_id"]),
            resource_id=UUID(row["resource_id"]) if row["resource_id"] else None,
            purpose=row["purpose"],
        )
