from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .discovery import DiscoveryFinding
from .database import ProjectOSDatabase
from .errors import ValidationError
from .looker.analytics import LookerAnalyticsService
from .looker.reconcile import LookerReconciler
from .looker.repository import LookerRepository


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "unnamed-project"


class ContextOSManifestAdapter:
    name = "contextos_manifest"

    def __init__(self, projects_dir: Path, machine_id: str):
        self.projects_dir = Path(projects_dir)
        self.machine_id = machine_id

    def scan(self):
        if not self.projects_dir.exists():
            yield self._error(self.projects_dir, "projects directory does not exist")
            return
        for project_dir in sorted(path for path in self.projects_dir.iterdir() if path.is_dir()):
            manifest_path = project_dir / "project.json"
            if not manifest_path.is_file():
                yield self._error(manifest_path, "project manifest is missing")
                continue
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                yield self._map(payload, manifest_path)
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                yield self._error(manifest_path, f"invalid project manifest: {exc}")

    def _map(self, payload: dict[str, Any], manifest_path: Path) -> DiscoveryFinding:
        project_id = str(payload["project_id"])
        name = str(payload["name"])
        project = {
            "slug": str(payload.get("slug") or _slug(project_id or name)),
            "name": name,
            "description": str(payload.get("description", "")),
            "project_type": str(payload.get("project_type", "LOCAL")).upper(),
            "status": str(payload.get("status", "ACTIVE")).upper(),
            "visibility": str(payload.get("visibility", "PRIVATE")).upper(),
            "context_os_registered": True,
            "context_os_project_id": project_id,
            "tags": list(payload.get("types", ())),
            "source_key": f"contextos:{project_id}",
        }
        locations = []
        if payload.get("path"):
            locations.append(
                {
                    "machine_id": self.machine_id,
                    "location_type": "LOCAL_PROJECT",
                    "path": str(payload["path"]),
                    "repository_root": payload.get("repository_root"),
                }
            )
        resources = []
        for raw in payload.get("resources", ()):
            resources.append(
                {
                    "resource_type": str(raw["resource_type"]),
                    "provider": str(raw["provider"]),
                    "external_id": raw.get("external_id"),
                    "name": str(raw["name"]),
                    "url": raw.get("url"),
                    "environment": str(raw.get("environment", "")),
                    "role": str(raw.get("role", "USES")),
                    "metadata": dict(raw.get("metadata", {})),
                }
            )
        provenance = {
            "adapter": self.name,
            "machine_id": self.machine_id,
            "manifest_path": str(manifest_path),
        }
        return DiscoveryFinding.new(
            finding_key=f"contextos:{project_id}",
            entity_type="project_bundle",
            proposed={"project": project, "locations": locations, "resources": resources},
            evidence=[{"path": str(manifest_path), "kind": "contextos_project_manifest"}],
            provenance=provenance,
        )

    def _error(self, path: Path, message: str) -> DiscoveryFinding:
        return DiscoveryFinding.new(
            finding_key=f"contextos-error:{path}",
            entity_type="source_error",
            proposed={"source_path": str(path), "message": message},
            evidence=[{"path": str(path), "kind": "manifest_error"}],
            provenance={"adapter": self.name, "machine_id": self.machine_id},
            status="ERROR",
        )


class ProjectOSQueryAdapter:
    """Bounded read-only query surface exposed to an adopted ContextOS skill."""

    _CAPABILITIES = {
        "looker-status",
        "looker-assets",
        "looker-dependencies",
        "looker-findings",
        "looker-impact",
        "looker-reconciliation",
    }

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

    @staticmethod
    def _latest(database: ProjectOSDatabase, project_id: str) -> tuple[str, int, dict[str, object]]:
        rows = database.connection.execute(
            "SELECT value_json,source_run_id FROM looker_analytics "
            "WHERE project_id=? AND analytic_type='LOOKER_SUMMARY' ORDER BY created_at,analytic_id",
            (project_id,),
        ).fetchall()
        if not rows:
            raise ValidationError("Looker analytics are unavailable")
        value = json.loads(rows[-1]["value_json"])
        return rows[-1]["source_run_id"], int(value["version"]), value["data"]

    def query(self, capability: str, project_id: str, **arguments: object) -> object:
        if capability not in self._CAPABILITIES:
            raise ValidationError("ContextOS query capability is not allowlisted")
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValidationError("project_id is required")
        expected_arguments = (
            {"node"}
            if capability in {"looker-dependencies", "looker-impact"}
            else {"reconciliation_id"}
            if capability == "looker-reconciliation"
            else set()
        )
        if set(arguments) != expected_arguments:
            raise ValidationError("ContextOS query arguments are invalid")
        database = ProjectOSDatabase.open_existing(self.database_path, read_only=True)
        try:
            run_id, version, summary = self._latest(database, project_id)
            repository = LookerRepository(database)
            analytics = LookerAnalyticsService(database)
            if capability == "looker-status":
                return {"analytic_version": version, "intake_run_id": run_id, **summary}
            if capability == "looker-assets":
                return [
                    {
                        "asset_type": row["asset_type"],
                        "name": row["name"],
                        "file_path": row["file_path"],
                        "source_line": row["source_line"],
                        "parser_version": row["parser_version"],
                    }
                    for row in repository.assets(project_id, run_id)
                ]
            if capability == "looker-findings":
                return [
                    {
                        "severity": row["severity"],
                        "category": row["category"],
                        "code": row["code"],
                        "subject": row["subject"],
                        "status": row["status"],
                        "source_path": row["source_path"],
                        "source_line": row["source_line"],
                    }
                    for row in repository.findings(project_id, run_id)
                ]
            if capability in {"looker-dependencies", "looker-impact"}:
                node = arguments.get("node")
                if not isinstance(node, str) or not node.strip():
                    raise ValidationError("node is required")
                return (
                    analytics.dependencies(project_id, node)
                    if capability == "looker-dependencies"
                    else analytics.impact(project_id, node)
                )
            reconciliation_id = arguments.get("reconciliation_id")
            if not isinstance(reconciliation_id, str) or not reconciliation_id.strip():
                raise ValidationError("reconciliation_id is required")
            report = LookerReconciler(database).report(reconciliation_id)
            if report.project_id != project_id:
                raise ValidationError("reconciliation does not belong to project")
            return report
        finally:
            database.close()
