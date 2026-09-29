from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from .database import SCHEMA_VERSION, ProjectOSDatabase, utc_now
from .errors import HealthError
from .validation import canonical_json, redact_sensitive


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class BackupManifest:
    backup_id: UUID
    manifest_path: Path
    snapshot_path: Path
    sha256: str
    byte_size: int
    schema_version: int
    created_at: str
    source_identity: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "backup_id": str(self.backup_id),
            "manifest_path": str(self.manifest_path),
            "snapshot_path": str(self.snapshot_path),
            "sha256": self.sha256,
            "byte_size": self.byte_size,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "source_identity": self.source_identity,
        }


@dataclass(frozen=True)
class BackupVerification:
    valid: bool
    manifest_path: Path
    snapshot_path: Path | None
    errors: tuple[str, ...]
    schema_version: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "manifest_path": str(self.manifest_path),
            "snapshot_path": str(self.snapshot_path) if self.snapshot_path else None,
            "errors": list(self.errors),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class RestoreResult:
    target_db: Path
    rollback_path: Path | None
    restored_sha256: str
    schema_version: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_db": str(self.target_db),
            "rollback_path": str(self.rollback_path) if self.rollback_path else None,
            "restored_sha256": self.restored_sha256,
            "schema_version": self.schema_version,
        }


