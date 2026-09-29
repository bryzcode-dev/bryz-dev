from __future__ import annotations

import hashlib
import json
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.helpers import TemporaryDirectoryMixin

from projectos.backup import BackupService
from projectos.database import ProjectOSDatabase
from projectos.errors import HealthError
from projectos.health import ProjectOSDoctor
from projectos.repositories import ProjectRepository
from projectos.types import ProjectCreate, ProjectType, ProjectVisibility


class BackupHealthTests(TemporaryDirectoryMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.database = self.open_database()
        self.repository = ProjectRepository(self.database)
        self.repository.create(
            ProjectCreate(
                slug="safe-project",
                name="Safe Project",
                project_type=ProjectType.LOCAL,
                visibility=ProjectVisibility.PRIVATE,
            ),
            actor="owner",
        )
        self.backups = self.temp_path / "backups"
        self.service = BackupService(self.database)

    def test_backup_uses_sqlite_consistent_snapshot_and_sha256_manifest(self) -> None:
        manifest = self.service.create(self.backups)

        self.assertTrue(manifest.snapshot_path.is_file())
        self.assertTrue(manifest.manifest_path.is_file())
        self.assertEqual(
            hashlib.sha256(manifest.snapshot_path.read_bytes()).hexdigest(), manifest.sha256
        )
        snapshot = sqlite3.connect(manifest.snapshot_path)
        try:
            self.assertEqual(1, snapshot.execute("SELECT COUNT(*) FROM projects").fetchone()[0])
            self.assertEqual("ok", snapshot.execute("PRAGMA integrity_check").fetchone()[0])
        finally:
            snapshot.close()
        self.assertTrue(self.service.verify(manifest.manifest_path).valid)

    def test_verify_detects_changed_or_missing_snapshot(self) -> None:
        manifest = self.service.create(self.backups)
        manifest.snapshot_path.write_bytes(manifest.snapshot_path.read_bytes() + b"changed")
        changed = self.service.verify(manifest.manifest_path)
        manifest.snapshot_path.unlink()
        missing = self.service.verify(manifest.manifest_path)

        self.assertFalse(changed.valid)
        self.assertIn("checksum mismatch", changed.errors)
        self.assertFalse(missing.valid)
        self.assertIn("snapshot is missing", missing.errors)

    def test_restore_refuses_existing_target_without_replace(self) -> None:
        manifest = self.service.create(self.backups)
        target = self.temp_path / "target.db"
        target.write_bytes(b"preserve")

        with self.assertRaises(HealthError):
            self.service.restore(manifest.manifest_path, target)

        self.assertEqual(b"preserve", target.read_bytes())

    def test_restore_refuses_active_target_or_sqlite_sidecars(self) -> None:
        manifest = self.service.create(self.backups)
        with self.assertRaises(HealthError):
            self.service.restore(manifest.manifest_path, self.database.path, replace=True)

        target = self.temp_path / "target-with-sidecar.db"
        target.write_bytes(b"preserve")
        wal = Path(str(target) + "-wal")
        wal.write_bytes(b"active-wal")
        with self.assertRaises(HealthError):
            self.service.restore(manifest.manifest_path, target, replace=True)

        self.assertEqual(b"preserve", target.read_bytes())
        self.assertEqual(b"active-wal", wal.read_bytes())

    def test_restore_corrupt_snapshot_preserves_current_database(self) -> None:
        manifest = self.service.create(self.backups)
        target = self.temp_path / "target.db"
        target.write_bytes(b"current-database")
        manifest.snapshot_path.write_bytes(b"not sqlite")
        payload = json.loads(manifest.manifest_path.read_text())
        payload["sha256"] = hashlib.sha256(b"not sqlite").hexdigest()
        payload["byte_size"] = len(b"not sqlite")
        manifest.manifest_path.write_text(json.dumps(payload))

        with self.assertRaises(HealthError):
            self.service.restore(manifest.manifest_path, target, replace=True)

        self.assertEqual(b"current-database", target.read_bytes())
        self.assertEqual([], list(self.temp_path.glob("target.db.rollback-*")))

    def test_restore_newer_schema_fails_closed(self) -> None:
        future = self.temp_path / "future.db"
        connection = sqlite3.connect(future)
        connection.executescript(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT,applied_at TEXT);"
            "INSERT INTO schema_migrations VALUES(99,'future','now');"
        )
        connection.close()
        manifest = self.service.create_manifest_for_snapshot(future, self.backups)
        target = self.temp_path / "target.db"
        target.write_bytes(b"current")

        with self.assertRaises(HealthError):
            self.service.restore(manifest.manifest_path, target, replace=True)

        self.assertEqual(b"current", target.read_bytes())

    def test_doctor_detects_foreign_key_and_integrity_failures(self) -> None:
        self.database.connection.execute("PRAGMA foreign_keys=OFF")
        self.database.connection.execute(
            "INSERT INTO project_locations "
            "(location_id,project_id,machine_id,location_type,created_at,updated_at) "
            "VALUES('bad-location','missing','mac','LOCAL','now','now')"
        )
        self.database.connection.execute("PRAGMA foreign_keys=ON")
        foreign_key_report = ProjectOSDoctor(self.database).check()
        with patch.object(ProjectOSDoctor, "_integrity_rows", return_value=("page is corrupt",)):
            integrity_report = ProjectOSDoctor(self.database).check()

        self.assertFalse(foreign_key_report.healthy)
        self.assertIn("foreign_key_violation", foreign_key_report.checks)
        self.assertFalse(integrity_report.healthy)
        self.assertIn("integrity_failure", integrity_report.checks)

    def test_backup_manifest_contains_no_secret_material(self) -> None:
        manifest = self.service.create(self.backups)
        payload = json.loads(manifest.manifest_path.read_text())
        serialized = json.dumps(payload).lower()

        self.assertNotIn("password", serialized)
        self.assertNotIn("api_token", serialized)
        self.assertEqual(manifest.to_dict(), payload)


if __name__ == "__main__":
    unittest.main()
