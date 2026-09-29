from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from tests.helpers import REPO_ROOT, TemporaryDirectoryMixin

from projectos.contextos_adapter import ContextOSManifestAdapter
from projectos.discovery import DiscoveryFinding, DiscoveryService
from projectos.errors import ValidationError
from projectos.repositories import LocationRepository, ProjectRepository, ResourceRepository


FIXTURES = REPO_ROOT / "tests" / "fixtures"


class StaticAdapter:
    name = "static"

    def __init__(self, findings: list[DiscoveryFinding]):
        self.findings = findings

    def scan(self):
        return iter(self.findings)


class DiscoveryTests(TemporaryDirectoryMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.database = self.open_database()
        self.service = DiscoveryService(self.database)
        self.projects_dir = self.temp_path / "projects"
        self.projects_dir.mkdir()

    def copy_manifest(self, fixture: str = "contextos-project.json", name: str = "one") -> Path:
        project_dir = self.projects_dir / name
        project_dir.mkdir()
        target = project_dir / "project.json"
        shutil.copyfile(FIXTURES / fixture, target)
        return target

    def adapter(self) -> ContextOSManifestAdapter:
        return ContextOSManifestAdapter(self.projects_dir, machine_id="mac-mini")

    def test_contextos_adapter_maps_project_without_mutating_catalog(self) -> None:
        self.copy_manifest()

        findings = list(self.adapter().scan())

        self.assertEqual(1, len(findings))
        self.assertEqual("contextos:context-os-v3", findings[0].finding_key)
        self.assertTrue(findings[0].proposed["project"]["context_os_registered"])
        self.assertEqual("/opt/context-os", findings[0].proposed["locations"][0]["path"])
        self.assertEqual(0, len(ProjectRepository(self.database).list()))

    def test_discovery_records_provenance_and_evidence(self) -> None:
        manifest = self.copy_manifest()

        result = self.service.run(self.adapter(), source_run_id="scan-1")
        stored = self.service.get(result.findings[0].finding_id)

        self.assertEqual("mac-mini", stored.provenance["machine_id"])
        self.assertEqual(str(manifest), stored.evidence[0]["path"])
        self.assertEqual("CANDIDATE", stored.status)

    def test_repeated_scan_is_idempotent(self) -> None:
        self.copy_manifest()

        first = self.service.run(self.adapter(), source_run_id="scan-1")
        second = self.service.run(self.adapter(), source_run_id="scan-2")

        count = self.database.connection.execute(
            "SELECT COUNT(*) FROM discovery_findings"
        ).fetchone()[0]
        self.assertEqual((1, 0), (first.created_count, first.existing_count))
        self.assertEqual((0, 1), (second.created_count, second.existing_count))
        self.assertEqual(1, count)

    def test_changed_manifest_creates_new_candidate_version(self) -> None:
        path = self.copy_manifest()
        self.service.run(self.adapter(), source_run_id="scan-1")
        payload = json.loads(path.read_text())
        payload["name"] = "Context OS Fourth Edition"
        path.write_text(json.dumps(payload))

        result = self.service.run(self.adapter(), source_run_id="scan-2")

        rows = self.database.connection.execute(
            "SELECT content_hash FROM discovery_findings WHERE finding_key=?",
            ("contextos:context-os-v3",),
        ).fetchall()
        self.assertEqual(1, result.created_count)
        self.assertEqual(2, len(rows))
        self.assertEqual(2, len({row[0] for row in rows}))

    def test_apply_candidate_uses_repository_transaction(self) -> None:
        self.copy_manifest()
        finding = self.service.run(self.adapter(), "scan-1").findings[0]

        applied = self.service.apply(finding.finding_id, actor="owner@example.com")

        project = ProjectRepository(self.database).get(applied.project_id)
        self.assertEqual("Context OS V3", project.name)
        self.assertEqual(1, len(LocationRepository(self.database).list(project.project_id)))
        self.assertEqual(1, len(ResourceRepository(self.database).list(project.project_id)))
        self.assertEqual("APPLIED", self.service.get(finding.finding_id).status)

    def test_apply_candidate_rolls_back_all_repository_writes_on_failure(self) -> None:
        finding = DiscoveryFinding.new(
            finding_key="contextos:broken",
            entity_type="project_bundle",
            proposed={
                "project": {
                    "slug": "broken",
                    "name": "Broken",
                    "project_type": "LOCAL",
                    "visibility": "PRIVATE",
                    "source_key": "contextos:broken",
                },
                "locations": [
                    {"machine_id": "mac-mini", "location_type": "LOCAL", "path": "/tmp/broken"}
                ],
                "resources": [{"provider": "GOOGLE", "name": "Missing type"}],
            },
            evidence=[],
            provenance={"adapter": "test"},
        )
        stored = self.service.run(StaticAdapter([finding]), "broken-scan").findings[0]

        with self.assertRaises(KeyError):
            self.service.apply(stored.finding_id, actor="owner")

        self.assertEqual([], ProjectRepository(self.database).list())
        self.assertEqual("CANDIDATE", self.service.get(stored.finding_id).status)

    def test_reject_candidate_preserves_history(self) -> None:
        self.copy_manifest()
        finding = self.service.run(self.adapter(), "scan-1").findings[0]

        rejected = self.service.reject(finding.finding_id, "owner", "not a managed project")

        self.assertEqual("REJECTED", rejected.status)
        self.assertEqual("not a managed project", rejected.resolution_reason)
        self.assertEqual(1, self.database.connection.execute(
            "SELECT COUNT(*) FROM discovery_findings"
        ).fetchone()[0])

    def test_secret_material_in_candidate_is_rejected_before_persistence(self) -> None:
        finding = DiscoveryFinding.new(
            finding_key="unsafe",
            entity_type="project",
            proposed={"project": {"name": "Unsafe", "api_token": "secret-value"}},
            evidence=[],
            provenance={"adapter": "test"},
        )

        with self.assertRaises(ValidationError):
            self.service.run(StaticAdapter([finding]), "unsafe-scan")

        self.assertEqual(0, self.database.connection.execute(
            "SELECT COUNT(*) FROM discovery_findings"
        ).fetchone()[0])
        self.assertEqual(0, self.database.connection.execute(
            "SELECT COUNT(*) FROM discovery_runs"
        ).fetchone()[0])

    def test_missing_or_malformed_manifest_is_a_non_destructive_finding(self) -> None:
        self.copy_manifest()
        (self.projects_dir / "missing").mkdir()
        malformed = self.projects_dir / "malformed"
        malformed.mkdir()
        (malformed / "project.json").write_text("{not json")

        result = self.service.run(self.adapter(), "scan-errors")

        self.assertEqual(3, len(result.findings))
        self.assertEqual(2, result.error_count)
        self.assertEqual(0, len(ProjectRepository(self.database).list()))
        self.assertEqual(
            {"CANDIDATE", "ERROR"}, {finding.status for finding in result.findings}
        )


if __name__ == "__main__":
    unittest.main()
