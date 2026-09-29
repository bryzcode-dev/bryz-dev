from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from projectos.database import ProjectOSDatabase, utc_now
from projectos.health import ProjectOSDoctor


@dataclass(frozen=True)
class DiagnosticManifest:
    manifest_path: Path
    files: tuple[Path, ...]
    sha256: str
    created_at: str


class DiagnosticBundleService:
    def __init__(self, database: ProjectOSDatabase):
        self.database = database

    def create(self, destination: Path) -> DiagnosticManifest:
        target = Path(destination)
        target.mkdir(parents=True, exist_ok=True)
        created_at = utc_now()
        health = ProjectOSDoctor(self.database).check()
        bindings = [
            {
                "environment": row["environment"],
                "contract_version": row["contract_version"],
                "enabled": bool(row["enabled"]),
                "write_enabled": bool(row["write_enabled"]),
                "status": row["status"],
            }
            for row in self.database.connection.execute(
                "SELECT environment,contract_version,enabled,write_enabled,status FROM google_bindings"
            )
        ]
        errors = [
            row["error_code"]
            for row in self.database.connection.execute(
                "SELECT error_code FROM sync_runs WHERE error_code IS NOT NULL ORDER BY started_at DESC LIMIT 20"
            )
        ]
        payload = {
            "kind": "projectos_diagnostic_v1",
            "created_at": created_at,
            "schema_version": self.database.schema_version(),
            "health": health.to_dict(),
            "bindings": bindings,
            "recent_error_codes": errors,
        }
        data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
        diagnostics_path = target / "diagnostics.json"
        temporary = target / ".diagnostics.json.tmp"
        temporary.write_bytes(data)
        os.replace(temporary, diagnostics_path)
        digest = hashlib.sha256(data).hexdigest()
        manifest_path = target / "manifest.json"
        manifest_data = (
            json.dumps(
                {
                    "kind": "projectos_diagnostic_manifest_v1",
                    "created_at": created_at,
                    "files": [{"name": diagnostics_path.name, "sha256": digest}],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        manifest_path.write_text(manifest_data, encoding="utf-8")
        return DiagnosticManifest(manifest_path, (diagnostics_path, manifest_path), digest, created_at)
