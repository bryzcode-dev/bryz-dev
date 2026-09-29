from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class TabContract:
    name: str
    headers: tuple[str, ...]
    exposure: str
    protected: bool = True


@dataclass(frozen=True)
class WorkbookContract:
    version: int
    tabs: tuple[TabContract, ...]

    @classmethod
    def current(cls) -> "WorkbookContract":
        return cls(
            version=1,
            tabs=(
                TabContract(
                    "_ProjectOS_Schema",
                    (
                        "contract_version",
                        "workbook_id",
                        "active_projection_revision",
                        "contract_hash",
                        "tab_hashes_json",
                        "updated_at",
                    ),
                    "OWNER_ONLY",
                ),
                TabContract(
                    "_ProjectOS_Sync",
                    (
                        "state",
                        "last_run_id",
                        "last_run_at",
                        "checkpoint",
                        "active_revision",
                        "safe_counts_json",
                        "status_code",
                    ),
                    "ROLE_SAFE_SUMMARY",
                ),
                TabContract(
                    "Users",
                    (
                        "user_id",
                        "email",
                        "display_name",
                        "role",
                        "active",
                        "added_at",
                        "updated_at",
                        "last_access_at",
                        "notes",
                        "version",
                        "projection_revision",
                        "row_hash",
                    ),
                    "CURRENT_CALLER_OR_OWNER",
                ),
                TabContract(
                    "Projects",
                    (
                        "projection_revision",
                        "project_id",
                        "version",
                        "status",
                        "visibility",
                        "name",
                        "description",
                        "project_type",
                        "tags",
                        "updated_at",
                        "row_hash",
                    ),
                    "PUBLIC_FILTERED",
                ),
                TabContract(
                    "Locations",
                    (
                        "projection_revision",
                        "location_id",
                        "project_id",
                        "version",
                        "status",
                        "machine_id",
                        "location_type",
                        "path",
                        "repository_root",
                        "drive_folder_id",
                        "drive_folder_url",
                        "environment",
                        "row_hash",
                    ),
                    "PUBLIC_FILTERED",
                ),
                TabContract(
                    "Resources",
                    (
                        "projection_revision",
                        "resource_id",
                        "project_id",
                        "version",
                        "status",
                        "resource_type",
                        "provider",
                        "external_id",
                        "name",
                        "url",
                        "environment",
                        "role",
                        "metadata_json",
                        "row_hash",
                    ),
                    "PUBLIC_FILTERED",
                ),
                TabContract(
                    "Deployments",
                    (
                        "projection_revision",
                        "deployment_id",
                        "project_id",
                        "resource_id",
                        "version",
                        "status",
                        "environment",
                        "script_id",
                        "external_deployment_id",
                        "deployment_url",
                        "active_version",
                        "notes",
                        "row_hash",
                    ),
                    "PUBLIC_FILTERED",
                ),
                TabContract(
                    "Connections",
                    (
                        "projection_revision",
                        "connection_id",
                        "version",
                        "status",
                        "source_project_id",
                        "source_resource_id",
                        "target_project_id",
                        "target_resource_id",
                        "connection_type",
                        "direction",
                        "implementation_method",
                        "purpose",
                        "notes",
                        "health_status",
                        "row_hash",
                    ),
                    "PUBLIC_FILTERED",
                ),
                TabContract(
                    "Credential_References",
                    (
                        "projection_revision",
                        "credential_id",
                        "version",
                        "provider",
                        "label",
                        "credential_type",
                        "purpose",
                        "storage_system",
                        "storage_reference",
                        "status",
                        "row_hash",
                    ),
                    "OWNER_ONLY",
                ),
                TabContract(
                    "Looker_Assets",
                    (
                        "projection_revision", "looker_asset_id", "project_id", "asset_type",
                        "file_path", "name", "metadata_json", "version", "updated_at", "row_hash",
                    ),
                    "PUBLIC_FILTERED",
                ),
                TabContract(
                    "Looker_Relationships",
                    (
                        "projection_revision", "relationship_id", "project_id", "intake_run_id",
                        "relationship_type", "source_type", "source_name", "target_type",
                        "target_name", "source_path", "source_line", "row_hash",
                    ),
                    "PUBLIC_FILTERED",
                ),
                TabContract(
                    "Looker_Findings",
                    (
                        "projection_revision", "finding_id", "project_id", "intake_run_id",
                        "severity", "category", "code", "subject", "status", "source_path",
                        "source_line", "created_at", "row_hash",
                    ),
                    "PUBLIC_FILTERED",
                ),
                TabContract(
                    "Looker_Analytics",
                    (
                        "projection_revision", "analytic_id", "project_id", "analytic_type",
                        "value_json", "source_run_id", "created_at", "row_hash",
                    ),
                    "PUBLIC_FILTERED",
                ),
                TabContract(
                    "Change_Requests",
                    (
                        "request_id",
                        "request_schema_version",
                        "actor_email",
                        "actor_role_claim",
                        "entity_type",
                        "entity_id",
                        "operation",
                        "base_version",
                        "changes_json",
                        "submitted_at",
                        "client_request_hash",
                        "gas_deployment_id",
                        "status",
                        "result_code",
                        "result_message",
                        "current_version",
                        "resolved_at",
                        "publication_revision",
                    ),
                    "REQUEST_APPEND",
                ),
                TabContract(
                    "Owner_Drafts",
                    (
                        "draft_id",
                        "entity_type",
                        "entity_id",
                        "operation",
                        "base_version",
                        "changes_json",
                        "submitted_request_id",
                        "draft_status",
                        "updated_at",
                    ),
                    "OWNER_ONLY",
                ),
                TabContract(
                    "Access_Events",
                    ("event_id", "actor_email", "accessed_at", "payload_hash"),
                    "INTERNAL",
                ),
                TabContract(
                    "Conflicts",
                    (
                        "conflict_id",
                        "request_id",
                        "entity_type",
                        "entity_id",
                        "current_version",
                        "status",
                        "created_at",
                        "resolved_at",
                    ),
                    "OWNER_ONLY",
                ),
                TabContract(
                    "Audit_Summary",
                    (
                        "projection_revision",
                        "audit_id",
                        "event_type",
                        "entity_type",
                        "entity_id",
                        "created_at",
                        "row_hash",
                    ),
                    "OWNER_ONLY",
                ),
            ),
        )

    def tab(self, name: str) -> TabContract:
        for tab in self.tabs:
            if tab.name == name:
                return tab
        raise KeyError(name)


@dataclass(frozen=True)
class WorkbookSnapshot:
    contract_version: int | None
    tabs: Mapping[str, tuple[tuple[str, ...], int]]
    protected_tabs: frozenset[str] | None = None
    formatted_tabs: frozenset[str] | None = None


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def contract_hash(contract: WorkbookContract) -> str:
    return hashlib.sha256(canonical_json_bytes(asdict(contract))).hexdigest()
