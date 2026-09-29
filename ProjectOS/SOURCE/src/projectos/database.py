from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Iterator, Protocol, runtime_checkable

from .errors import MigrationError

SCHEMA_VERSION = 3


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


@runtime_checkable
class MigrationSource(Protocol):
    def list(self) -> tuple[Migration, ...]: ...


class PackagedMigrationSource:
    def list(self) -> tuple[Migration, ...]:
        migrations: list[Migration] = []
        root = files("projectos").joinpath("migrations")
        for item in root.iterdir():
            if not item.name.endswith(".sql") or len(item.name) < 8:
                continue
            prefix = item.name[:4]
            if not prefix.isdigit():
                continue
            migrations.append(
                Migration(int(prefix), item.name, item.read_text(encoding="utf-8"))
            )
        return tuple(sorted(migrations, key=lambda migration: migration.version))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ProjectOSDatabase:
    def __init__(self, path: Path, migration_source: MigrationSource | None = None):
        self.path = Path(path)
        self.migration_source = migration_source or PackagedMigrationSource()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, isolation_level=None)
        try:
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys=ON")
            self.connection.execute("PRAGMA journal_mode=WAL")
        except BaseException:
            self.connection.close()
            raise
        self._savepoint_counter = 0

    @classmethod
    def open_existing(
        cls,
        path: Path,
        *,
        read_only: bool = False,
    ) -> "ProjectOSDatabase":
        database_path = Path(path)
        if not database_path.is_file() or database_path.is_symlink():
            raise MigrationError("existing ProjectOS database is unavailable")
        database = cls.__new__(cls)
        database.path = database_path
        database.migration_source = PackagedMigrationSource()
        try:
            if read_only:
                uri = f"{database_path.resolve().as_uri()}?mode=ro&immutable=1"
                database.connection = sqlite3.connect(
                    uri, isolation_level=None, uri=True
                )
            else:
                database.connection = sqlite3.connect(
                    database_path, isolation_level=None
                )
            database.connection.row_factory = sqlite3.Row
            database._savepoint_counter = 0
            version = database._stored_schema_version()
            if version != SCHEMA_VERSION:
                raise MigrationError(
                    f"database schema {version} does not match required schema {SCHEMA_VERSION}"
                )
            database.connection.execute("PRAGMA foreign_keys=ON")
            if not read_only:
                database.connection.execute("PRAGMA journal_mode=WAL")
            return database
        except BaseException:
            connection = getattr(database, "connection", None)
            if connection is not None:
                connection.close()
            raise

    def initialize(self) -> "ProjectOSDatabase":
        try:
            current = self._stored_schema_version()
            if current > SCHEMA_VERSION:
                raise MigrationError(
                    f"database schema {current} is newer than supported schema {SCHEMA_VERSION}"
                )
            migrations = self._validated_migrations()
            for migration in migrations:
                if migration.version > current:
                    self._apply_migration(migration)
                    current = migration.version
            return self
        except BaseException:
            self.close()
            raise

    def _stored_schema_version(self) -> int:
        exists = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        if not exists:
            return 0
        row = self.connection.execute(
            "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
        ).fetchone()
        return int(row["version"])

    def _validated_migrations(self) -> tuple[Migration, ...]:
        migrations = self.migration_source.list()
        versions = [migration.version for migration in migrations]
        if not versions:
            raise MigrationError("no database migrations are available")
        if len(set(versions)) != len(versions):
            raise MigrationError("database migration versions must be unique")
        if versions != list(range(1, max(versions) + 1)):
            raise MigrationError("database migration versions must be contiguous from 1")
        if max(versions) > SCHEMA_VERSION:
            raise MigrationError(
                f"migration source version {max(versions)} is newer than supported schema {SCHEMA_VERSION}"
            )
        return migrations

    def _apply_migration(self, migration: Migration) -> None:
        escaped_name = migration.name.replace("'", "''")
        escaped_time = utc_now().replace("'", "''")
        script = (
            "BEGIN IMMEDIATE;\n"
            + migration.sql
            + f"\nINSERT INTO schema_migrations(version,name,applied_at) "
            f"VALUES({migration.version},'{escaped_name}','{escaped_time}');\nCOMMIT;"
        )
        try:
            self.connection.executescript(script)
        except sqlite3.DatabaseError as exc:
            try:
                self.connection.execute("ROLLBACK")
            except sqlite3.DatabaseError:
                pass
            raise MigrationError(f"failed to apply migration {migration.version}: {exc}") from exc

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        if self.connection.in_transaction:
            self._savepoint_counter += 1
            savepoint = f"projectos_{self._savepoint_counter}"
            self.connection.execute(f"SAVEPOINT {savepoint}")
            try:
                yield self.connection
            except BaseException:
                self.connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                self.connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            else:
                self.connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            return
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        else:
            self.connection.execute("COMMIT")

    def schema_version(self) -> int:
        return self._stored_schema_version()

    def close(self) -> None:
        self.connection.close()
