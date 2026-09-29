from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from .database import SCHEMA_VERSION, ProjectOSDatabase


@dataclass(frozen=True)
class HealthReport:
    healthy: bool
    schema_version: int | None
    checks: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "schema_version": self.schema_version,
            "checks": self.checks,
        }


class ProjectOSDoctor:
    def __init__(self, database: ProjectOSDatabase):
        self.database = database

    def _integrity_rows(self) -> tuple[str, ...]:
        return tuple(row[0] for row in self.database.connection.execute("PRAGMA integrity_check"))

    def check(self) -> HealthReport:
        checks: dict[str, Any] = {}
        schema_version: int | None = None
        healthy = True
        try:
            integrity = self._integrity_rows()
            if integrity == ("ok",):
                checks["integrity"] = "ok"
            else:
                checks["integrity_failure"] = list(integrity)
                healthy = False
        except sqlite3.DatabaseError as exc:
            checks["integrity_failure"] = str(exc)
            healthy = False
        try:
            violations = [tuple(row) for row in self.database.connection.execute("PRAGMA foreign_key_check")]
            if violations:
                checks["foreign_key_violation"] = violations
                healthy = False
            else:
                checks["foreign_keys"] = "ok"
        except sqlite3.DatabaseError as exc:
            checks["foreign_key_violation"] = str(exc)
            healthy = False
        try:
            schema_version = self.database.schema_version()
            if schema_version > SCHEMA_VERSION:
                checks["schema"] = f"unsupported newer schema {schema_version}"
                healthy = False
            elif schema_version < SCHEMA_VERSION:
                checks["schema"] = f"outdated schema {schema_version}"
                healthy = False
            else:
                checks["schema"] = "ok"
        except sqlite3.DatabaseError as exc:
            checks["schema"] = str(exc)
            healthy = False
        return HealthReport(healthy, schema_version, checks)
