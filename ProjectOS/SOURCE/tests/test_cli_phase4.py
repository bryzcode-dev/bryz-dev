from __future__ import annotations

import gc
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tests.helpers import REPO_ROOT

if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from projectos.cli import build_parser, main
from projectos.database import ProjectOSDatabase
from projectos.errors import ValidationError
from projectos.google.types import UserCreate, UserRole
from projectos.looker.evidence import LookerEvidenceBuilder
from projectos.repositories import ProjectRepository
from projectos.types import ProjectCreate, ProjectType, ProjectVisibility
from projectos.users import UserRepository


class Phase4CliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "projectos.sqlite"
        database = ProjectOSDatabase(self.db_path).initialize()
        users = UserRepository(database, "owner@example.com")
        users.seed_owner("owner@example.com", "Owner")
        users.create(UserCreate("admin@example.com", "Admin", UserRole.ADMIN), "owner@example.com")
        self.public = ProjectRepository(database).create(ProjectCreate("public-looker", "Public Looker", ProjectType.LOOKER, ProjectVisibility.PUBLIC), "owner@example.com")
        self.private = ProjectRepository(database).create(ProjectCreate("private-looker", "Private Looker", ProjectType.LOOKER, ProjectVisibility.PRIVATE), "owner@example.com")
        database.close()
        sections = {name: {"format": name, "items": []} for name in ("repository", "looker-assets", "looker-relationships", "legacy-tracker", "automation", "validation", "credential-references", "findings")}
        sections["repository"] = {"format": "repository-v1", "git": {"head": "a" * 40, "branch": "main", "dirty": False, "behind": 0, "ahead": 0, "remote": "origin", "primary_branch": "main"}}
        sections["looker-assets"]["items"] = [{"asset_type": "view", "name": "orders", "source_path": "orders.view.lkml", "content_sha256": "b" * 64, "parser_version": "1.0.0", "line": 1}]
        self.archive = self.root / "intake.zip"
        LookerEvidenceBuilder().build("machine", "macos", "run-1", "1" * 64, "2" * 64, "3" * 64, sections, self.archive)

    def invoke(self, *arguments, include_db=True):
        argv = (["--db", str(self.db_path)] if include_db else []) + list(arguments)
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv)
            gc.collect()
        self.assertEqual("", stderr.getvalue())
        lines = [line for line in stdout.getvalue().splitlines() if line]
        self.assertEqual(1, len(lines))
        return code, json.loads(lines[0]), stdout.getvalue()

    def test_verify_and_preview_are_database_free_single_json_documents(self):
        absent = self.root / "must-not-exist.sqlite"
        code, verified, raw = self.invoke("looker", "intake", "verify", str(self.archive), include_db=False)
        self.assertEqual(0, code); self.assertTrue(verified["ok"]); self.assertNotIn("Traceback", raw)
        code, preview, _ = self.invoke("looker", "intake", "preview", str(self.archive), include_db=False)
        self.assertEqual(0, code); self.assertEqual(1, preview["data"]["asset_count"]); self.assertFalse(absent.exists())

    def test_import_and_build_require_explicit_database_and_owner(self):
        code, payload, _ = self.invoke("looker", "intake", "import", str(self.archive), str(self.public.project_id), "--owner-email", "owner@example.com", "--actor", "owner@example.com", include_db=False)
        self.assertEqual(2, code); self.assertIn("explicit database", payload["errors"][0]["message"])
        code, payload, _ = self.invoke("looker", "intake", "import", str(self.archive), str(self.public.project_id), "--owner-email", "owner@example.com", "--actor", "admin@example.com")
        self.assertEqual(2, code); self.assertEqual("validation_error", payload["errors"][0]["code"])
        code, imported, _ = self.invoke("looker", "intake", "import", str(self.archive), str(self.public.project_id), "--owner-email", "owner@example.com", "--actor", "owner@example.com")
        self.assertEqual(0, code); self.assertEqual("run-1", imported["data"]["intake_run_id"])
        code, built, _ = self.invoke("looker", "analytics", "build", str(self.public.project_id), "run-1", "--owner-email", "owner@example.com", "--actor", "owner@example.com")
        self.assertEqual(0, code); self.assertEqual(1, built["data"]["version"])

    def test_show_filters_private_projects_and_never_accepts_role_claims(self):
        self.invoke("looker", "intake", "import", str(self.archive), str(self.public.project_id), "--owner-email", "owner@example.com", "--actor", "owner@example.com")
        self.invoke("looker", "analytics", "build", str(self.public.project_id), "run-1", "--owner-email", "owner@example.com", "--actor", "owner@example.com")
        code, shown, _ = self.invoke("looker", "analytics", "show", str(self.public.project_id), "--owner-email", "owner@example.com", "--actor", "admin@example.com")
        self.assertEqual(0, code); self.assertEqual(1, shown["data"]["asset_counts"]["view"])
        code, denied, raw = self.invoke("looker", "analytics", "show", str(self.private.project_id), "--owner-email", "owner@example.com", "--actor", "admin@example.com")
        self.assertEqual(2, code); self.assertNotIn("Private Looker", raw); self.assertEqual("Looker analytics are unavailable", denied["errors"][0]["message"])
        with self.assertRaises(ValidationError):
            build_parser().parse_args(["looker", "analytics", "show", str(self.public.project_id), "--owner-email", "owner@example.com", "--actor", "admin@example.com", "--role", "OWNER"])

    def test_looker_cli_has_no_force_purge_or_sql_options(self):
        parser = build_parser()
        for unsafe in ("--force", "--purge", "--sql"):
            with self.assertRaises(ValidationError):
                parser.parse_args(["looker", "intake", "verify", str(self.archive), unsafe])

    def test_reconciliation_stage_report_and_owner_only_waiver_are_json(self):
        self.invoke("looker", "intake", "import", str(self.archive), str(self.public.project_id), "--owner-email", "owner@example.com", "--actor", "owner@example.com")
        self.invoke("looker", "analytics", "build", str(self.public.project_id), "run-1", "--owner-email", "owner@example.com", "--actor", "owner@example.com")
        _, shown, _ = self.invoke("looker", "analytics", "show", str(self.public.project_id), "--owner-email", "owner@example.com", "--actor", "owner@example.com")
        summary = shown["data"]
        snapshot = {"asset_counts": summary["asset_counts"], "relationships": {}, "findings": {"duplicate_count": 0, "orphan:view:orders": True, "unresolved_count": 0}, "dashboards": {"count": 0}, "tracker_mappings": summary["legacy"], "validation": {"code_status": "PASS", "failed": 0, "passed": 0}, "refresh": {"status": "STALE"}, "credential_usage": summary["credential_usage"]}
        policy = {"required_dimensions": ["asset_counts", "relationships", "findings", "dashboards", "tracker_mappings", "validation", "refresh", "credential_usage"], "optional_dimensions": []}
        snapshot_path = self.root / "legacy.json"; snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
        policy_path = self.root / "policy.json"; policy_path.write_text(json.dumps(policy), encoding="utf-8")
        code, staged, _ = self.invoke("looker", "reconcile", "stage", str(self.public.project_id), "run-1", "1", "--legacy-snapshot", str(snapshot_path), "--policy", str(policy_path), "--owner-email", "owner@example.com", "--actor", "owner@example.com")
        self.assertEqual(0, code); self.assertFalse(staged["data"]["ready"]); reconciliation_id = staged["data"]["reconciliation_id"]
        code, denied, _ = self.invoke("looker", "reconcile", "waive", reconciliation_id, "refresh", "status", "--reason", "fixture drift", "--owner-email", "owner@example.com", "--actor", "admin@example.com")
        self.assertEqual(2, code); self.assertEqual("validation_error", denied["errors"][0]["code"])
        code, waived, _ = self.invoke("looker", "reconcile", "waive", reconciliation_id, "refresh", "status", "--reason", "fixture drift", "--owner-email", "owner@example.com", "--actor", "owner@example.com")
        self.assertEqual(0, code); self.assertTrue(waived["data"]["ready"])
        code, report, _ = self.invoke("looker", "reconcile", "report", waived["data"]["reconciliation_id"], "--owner-email", "owner@example.com", "--actor", "owner@example.com")
        self.assertEqual(0, code); self.assertEqual("READY", report["data"]["status"])


if __name__ == "__main__":
    unittest.main()
