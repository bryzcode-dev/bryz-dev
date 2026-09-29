from __future__ import annotations

import tempfile
import unittest
import sys
from pathlib import Path
from uuid import uuid4

from tests.helpers import REPO_ROOT

if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from projectos.database import ProjectOSDatabase
from projectos.looker.analytics import LookerAnalyticsService
from projectos.looker.evidence import LookerEvidenceBuilder, verify_intake_archive
from projectos.looker.importer import LookerImporter
from projectos.repositories import ProjectRepository
from projectos.sync.projection import ProjectionBuilder
from projectos.types import ProjectCreate, ProjectType, ProjectVisibility


class LookerProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup); self.root = Path(self.temporary.name)
        self.database = ProjectOSDatabase(self.root / "db.sqlite").initialize(); self.addCleanup(self.database.close)
        projects = ProjectRepository(self.database)
        self.public = projects.create(ProjectCreate("public-looker", "Public Looker", ProjectType.LOOKER, ProjectVisibility.PUBLIC), "owner")
        self.private = projects.create(ProjectCreate("private-looker", "Private Looker", ProjectType.LOOKER, ProjectVisibility.PRIVATE), "owner")

    def import_project(self, project, run_id, asset_name):
        sections = {name: {"format": name, "items": []} for name in ("repository", "looker-assets", "looker-relationships", "legacy-tracker", "automation", "validation", "credential-references", "findings")}
        sections["repository"] = {"format": "repository-v1", "git": {"head": "a" * 40, "branch": "main", "dirty": False, "behind": 0, "ahead": 0, "remote": "origin", "primary_branch": "main"}}
        sections["looker-assets"]["items"] = [{"asset_type": "view", "name": asset_name, "source_path": f"{asset_name}.view.lkml", "content_sha256": "b" * 64, "parser_version": "1.0.0", "line": 1}]
        archive = self.root / f"{run_id}.zip"; LookerEvidenceBuilder().build("machine", "windows", run_id, "1" * 64, "2" * 64, "3" * 64, sections, archive)
        LookerImporter(self.database).import_archive(project.project_id, verify_intake_archive(archive), "owner")
        LookerAnalyticsService(self.database).build(project.project_id, run_id)

    def test_projection_includes_looker_contract_rows_with_stable_hashes(self):
        self.import_project(self.public, "public-run", "public_orders")
        bundle = ProjectionBuilder().build(self.database.connection, uuid4())
        self.assertEqual({"Looker_Assets", "Looker_Relationships", "Looker_Findings", "Looker_Analytics"}, {name for name in bundle.tabs if name.startswith("Looker_")})
        self.assertEqual("public_orders", bundle.tabs["Looker_Assets"][0]["name"])
        self.assertTrue(all(len(row["row_hash"]) == 64 for name in bundle.tabs if name.startswith("Looker_") for row in bundle.tabs[name]))

    def test_public_projection_excludes_private_assets_graph_findings_and_aggregates(self):
        self.import_project(self.public, "public-run", "public_orders")
        self.import_project(self.private, "private-run", "private_payroll")
        bundle = ProjectionBuilder().build(self.database.connection, uuid4())
        rendered = repr(bundle.public_tabs)
        self.assertIn("public_orders", rendered)
        self.assertNotIn("private_payroll", rendered)
        self.assertNotIn(str(self.private.project_id), rendered)
        for name in ("Looker_Assets", "Looker_Relationships", "Looker_Findings", "Looker_Analytics"):
            self.assertTrue(all(row["project_id"] == str(self.public.project_id) for row in bundle.public_tabs[name]))


if __name__ == "__main__":
    unittest.main()
