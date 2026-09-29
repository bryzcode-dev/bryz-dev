from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from tests.helpers import REPO_ROOT

if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from projectos.bindings import GoogleBindingRepository
from projectos.credentials import CredentialReferenceCreate, CredentialReferenceService
from projectos.database import ProjectOSDatabase
from projectos.errors import ValidationError
from projectos.google.types import GoogleBindingCreate
from projectos.looker.analytics import LookerAnalyticsService
from projectos.looker.evidence import LookerEvidenceBuilder, verify_intake_archive
from projectos.looker.importer import LookerImporter
from projectos.looker.reconcile import LookerReconciler, ReconciliationPolicy
from projectos.repositories import ProjectRepository
from projectos.types import ProjectCreate, ProjectType, ProjectVisibility


class LookerRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup); self.root = Path(self.temporary.name)
        self.path = self.root / "db.sqlite"; self.database = ProjectOSDatabase(self.path).initialize(); self.addCleanup(self.database.close)
        self.project = ProjectRepository(self.database).create(ProjectCreate("looker", "Looker", ProjectType.LOOKER, ProjectVisibility.PUBLIC), "owner")
        sections = {name: {"format": name, "items": []} for name in ("repository", "looker-assets", "looker-relationships", "legacy-tracker", "automation", "validation", "credential-references", "findings")}
        sections["repository"] = {"format": "repository-v1", "git": {"head": "a" * 40, "branch": "main", "dirty": False, "behind": 0, "ahead": 0, "remote": "origin", "primary_branch": "main"}}
        sections["looker-assets"]["items"] = [{"asset_type": "view", "name": "orders", "source_path": "orders.view.lkml", "content_sha256": "b" * 64, "parser_version": "1.0.0", "line": 1}]
        sections["validation"]["items"] = [{"command_id": "tests", "passed": True, "returncode": 0, "timed_out": False, "parser": "TEST_SUMMARY", "summary": "passed=1"}]
        archive = self.root / "intake.zip"; LookerEvidenceBuilder().build("machine", "windows", "run-1", "1" * 64, "2" * 64, "3" * 64, sections, archive)
        LookerImporter(self.database).import_archive(self.project.project_id, verify_intake_archive(archive), "owner")
        analytics = LookerAnalyticsService(self.database); analytics.build(self.project.project_id, "run-1"); summary = analytics.summary(self.project.project_id, 1)
        snapshot = {"asset_counts": summary["asset_counts"], "relationships": {}, "findings": {"duplicate_count": 0, "orphan:view:orders": True, "unresolved_count": 0}, "dashboards": {"count": 0}, "tracker_mappings": summary["legacy"], "validation": {"code_status": "PASS", "failed": 0, "passed": 1}, "refresh": {"status": "UNAVAILABLE"}, "credential_usage": summary["credential_usage"]}
        self.reconciliation = LookerReconciler(self.database).stage(self.project.project_id, "run-1", 1, snapshot, ReconciliationPolicy.default(), "owner")
        credential = CredentialReferenceService(self.database).create(CredentialReferenceCreate("GOOGLE", "refresh", "ADC", "refresh", "KEYCHAIN", "projectos/refresh"), "owner")
        self.binding = GoogleBindingRepository(self.database).create(GoogleBindingCreate("DEV", "sheet", "ProjectOS", 1, credential.credential_id, enabled=True, write_enabled=True), "owner")
        self.revision = str(uuid4()); self.sync_run = str(uuid4())
        self.database.connection.execute("INSERT INTO projection_revisions(revision_id,binding_id,schema_version,snapshot_hash,entity_counts_json,state,started_at,verified_at,activated_at) VALUES(?,?,?,?,?,'ACTIVE','t','t','t')", (self.revision, str(self.binding.binding_id), 1, "c" * 64, "{}"))
        self.database.connection.execute("INSERT INTO sync_runs(run_id,trigger,status,started_at,finished_at,summary_json,binding_id,starting_checkpoint,ending_checkpoint) VALUES(?,'skill','COMPLETE','t','t','{}',?,'before','after')", (self.sync_run, str(self.binding.binding_id)))

    def receipt(self, **changes):
        value = {"receipt_version": 1, "support_state": "REAL", "project_id": str(self.project.project_id), "intake_run_id": "run-1", "analytic_version": 1, "reconciliation_id": self.reconciliation.reconciliation_id, "binding_id": str(self.binding.binding_id), "sync_run_id": self.sync_run, "projection_revision_id": self.revision, "validation_command_ids": ["tests"], "source_revision": "a" * 40, "refreshed_at": "2026-09-27T12:00:00Z"}
        value.update(changes); return value

    def test_real_bound_receipt_verifies_without_mutating_database(self):
        from projectos.looker.refresh import RefreshReceipt
        before = self.path.read_bytes(); verified = RefreshReceipt.from_mapping(self.receipt()).verify(self.database)
        self.assertTrue(verified.ok); self.assertEqual(64, len(verified.sha256)); self.assertEqual(before, self.path.read_bytes())

    def test_simulated_unbound_mixed_and_failed_validation_receipts_fail_closed(self):
        from projectos.looker.refresh import RefreshReceipt
        cases = (self.receipt(support_state="SIMULATED"), self.receipt(projection_revision_id=str(uuid4())), self.receipt(analytic_version=2), self.receipt(source_revision="b" * 40))
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValidationError): RefreshReceipt.from_mapping(value).verify(self.database)
        self.database.connection.execute("UPDATE looker_validation_results SET passed=0 WHERE command_id='tests'")
        with self.assertRaisesRegex(ValidationError, "validation"): RefreshReceipt.from_mapping(self.receipt()).verify(self.database)

    def test_contextos_looker_adapter_is_read_only_and_rejects_state_changes(self):
        from projectos.contextos_adapter import ProjectOSQueryAdapter
        self.database.close(); before = self.path.read_bytes(); adapter = ProjectOSQueryAdapter(self.path)
        status = adapter.query("looker-status", str(self.project.project_id)); assets = adapter.query("looker-assets", str(self.project.project_id)); dependencies = adapter.query("looker-dependencies", str(self.project.project_id), node="view:orders")
        findings = adapter.query("looker-findings", str(self.project.project_id)); impact = adapter.query("looker-impact", str(self.project.project_id), node="view:orders"); reconciliation = adapter.query("looker-reconciliation", str(self.project.project_id), reconciliation_id=self.reconciliation.reconciliation_id)
        self.assertEqual(1, status["analytic_version"]); self.assertEqual("orders", assets[0]["name"]); self.assertEqual(("view:orders",), dependencies); self.assertEqual([], findings); self.assertEqual(("view:orders",), impact); self.assertTrue(reconciliation.ready)
        with self.assertRaises(ValidationError): adapter.query("looker-refresh", str(self.project.project_id))
        self.assertEqual(before, self.path.read_bytes()); self.assertFalse(Path(f"{self.path}-wal").exists()); self.assertFalse(Path(f"{self.path}-shm").exists())


if __name__ == "__main__":
    unittest.main()
