from __future__ import annotations

import sqlite3
import unittest
from importlib.resources import files

from tests.helpers import TemporaryDirectoryMixin

from projectos.database import Migration, ProjectOSDatabase
from projectos.errors import MigrationError


class StaticMigrationSource:
    def __init__(self, *migrations: Migration):
        self._migrations = migrations

    def list(self) -> tuple[Migration, ...]:
        return self._migrations


class ProjectOSDatabasePhase2Tests(TemporaryDirectoryMixin, unittest.TestCase):
    def test_fresh_database_reaches_schema_two(self) -> None:
        database = ProjectOSDatabase(self.temp_path / "fresh.db").initialize()
        tables = {
            row[0]
            for row in database.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertEqual(3, database.schema_version())
        self.assertTrue(
            {
                "users",
                "google_bindings",
                "remote_request_receipts",
                "remote_access_receipts",
                "projection_revisions",
            }.issubset(tables)
        )
        request_columns = {
            row[1] for row in database.connection.execute("PRAGMA table_info(change_requests)")
        }
        self.assertTrue(
            {
                "request_schema_version",
                "operation",
                "actor_role_claim",
                "client_request_hash",
                "binding_id",
                "source_row",
                "observed_at",
                "result_code",
                "result_message",
                "current_version",
                "publication_revision",
            }.issubset(request_columns)
        )
        database.close()

    def test_phase_one_database_migrates_without_data_loss(self) -> None:
        path = self.temp_path / "phase-one.db"
        initial = files("projectos").joinpath("migrations/0001.sql").read_text(encoding="utf-8")
        version_one = Migration(1, "0001.sql", initial)
        database = ProjectOSDatabase(path, StaticMigrationSource(version_one)).initialize()
        database.connection.execute(
            "INSERT INTO projects(project_id,slug,name,project_type,status,visibility,created_at,updated_at) "
            "VALUES('p1','phase-one','Phase One','LOCAL','ACTIVE','PUBLIC','t','t')"
        )
        database.close()

        database = ProjectOSDatabase(path).initialize()
        row = database.connection.execute(
            "SELECT name, version FROM projects WHERE project_id='p1'"
        ).fetchone()
        self.assertEqual(("Phase One", 1), tuple(row))
        self.assertEqual(3, database.schema_version())
        database.close()

    def test_migration_two_is_idempotent(self) -> None:
        path = self.temp_path / "idempotent.db"
        ProjectOSDatabase(path).initialize().close()
        database = ProjectOSDatabase(path).initialize()
        versions = database.connection.execute(
            "SELECT version, COUNT(*) FROM schema_migrations GROUP BY version ORDER BY version"
        ).fetchall()
        self.assertEqual([(1, 1), (2, 1), (3, 1)], [tuple(row) for row in versions])
        database.close()

    def test_migration_failure_rolls_back_version_and_schema(self) -> None:
        path = self.temp_path / "failure.db"
        initial = files("projectos").joinpath("migrations/0001.sql").read_text(encoding="utf-8")
        source = StaticMigrationSource(
            Migration(1, "0001.sql", initial),
            Migration(2, "0002-broken.sql", "CREATE TABLE partial_row(value TEXT); BROKEN SQL;"),
        )
        with self.assertRaisesRegex(MigrationError, "migration 2"):
            ProjectOSDatabase(path, source).initialize()

        connection = sqlite3.connect(path)
        version = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()[0]
        partial = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='partial_row'"
        ).fetchone()[0]
        self.assertEqual(1, version)
        self.assertEqual(0, partial)
        connection.close()

    def test_newer_than_three_still_fails_closed(self) -> None:
        path = self.temp_path / "future.db"
        connection = sqlite3.connect(path)
        connection.executescript(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL);"
            "INSERT INTO schema_migrations VALUES(4, 'future', 't');"
        )
        connection.close()
        with self.assertRaises(MigrationError):
            ProjectOSDatabase(path).initialize()


if __name__ == "__main__":
    unittest.main()
