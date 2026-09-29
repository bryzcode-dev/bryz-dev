from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Protocol
from uuid import UUID, uuid4

from .audit import AuditLog
from .database import ProjectOSDatabase, utc_now
from .errors import ValidationError
from .repositories import LocationRepository, ProjectRepository, ResourceRepository
from .types import (
    LocationUpsert,
    ProjectCreate,
    ProjectStatus,
    ProjectType,
    ProjectVisibility,
    ResourceUpsert,
)
from .validation import canonical_json, reject_secret_material


@dataclass(frozen=True)
class DiscoveryFinding:
    finding_id: UUID
    finding_key: str
    entity_type: str
    proposed: Mapping[str, Any]
    evidence: tuple[Mapping[str, Any], ...]
    provenance: Mapping[str, Any]
    status: str = "CANDIDATE"
    content_hash: str = ""
    run_id: UUID | None = None
    created_at: str | None = None
    resolved_at: str | None = None
    resolution_reason: str | None = None

    @classmethod
    def new(
        cls,
        finding_key: str,
        entity_type: str,
        proposed: Mapping[str, Any],
        evidence: Iterable[Mapping[str, Any]],
        provenance: Mapping[str, Any],
        status: str = "CANDIDATE",
    ) -> "DiscoveryFinding":
        digest = hashlib.sha256(canonical_json(dict(proposed)).encode("utf-8")).hexdigest()
        return cls(
            finding_id=uuid4(),
            finding_key=finding_key,
            entity_type=entity_type,
            proposed=dict(proposed),
            evidence=tuple(dict(item) for item in evidence),
            provenance=dict(provenance),
            status=status,
            content_hash=digest,
        )


class DiscoveryAdapter(Protocol):
    name: str

    def scan(self) -> Iterable[DiscoveryFinding]: ...


@dataclass(frozen=True)
class DiscoveryRunResult:
    run_id: UUID
    created_count: int
    existing_count: int
    error_count: int
    findings: tuple[DiscoveryFinding, ...]


@dataclass(frozen=True)
class ApplyResult:
    finding_id: UUID
    project_id: UUID


