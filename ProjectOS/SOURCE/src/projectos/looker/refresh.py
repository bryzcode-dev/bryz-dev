from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping

from projectos.database import ProjectOSDatabase
from projectos.errors import ValidationError
from projectos.validation import canonical_json, reject_secret_material, require_text


_FIELDS = {
    "receipt_version",
    "support_state",
    "project_id",
    "intake_run_id",
    "analytic_version",
    "reconciliation_id",
    "binding_id",
    "sync_run_id",
    "projection_revision_id",
    "validation_command_ids",
    "source_revision",
    "refreshed_at",
}


@dataclass(frozen=True)
class VerifiedRefreshReceipt:
    receipt: "RefreshReceipt"
    sha256: str
    ok: bool = True


@dataclass(frozen=True)
class RefreshReceipt:
    receipt_version: int
    support_state: str
    project_id: str
    intake_run_id: str
    analytic_version: int
    reconciliation_id: str
    binding_id: str
    sync_run_id: str
    projection_revision_id: str
    validation_command_ids: tuple[str, ...]
    source_revision: str
    refreshed_at: str

    @classmethod
    def from_mapping(cls, value: object) -> "RefreshReceipt":
        if not isinstance(value, Mapping) or set(value) != _FIELDS:
            raise ValidationError("refresh receipt fields are invalid")
        reject_secret_material(value)
        if type(value["receipt_version"]) is not int or value["receipt_version"] != 1:
            raise ValidationError("refresh receipt version is invalid")
        if type(value["analytic_version"]) is not int or value["analytic_version"] < 1:
            raise ValidationError("refresh analytic version is invalid")
        command_ids = value["validation_command_ids"]
        if (
            not isinstance(command_ids, list)
            or not command_ids
            or any(not isinstance(item, str) or not item.strip() for item in command_ids)
            or len(command_ids) != len(set(command_ids))
        ):
            raise ValidationError("refresh validation commands are invalid")
        text_fields = (
            "support_state", "project_id", "intake_run_id", "reconciliation_id",
            "binding_id", "sync_run_id", "projection_revision_id", "source_revision",
            "refreshed_at",
        )
        if any(not isinstance(value[field], str) for field in text_fields):
            raise ValidationError("refresh receipt text field is invalid")
        texts = {field: require_text(value[field], field) for field in text_fields}
        return cls(
            1,
            texts["support_state"],
            texts["project_id"],
            texts["intake_run_id"],
            value["analytic_version"],
            texts["reconciliation_id"],
            texts["binding_id"],
            texts["sync_run_id"],
            texts["projection_revision_id"],
            tuple(command_ids),
            texts["source_revision"],
            texts["refreshed_at"],
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "analytic_version": self.analytic_version,
            "binding_id": self.binding_id,
            "intake_run_id": self.intake_run_id,
            "project_id": self.project_id,
            "projection_revision_id": self.projection_revision_id,
            "receipt_version": self.receipt_version,
            "reconciliation_id": self.reconciliation_id,
            "refreshed_at": self.refreshed_at,
            "source_revision": self.source_revision,
            "support_state": self.support_state,
            "sync_run_id": self.sync_run_id,
            "validation_command_ids": list(self.validation_command_ids),
        }

    def verify(self, database: ProjectOSDatabase) -> VerifiedRefreshReceipt:
        if self.support_state != "REAL":
            raise ValidationError("only REAL refresh receipts can be verified")
        if database.schema_version() < 3:
            raise ValidationError("refresh receipts require database schema 3")
        intake = database.connection.execute(
            "SELECT git_head FROM looker_intake_runs WHERE project_id=? AND intake_run_id=?",
            (self.project_id, self.intake_run_id),
        ).fetchone()
        if intake is None or intake["git_head"] != self.source_revision:
            raise ValidationError("refresh receipt source revision is unbound")

        analytic_rows = database.connection.execute(
            "SELECT analytic_type,value_json,source_run_id FROM looker_analytics WHERE project_id=?",
            (self.project_id,),
        ).fetchall()
        analytics = [
            row for row in analytic_rows
            if int(json.loads(row["value_json"]).get("version", 0)) == self.analytic_version
        ]
        if {row["analytic_type"] for row in analytics} != {"LOOKER_GRAPH", "LOOKER_SUMMARY"} or {
            row["source_run_id"] for row in analytics
        } != {self.intake_run_id}:
            raise ValidationError("refresh receipt analytics are unavailable or mixed")

        reconciliation = database.connection.execute(
            "SELECT project_id,intake_run_id,analytic_source_run_id,analytic_version,status "
            "FROM looker_reconciliation_runs WHERE reconciliation_id=?",
            (self.reconciliation_id,),
        ).fetchone()
        if reconciliation is None or (
            reconciliation["project_id"] != self.project_id
            or reconciliation["intake_run_id"] != self.intake_run_id
            or reconciliation["analytic_source_run_id"] != self.intake_run_id
            or reconciliation["analytic_version"] != self.analytic_version
            or reconciliation["status"] != "READY"
        ):
            raise ValidationError("refresh receipt reconciliation is not ready or is unbound")

        revision = database.connection.execute(
            "SELECT binding_id,state,verified_at,activated_at FROM projection_revisions WHERE revision_id=?",
            (self.projection_revision_id,),
        ).fetchone()
        if revision is None or (
            revision["binding_id"] != self.binding_id
            or revision["state"] != "ACTIVE"
            or not revision["verified_at"]
            or not revision["activated_at"]
        ):
            raise ValidationError("refresh receipt projection is not active or is unbound")

        sync = database.connection.execute(
            "SELECT binding_id,status,finished_at FROM sync_runs WHERE run_id=?",
            (self.sync_run_id,),
        ).fetchone()
        if sync is None or sync["binding_id"] != self.binding_id or sync["status"] != "COMPLETE" or not sync["finished_at"]:
            raise ValidationError("refresh receipt sync is incomplete or unbound")

        validation_rows = database.connection.execute(
            "SELECT command_id,passed FROM looker_validation_results WHERE intake_run_id=? ORDER BY command_id",
            (self.intake_run_id,),
        ).fetchall()
        if tuple(row["command_id"] for row in validation_rows) != tuple(sorted(self.validation_command_ids)) or any(
            not row["passed"] for row in validation_rows
        ):
            raise ValidationError("refresh receipt validation evidence is missing or failed")

        digest = hashlib.sha256(canonical_json(self.to_mapping()).encode()).hexdigest()
        return VerifiedRefreshReceipt(self, digest)