class BackupService:
    def __init__(self, database: ProjectOSDatabase):
        self.database = database

    def create(self, destination_dir: Path) -> BackupManifest:
        destination = Path(destination_dir)
        destination.mkdir(parents=True, exist_ok=True)
        backup_id = uuid4()
        snapshot_path = destination / f"projectos-{backup_id}.db"
        target = sqlite3.connect(snapshot_path)
        try:
            self.database.connection.backup(target)
        finally:
            target.close()
        manifest = self._write_manifest(
            snapshot_path,
            destination,
            backup_id=backup_id,
            schema_version=self.database.schema_version(),
            source_identity={
                "database_name": self.database.path.name,
                "kind": "projectos_sqlite",
            },
        )
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO backup_manifests "
                "(backup_id,manifest_path,snapshot_path,sha256,byte_size,schema_version,"
                "created_at,verification_json) VALUES(?,?,?,?,?,?,?,?)",
                (
                    str(manifest.backup_id),
                    str(manifest.manifest_path),
                    str(manifest.snapshot_path),
                    manifest.sha256,
                    manifest.byte_size,
                    manifest.schema_version,
                    manifest.created_at,
                    canonical_json({"created_from_sqlite_backup_api": True}),
                ),
            )
        return manifest

    def create_manifest_for_snapshot(
        self, snapshot_path: Path, destination_dir: Path
    ) -> BackupManifest:
        snapshot = Path(snapshot_path)
        destination = Path(destination_dir)
        destination.mkdir(parents=True, exist_ok=True)
        schema_version = self._schema_version(snapshot)
        return self._write_manifest(
            snapshot,
            destination,
            backup_id=uuid4(),
            schema_version=schema_version,
            source_identity={"database_name": snapshot.name, "kind": "sqlite_snapshot"},
        )

    def _write_manifest(
        self,
        snapshot_path: Path,
        destination_dir: Path,
        *,
        backup_id: UUID,
        schema_version: int,
        source_identity: dict[str, Any],
    ) -> BackupManifest:
        manifest_path = destination_dir / f"projectos-{backup_id}.manifest.json"
        manifest = BackupManifest(
            backup_id=backup_id,
            manifest_path=manifest_path,
            snapshot_path=snapshot_path.resolve(),
            sha256=_sha256(snapshot_path),
            byte_size=snapshot_path.stat().st_size,
            schema_version=schema_version,
            created_at=utc_now(),
            source_identity=source_identity,
        )
        payload = redact_sensitive(manifest.to_dict())
        temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, manifest_path)
        return manifest

    def verify(self, manifest_path: Path) -> BackupVerification:
        path = Path(manifest_path)
        errors: list[str] = []
        snapshot: Path | None = None
        schema_version: int | None = None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            snapshot = Path(payload["snapshot_path"])
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            return BackupVerification(False, path, None, (f"invalid manifest: {exc}",), None)
        if not snapshot.is_file():
            return BackupVerification(False, path, snapshot, ("snapshot is missing",), None)
        if snapshot.stat().st_size != payload.get("byte_size"):
            errors.append("byte size mismatch")
        if _sha256(snapshot) != payload.get("sha256"):
            errors.append("checksum mismatch")
        if not errors:
            inspection_errors, schema_version = self._inspect_snapshot(snapshot)
            errors.extend(inspection_errors)
            if schema_version != payload.get("schema_version"):
                errors.append("schema version mismatch")
        return BackupVerification(not errors, path, snapshot, tuple(errors), schema_version)

    def restore(
        self, manifest_path: Path, target_db: Path, replace: bool = False
    ) -> RestoreResult:
        target = Path(target_db)
        if target.resolve(strict=False) == self.database.path.resolve(strict=False):
            raise HealthError("restore target is the active ProjectOS database")
        if target.exists() and not replace:
            raise HealthError("restore target exists; pass replace=True to preserve and replace it")
        sidecars = (Path(str(target) + "-wal"), Path(str(target) + "-shm"))
        if any(path.exists() for path in sidecars):
            raise HealthError("restore target has SQLite sidecars and may be active")
        verification = self.verify(manifest_path)
        if not verification.valid or verification.snapshot_path is None:
            raise HealthError("backup verification failed: " + "; ".join(verification.errors))
        if verification.schema_version != SCHEMA_VERSION:
            raise HealthError(
                f"backup schema {verification.schema_version} is not supported schema {SCHEMA_VERSION}"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, staged_name = tempfile.mkstemp(
            prefix=f".{target.name}.restore-", dir=target.parent
        )
        os.close(descriptor)
        staged = Path(staged_name)
        rollback: Path | None = None
        try:
            shutil.copy2(verification.snapshot_path, staged)
            staged_errors, staged_schema = self._inspect_snapshot(staged)
            if staged_errors or staged_schema != SCHEMA_VERSION:
                raise HealthError("staged restore failed health checks: " + "; ".join(staged_errors))
            if target.exists():
                rollback = target.with_name(f"{target.name}.rollback-{uuid4()}")
                os.replace(target, rollback)
            try:
                os.replace(staged, target)
            except BaseException:
                if rollback is not None and rollback.exists() and not target.exists():
                    os.replace(rollback, target)
                raise
        finally:
            if staged.exists():
                staged.unlink()
        return RestoreResult(
            target_db=target,
            rollback_path=rollback,
            restored_sha256=_sha256(target),
            schema_version=SCHEMA_VERSION,
        )

    @staticmethod
    def _schema_version(snapshot: Path) -> int:
        connection = sqlite3.connect(f"file:{snapshot.resolve()}?mode=ro", uri=True)
        try:
            row = connection.execute(
                "SELECT COALESCE(MAX(version),0) FROM schema_migrations"
            ).fetchone()
            return int(row[0])
        finally:
            connection.close()

    @classmethod
    def _inspect_snapshot(cls, snapshot: Path) -> tuple[list[str], int | None]:
        errors: list[str] = []
        schema_version: int | None = None
        try:
            connection = sqlite3.connect(f"file:{snapshot.resolve()}?mode=ro", uri=True)
            try:
                integrity = tuple(row[0] for row in connection.execute("PRAGMA integrity_check"))
                if integrity != ("ok",):
                    errors.append("integrity check failed")
                violations = list(connection.execute("PRAGMA foreign_key_check"))
                if violations:
                    errors.append("foreign key check failed")
                row = connection.execute(
                    "SELECT COALESCE(MAX(version),0) FROM schema_migrations"
                ).fetchone()
                schema_version = int(row[0])
                if schema_version > SCHEMA_VERSION:
                    errors.append(f"snapshot schema {schema_version} is newer than supported")
            finally:
                connection.close()
        except (sqlite3.DatabaseError, OSError) as exc:
            errors.append(f"snapshot is not a healthy SQLite database: {exc}")
        return errors, schema_version