class DiscoveryService:
    def __init__(self, database: ProjectOSDatabase, audit: AuditLog | None = None):
        self.database = database
        self.audit = audit or AuditLog()

    def run(self, adapter: DiscoveryAdapter, source_run_id: str) -> DiscoveryRunResult:
        findings = tuple(adapter.scan())
        for finding in findings:
            reject_secret_material(finding.proposed)
            reject_secret_material(finding.evidence)
            reject_secret_material(finding.provenance)

        run_id = uuid4()
        started = utc_now()
        stored: list[DiscoveryFinding] = []
        created_count = 0
        existing_count = 0
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO discovery_runs "
                "(run_id,adapter,source_run_id,status,started_at,summary_json) "
                "VALUES(?,?,?,?,?,?)",
                (str(run_id), adapter.name, source_run_id, "RUNNING", started, "{}"),
            )
            for finding in findings:
                existing = connection.execute(
                    "SELECT * FROM discovery_findings WHERE finding_key=? AND content_hash=?",
                    (finding.finding_key, finding.content_hash),
                ).fetchone()
                if existing:
                    existing_count += 1
                    stored.append(self._record(existing))
                    continue
                finding_id = str(finding.finding_id)
                connection.execute(
                    "INSERT INTO discovery_findings "
                    "(finding_id,run_id,finding_key,content_hash,entity_type,proposed_json,"
                    "evidence_json,provenance_json,status,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        finding_id,
                        str(run_id),
                        finding.finding_key,
                        finding.content_hash,
                        finding.entity_type,
                        canonical_json(dict(finding.proposed)),
                        canonical_json(list(finding.evidence)),
                        canonical_json(dict(finding.provenance)),
                        finding.status,
                        started,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM discovery_findings WHERE finding_id=?", (finding_id,)
                ).fetchone()
                stored.append(self._record(row))
                created_count += 1
            error_count = sum(item.status == "ERROR" for item in stored)
            summary = {
                "created_count": created_count,
                "existing_count": existing_count,
                "error_count": error_count,
            }
            connection.execute(
                "UPDATE discovery_runs SET status='COMPLETE',finished_at=?,summary_json=? "
                "WHERE run_id=?",
                (utc_now(), canonical_json(summary), str(run_id)),
            )
        return DiscoveryRunResult(
            run_id, created_count, existing_count, error_count, tuple(stored)
        )

    def get(self, finding_id: UUID) -> DiscoveryFinding | None:
        row = self.database.connection.execute(
            "SELECT * FROM discovery_findings WHERE finding_id=?", (str(finding_id),)
        ).fetchone()
        return self._record(row) if row else None

    def list(self, status: str | None = None) -> list[DiscoveryFinding]:
        if status:
            rows = self.database.connection.execute(
                "SELECT * FROM discovery_findings WHERE status=? ORDER BY created_at,finding_id",
                (status,),
            )
        else:
            rows = self.database.connection.execute(
                "SELECT * FROM discovery_findings ORDER BY created_at,finding_id"
            )
        return [self._record(row) for row in rows]

    def apply(self, finding_id: UUID, actor: str) -> ApplyResult:
        finding = self.get(finding_id)
        if finding is None:
            raise ValidationError("discovery finding does not exist")
        if finding.status != "CANDIDATE":
            raise ValidationError("only CANDIDATE findings can be applied")
        project_data = finding.proposed.get("project")
        if not isinstance(project_data, Mapping):
            raise ValidationError("finding does not contain a project proposal")

        with self.database.transaction() as connection:
            project = ProjectRepository(self.database).create(
                ProjectCreate(
                    slug=str(project_data["slug"]),
                    name=str(project_data["name"]),
                    description=str(project_data.get("description", "")),
                    project_type=ProjectType(str(project_data.get("project_type", "OTHER"))),
                    status=ProjectStatus(str(project_data.get("status", "ACTIVE"))),
                    visibility=ProjectVisibility(str(project_data.get("visibility", "PRIVATE"))),
                    context_os_registered=bool(
                        project_data.get("context_os_registered", False)
                    ),
                    context_os_project_id=project_data.get("context_os_project_id"),
                    tags=tuple(project_data.get("tags", ())),
                    provenance=finding.provenance,
                    source_key=project_data.get("source_key"),
                ),
                actor,
            )
            for location in finding.proposed.get("locations", ()):
                LocationRepository(self.database).upsert(
                    project.project_id,
                    LocationUpsert(
                        machine_id=str(location["machine_id"]),
                        location_type=str(location.get("location_type", "LOCAL")),
                        path=location.get("path"),
                        repository_root=location.get("repository_root"),
                        drive_folder_id=location.get("drive_folder_id"),
                        drive_folder_url=location.get("drive_folder_url"),
                        environment=str(location.get("environment", "")),
                        discovery_status="DISCOVERED",
                        provenance=finding.provenance,
                    ),
                    actor,
                )
            for resource in finding.proposed.get("resources", ()):
                ResourceRepository(self.database).upsert(
                    project.project_id,
                    ResourceUpsert(
                        resource_type=str(resource["resource_type"]),
                        provider=str(resource["provider"]),
                        name=str(resource["name"]),
                        external_id=resource.get("external_id"),
                        url=resource.get("url"),
                        environment=str(resource.get("environment", "")),
                        role=str(resource.get("role", "USES")),
                        metadata=resource.get("metadata", {}),
                        provenance=finding.provenance,
                    ),
                    actor,
                )
            resolved = utc_now()
            connection.execute(
                "UPDATE discovery_findings SET status='APPLIED',resolved_at=? WHERE finding_id=?",
                (resolved, str(finding_id)),
            )
            self.audit.append(
                connection,
                "discovery.applied",
                actor,
                "discovery_finding",
                str(finding_id),
                {"project_id": str(project.project_id)},
            )
        return ApplyResult(finding_id, project.project_id)

    def reject(self, finding_id: UUID, actor: str, reason: str) -> DiscoveryFinding:
        finding = self.get(finding_id)
        if finding is None:
            raise ValidationError("discovery finding does not exist")
        if finding.status != "CANDIDATE":
            raise ValidationError("only CANDIDATE findings can be rejected")
        if not reason.strip():
            raise ValidationError("rejection reason is required")
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE discovery_findings SET status='REJECTED',resolved_at=?,"
                "resolution_reason=? WHERE finding_id=?",
                (utc_now(), reason.strip(), str(finding_id)),
            )
            self.audit.append(
                connection,
                "discovery.rejected",
                actor,
                "discovery_finding",
                str(finding_id),
                {"reason": reason.strip()},
            )
        result = self.get(finding_id)
        assert result is not None
        return result

    @staticmethod
    def _record(row: sqlite3.Row) -> DiscoveryFinding:
        return DiscoveryFinding(
            finding_id=UUID(row["finding_id"]),
            run_id=UUID(row["run_id"]),
            finding_key=row["finding_key"],
            content_hash=row["content_hash"],
            entity_type=row["entity_type"],
            proposed=json.loads(row["proposed_json"]),
            evidence=tuple(json.loads(row["evidence_json"])),
            provenance=json.loads(row["provenance_json"]),
            status=row["status"],
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
            resolution_reason=row["resolution_reason"],
        )
