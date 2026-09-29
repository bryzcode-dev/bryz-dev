from __future__ import annotations

import sqlite3
import unittest

from tests.helpers import TemporaryDirectoryMixin

from projectos.database import ProjectOSDatabase
from projectos.errors import MigrationError


REQUIRED_TABLES = {
    "schema_migrations",
    "projects",
    "project_locations",
    "resources",
    "deployments",
    "connections",
    "credential_references",
    "credential_usage",
    "looker_assets",
    "looker_analytics",
    "change_requests",
    "conflicts",
    "sync_runs",
    "sync_checkpoints",
    "audit_events",
    "discovery_runs",
    "discovery_findings",
    "extension_adoptions",
    "backup_manifests",
}


class ProjectOSDatabaseTests(TemporaryDirectoryMixin, unittest.TestCase):
    def test_initialize_creates_complete_schema(self) -> None:
        database = ProjectOSDatabase(self.temp_path / "projectos.db").initialize()
        table_names = {
            row[0]
            for row in database.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

        self.assertEqual(3, database.schema_version())
        self.assertTrue(REQUIRED_TABLES.issubset(table_names))
        self.assertEqual("wal", database.connection.execute("PRAGMA journal_mode").fetchone()[0])
        database.close()

    def test_initialize_is_idempotent(self) -> None:
        path = self.temp_path / "projectos.db"
        database = ProjectOSDatabase(path).initialize()
        database.close()
        database = ProjectOSDatabase(path).initialize()

        count = database.connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 3"
        ).fetchone()[0]

        self.assertEqual(1, count)
        database.close()

    def test_transaction_rolls_back_all_rows_on_error(self) -> None:
        database = ProjectOSDatabase(self.temp_path / "projectos.db").initialize()

        with self.assertRaisesRegex(RuntimeError, "abort"):
            with database.transaction() as connection:
                connection.execute(
                    "INSERT INTO audit_events "
                    "(audit_id, event_type, actor, entity_type, entity_id, payload_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("audit-1", "test", "tester", "project", "p1", "{}", "2026-09-26T00:00:00Z"),
                )
                raise RuntimeError("abort")

        count = database.connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        self.assertEqual(0, count)
        database.close()

    def test_foreign_keys_are_enabled(self) -> None:
        database = ProjectOSDatabase(self.temp_path / "projectos.db").initialize()
        enabled = database.connection.execute("PRAGMA foreign_keys").fetchone()[0]
        self.assertEqual(1, enabled)
        database.close()

    def test_newer_schema_fails_closed(self) -> None:
        path = self.temp_path / "projectos.db"
        connection = sqlite3.connect(path)
        connection.executescript(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL);"
            "INSERT INTO schema_migrations VALUES(99, 'future', '2026-09-26T00:00:00Z');"
        )
        connection.close()

        with self.assertRaises(MigrationError):
            ProjectOSDatabase(path).initialize()


if __name__ == "__main__":
    unittest.main()
