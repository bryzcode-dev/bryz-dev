from __future__ import annotations

import sqlite3
from uuid import UUID, uuid4

from .audit import AuditLog
from .database import ProjectOSDatabase, utc_now
from .errors import ValidationError, VersionConflict
from .google.types import GoogleBindingCreate, GoogleBindingPatch, GoogleBindingRecord
from .validation import canonical_json, reject_secret_material, require_text


class GoogleBindingRepository:
    def __init__(self, database: ProjectOSDatabase, audit: AuditLog | None = None):
        self.database = database
        self.audit = audit or AuditLog()

    def create(self, command: GoogleBindingCreate, actor: str) -> GoogleBindingRecord:
        reject_secret_material(command.provenance)
        self._require_credential(command.credential_id)
        if command.contract_version < 1:
            raise ValidationError("contract_version must be positive")
        binding_id = str(uuid4())
        now = utc_now()
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    "INSERT INTO google_bindings(binding_id,environment,spreadsheet_id,display_name,"
                    "contract_version,gas_script_id,gas_deployment_id,enabled,write_enabled,credential_id,"
                    "status,provenance_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        binding_id,
                        require_text(command.environment, "environment"),
                        require_text(command.spreadsheet_id, "spreadsheet_id"),
                        require_text(command.display_name, "display_name"),
                        command.contract_version,
                        command.gas_script_id,
                        command.gas_deployment_id,
                        int(command.enabled),
                        int(command.write_enabled),
                        str(command.credential_id),
                        "READY" if command.enabled else "DISABLED",
                        canonical_json(dict(command.provenance)),
                        now,
                        now,
                    ),
                )
                self.audit.append(
                    connection, "google_binding.created", actor, "google_binding", binding_id, {}
                )
        except sqlite3.IntegrityError as exc:
            raise ValidationError("Google binding conflicts with an existing record") from exc
        return self.get(UUID(binding_id))

    def get(self, binding_id: UUID) -> GoogleBindingRecord | None:
        row = self.database.connection.execute(
            "SELECT * FROM google_bindings WHERE binding_id=?", (str(binding_id),)
        ).fetchone()
        return self._record(row) if row else None

    def list(self) -> list[GoogleBindingRecord]:
        return [
            self._record(row)
            for row in self.database.connection.execute(
                "SELECT * FROM google_bindings ORDER BY environment,binding_id"
            )
        ]

    def update(
        self,
        binding_id: UUID,
        expected_version: int,
        patch: GoogleBindingPatch,
        actor: str,
    ) -> GoogleBindingRecord:
        current = self.get(binding_id)
        if current is None:
            raise ValidationError("Google binding does not exist")
        if current.version != expected_version:
            raise VersionConflict("Google binding version conflict")
        credential_id = patch.credential_id or current.credential_id
        self._require_credential(credential_id)
        contract_version = patch.contract_version or current.contract_version
        if contract_version < 1:
            raise ValidationError("contract_version must be positive")
        enabled = patch.enabled if patch.enabled is not None else current.enabled
        write_enabled = (
            patch.write_enabled if patch.write_enabled is not None else current.write_enabled
        )
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE google_bindings SET display_name=?,contract_version=?,credential_id=?,"
                "gas_script_id=?,gas_deployment_id=?,enabled=?,write_enabled=?,status=?,"
                "provenance_json=COALESCE(?,provenance_json),version=version+1,updated_at=? "
                "WHERE binding_id=? AND version=?",
                (
                    require_text(patch.display_name, "display_name")
                    if patch.display_name is not None
                    else current.display_name,
                    contract_version,
                    str(credential_id),
                    patch.gas_script_id if patch.gas_script_id is not None else current.gas_script_id,
                    patch.gas_deployment_id
                    if patch.gas_deployment_id is not None
                    else current.gas_deployment_id,
                    int(enabled),
                    int(write_enabled),
                    patch.status or ("READY" if enabled else "DISABLED"),
                    canonical_json(dict(patch.provenance))
                    if patch.provenance is not None
                    else None,
                    utc_now(),
                    str(binding_id),
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise VersionConflict("Google binding version conflict")
            self.audit.append(
                connection, "google_binding.updated", actor, "google_binding", str(binding_id), {}
            )
        return self.get(binding_id)

    def assert_write_ready(self, binding_id: UUID) -> GoogleBindingRecord:
        binding = self.get(binding_id)
        if binding is None:
            raise ValidationError("Google binding does not exist")
        if not binding.enabled or not binding.write_enabled:
            raise ValidationError("Google binding writes are disabled")
        require_text(binding.spreadsheet_id, "spreadsheet_id")
        if binding.contract_version < 1:
            raise ValidationError("Google binding contract is invalid")
        self._require_credential(binding.credential_id)
        return binding

    def _require_credential(self, credential_id: UUID) -> None:
        row = self.database.connection.execute(
            "SELECT 1 FROM credential_references WHERE credential_id=?", (str(credential_id),)
        ).fetchone()
        if row is None:
            raise ValidationError("credential reference does not exist")

    @staticmethod
    def _record(row: sqlite3.Row) -> GoogleBindingRecord:
        return GoogleBindingRecord(
            binding_id=UUID(row["binding_id"]),
            environment=row["environment"],
            spreadsheet_id=row["spreadsheet_id"],
            display_name=row["display_name"],
            contract_version=row["contract_version"],
            credential_id=UUID(row["credential_id"]),
            gas_script_id=row["gas_script_id"],
            gas_deployment_id=row["gas_deployment_id"],
            sharing_policy=row["sharing_policy"],
            enabled=bool(row["enabled"]),
            write_enabled=bool(row["write_enabled"]),
            status=row["status"],
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_preflight_at=row["last_preflight_at"],
            last_publication_revision=row["last_publication_revision"],
        )
