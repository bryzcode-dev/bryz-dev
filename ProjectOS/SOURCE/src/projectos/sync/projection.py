from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Iterable, Mapping
from uuid import UUID

from projectos.database import ProjectOSDatabase, utc_now
from projectos.google.contract import WorkbookContract, canonical_json_bytes
from projectos.google.gateway import GoogleGateway, PublicationReceipt
from projectos.google.types import GoogleBindingRecord

from .requests import RequestResult, RequestResultCode


@dataclass(frozen=True)
class ProjectionBundle:
    revision_id: UUID
    schema_version: int
    tabs: Mapping[str, tuple[Mapping[str, Any], ...]]
    public_tabs: Mapping[str, tuple[Mapping[str, Any], ...]]
    row_counts: Mapping[str, int]
    tab_hashes: Mapping[str, str]
    snapshot_hash: str

    def gateway_payload(self) -> dict[str, Any]:
        return {
            "revision_id": str(self.revision_id),
            "schema_version": self.schema_version,
            "snapshot_hash": self.snapshot_hash,
            "tabs": {name: [dict(row) for row in rows] for name, rows in self.tabs.items()},
        }


class ProjectionBuilder:
    def build(self, connection: sqlite3.Connection, revision_id: UUID) -> ProjectionBundle:
        owns_transaction = not connection.in_transaction
        if owns_transaction:
            connection.execute("BEGIN")
        try:
            contract = WorkbookContract.current()
            raw_tabs = self._read_tabs(connection)
            tabs: dict[str, tuple[Mapping[str, Any], ...]] = {}
            for tab in contract.tabs:
                rows = raw_tabs.get(tab.name, [])
                projected = [self._contract_row(tab.headers, row, revision_id) for row in rows]
                id_column = self._id_column(tab.headers)
                if id_column:
                    projected.sort(key=lambda row: str(row.get(id_column, "")))
                tabs[tab.name] = tuple(MappingProxyType(row) for row in projected)
            public_tabs = self._public_tabs(tabs)
            row_counts = {name: len(rows) for name, rows in tabs.items()}
            tab_hashes = {
                name: hashlib.sha256(
                    canonical_json_bytes([dict(row) for row in rows])
                ).hexdigest()
                for name, rows in tabs.items()
            }
            snapshot_hash = hashlib.sha256(
                canonical_json_bytes(
                    {
                        "revision_id": str(revision_id),
                        "row_counts": row_counts,
                        "tab_hashes": tab_hashes,
                    }
                )
            ).hexdigest()
            result = ProjectionBundle(
                revision_id,
                contract.version,
                MappingProxyType(tabs),
                MappingProxyType(public_tabs),
                MappingProxyType(row_counts),
                MappingProxyType(tab_hashes),
                snapshot_hash,
            )
            if owns_transaction:
                connection.execute("COMMIT")
            return result
        except BaseException:
            if owns_transaction and connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

    @staticmethod
    def _read_tabs(connection: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
        return {
            "Projects": [
                {
                    "project_id": row["project_id"],
                    "version": row["version"],
                    "status": row["status"],
                    "visibility": row["visibility"],
                    "name": row["name"],
                    "description": row["description"],
                    "project_type": row["project_type"],
                    "tags": row["tags_json"],
                    "updated_at": row["updated_at"],
                }
                for row in connection.execute("SELECT * FROM projects")
            ],
            "Locations": [dict(row) for row in connection.execute("SELECT * FROM project_locations")],
            "Resources": [dict(row) for row in connection.execute("SELECT * FROM resources")],
            "Deployments": [dict(row) for row in connection.execute("SELECT * FROM deployments")],
            "Connections": [dict(row) for row in connection.execute("SELECT * FROM connections")],
            "Users": [
                {
                    "user_id": row["user_id"],
                    "email": row["email"],
                    "display_name": row["display_name"],
                    "role": row["role"],
                    "active": bool(row["active"]),
                    "added_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "last_access_at": row["last_access_at"],
                    "notes": row["notes"],
                    "version": row["version"],
                }
                for row in connection.execute("SELECT * FROM users")
            ],
            "Credential_References": [
                dict(row) for row in connection.execute("SELECT * FROM credential_references")
            ],
            "Looker_Assets": [dict(row) for row in connection.execute("SELECT * FROM looker_assets")],
            "Looker_Relationships": [dict(row) for row in connection.execute("SELECT * FROM looker_relationships")],
            "Looker_Findings": [dict(row) for row in connection.execute("SELECT * FROM looker_findings")],
            "Looker_Analytics": [dict(row) for row in connection.execute("SELECT * FROM looker_analytics")],
            "Conflicts": [dict(row) for row in connection.execute("SELECT * FROM conflicts")],
            "Audit_Summary": [dict(row) for row in connection.execute("SELECT * FROM audit_events")],
        }

    @staticmethod
    def _contract_row(
        headers: tuple[str, ...], raw: Mapping[str, Any], revision_id: UUID
    ) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for header in headers:
            if header == "projection_revision":
                values[header] = str(revision_id)
            elif header == "metadata_json" and "metadata_json" in raw:
                values[header] = raw[header]
            elif header != "row_hash":
                values[header] = raw.get(header, "")
        if "row_hash" in headers:
            values["row_hash"] = hashlib.sha256(canonical_json_bytes(values)).hexdigest()
        return values

    @staticmethod
    def _id_column(headers: tuple[str, ...]) -> str | None:
        for header in headers:
            if header.endswith("_id") and header not in {
                "project_id",
                "source_project_id",
                "target_project_id",
                "source_resource_id",
                "target_resource_id",
            }:
                return header
        if "project_id" in headers:
            return "project_id"
        return None

    @staticmethod
    def _public_tabs(
        tabs: Mapping[str, tuple[Mapping[str, Any], ...]]
    ) -> dict[str, tuple[Mapping[str, Any], ...]]:
        public_projects = {
            row["project_id"]
            for row in tabs.get("Projects", ())
            if row.get("visibility") == "PUBLIC"
        }
        result: dict[str, tuple[Mapping[str, Any], ...]] = {
            "Projects": tuple(
                row for row in tabs.get("Projects", ()) if row.get("project_id") in public_projects
            )
        }
        for name in ("Locations", "Resources", "Deployments"):
            result[name] = tuple(
                row for row in tabs.get(name, ()) if row.get("project_id") in public_projects
            )
        for name in ("Looker_Assets", "Looker_Relationships", "Looker_Findings", "Looker_Analytics"):
            result[name] = tuple(
                row for row in tabs.get(name, ()) if row.get("project_id") in public_projects
            )
        public_resources = {row["resource_id"] for row in result["Resources"]}
        result["Connections"] = tuple(
            row
            for row in tabs.get("Connections", ())
            if row.get("source_project_id") in ("", None, *public_projects)
            and row.get("target_project_id") in ("", None, *public_projects)
            and row.get("source_resource_id") in ("", None, *public_resources)
            and row.get("target_resource_id") in ("", None, *public_resources)
        )
        return result


class ProjectionPublisher:
    def __init__(self, database: ProjectOSDatabase):
        self.database = database

    def stage_and_activate(
        self,
        binding: GoogleBindingRecord,
        bundle: ProjectionBundle,
        gateway: GoogleGateway,
    ) -> PublicationReceipt:
        revision_id = str(bundle.revision_id)
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO projection_revisions(revision_id,binding_id,schema_version,snapshot_hash,"
                "entity_counts_json,state,started_at) VALUES(?,?,?,?,?,'STAGED',?)",
                (
                    revision_id,
                    str(binding.binding_id),
                    bundle.schema_version,
                    bundle.snapshot_hash,
                    json.dumps(dict(bundle.row_counts), sort_keys=True, separators=(",", ":")),
                    utc_now(),
                ),
            )
        try:
            observed = gateway.publish_projection(binding, bundle.gateway_payload())
        except BaseException:
            self._fail(revision_id, "REMOTE_PUBLICATION_FAILED")
            raise
        verified = (
            observed.verified
            and observed.revision_id == revision_id
            and dict(observed.row_counts) == dict(bundle.row_counts)
            and dict(observed.hashes) == dict(bundle.tab_hashes)
        )
        if not verified:
            self._fail(revision_id, "READBACK_MISMATCH")
            return PublicationReceipt(
                observed.revision_id, False, observed.row_counts, observed.hashes
            )
        now = utc_now()
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE projection_revisions SET state='SUPERSEDED' WHERE binding_id=? AND state='ACTIVE'",
                (str(binding.binding_id),),
            )
            connection.execute(
                "UPDATE projection_revisions SET state='ACTIVE',verified_at=?,activated_at=? "
                "WHERE revision_id=? AND state='STAGED'",
                (now, now, revision_id),
            )
            connection.execute(
                "UPDATE google_bindings SET last_publication_revision=?,updated_at=? WHERE binding_id=?",
                (revision_id, now, str(binding.binding_id)),
            )
        return observed

    def _fail(self, revision_id: str, code: str) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE projection_revisions SET state='FAILED',failed_at=?,error_code=?,"
                "error_details='safe publication failure' WHERE revision_id=?",
                (utc_now(), code, revision_id),
            )


SAFE_RESULT_MESSAGES = {
    RequestResultCode.ACCEPTED: "Request accepted",
    RequestResultCode.CONFLICT: "Version conflict",
    RequestResultCode.REJECTED_AUTHORIZATION: "Request not permitted",
    RequestResultCode.REJECTED_VALIDATION: "Request validation failed",
    RequestResultCode.REJECTED_TAMPERED: "Request integrity check failed",
    RequestResultCode.RETRYABLE_REMOTE_FAILURE: "Result publication will be retried",
}


def safe_result_rows(results: Iterable[RequestResult]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "request_id": str(result.request_id),
            "result_code": result.code.value,
            "result_message": SAFE_RESULT_MESSAGES[result.code],
            "current_version": result.current_version,
        }
        for result in results
    )
