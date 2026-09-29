from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import REPO_ROOT

if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from projectos.database import ProjectOSDatabase
from projectos.errors import ValidationError
from projectos.google.types import UserCreate, UserRole
from projectos.looker.analytics import LookerAnalyticsService
from projectos.looker.evidence import LookerEvidenceBuilder, verify_intake_archive
from projectos.looker.importer import LookerImporter
from projectos.repositories import ProjectRepository
from projectos.sync.authorization import AuthorizationService
from projectos.types import ProjectCreate, ProjectType, ProjectVisibility
from projectos.users import UserRepository


class LookerReconcileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup); root = Path(self.temporary.name)
        self.database = ProjectOSDatabase(root / "db.sqlite").initialize(); self.addCleanup(self.database.close)
        users = UserRepository(self.database, "owner@example.com"); users.seed_owner("owner@example.com", "Owner")
        users.create(UserCreate("admin@example.com", "Admin", UserRole.ADMIN), "owner@example.com"); users.create(UserCreate("user@example.com", "User", UserRole.USER), "owner@example.com")
        self.authorization = AuthorizationService(self.database, "owner@example.com")
        self.project = ProjectRepository(self.database).create(ProjectCreate("looker", "Looker", ProjectType.LOOKER, ProjectVisibility.PUBLIC), "owner@example.com")
        sections = {name: {"format": name, "items": []} for name in ("repository", "looker-assets", "looker-relationships", "legacy-tracker", "automation", "validation", "credential-references", "findings")}
        sections["repository"] = {"format": "repository-v1", "git": {"head": "a" * 40, "branch": "main", "dirty": False, "behind": 0, "ahead": 0, "remote": "origin", "primary_branch": "main"}}
        sections["looker-assets"]["items"] = [{"asset_type": "view", "name": "orders", "source_path": "orders.view.lkml", "content_sha256": "b" * 64, "parser_version": "1.0.0", "line": 1}]
        archive = root / "intake.zip"; LookerEvidenceBuilder().build("machine", "macos", "run-1", "1" * 64, "2" * 64, "3" * 64, sections, archive)
        LookerImporter(self.database).import_archive(self.project.project_id, verify_intake_archive(archive), "owner@example.com")
        self.analytics = LookerAnalyticsService(self.database); self.version = self.analytics.build(self.project.project_id, "run-1")

    def matching_snapshot(self):
        summary = self.analytics.summary(self.project.project_id, self.version.version)
        return {
            "asset_counts": summary["asset_counts"],
            "relationships": {},
            "findings": {"duplicate_count": 0, "orphan:view:orders": True, "unresolved_count": 0},
            "dashboards": {"count": 0},
            "tracker_mappings": summary["legacy"],
            "validation": {"code_status": "PASS", "failed": 0, "passed": 0},
            "refresh": {"status": "UNAVAILABLE"},
            "credential_usage": summary["credential_usage"],
        }

    def test_stage_compares_every_required_dimension_and_is_idempotent(self):
        from projectos.looker.reconcile import LookerReconciler, ReconciliationPolicy
        service = LookerReconciler(self.database); policy = ReconciliationPolicy.default()
        first = service.stage(self.project.project_id, "run-1", 1, self.matching_snapshot(), policy, "owner@example.com")
        second = service.stage(self.project.project_id, "run-1", 1, self.matching_snapshot(), policy, "owner@example.com")
        self.assertEqual(first.reconciliation_id, second.reconciliation_id); self.assertTrue(first.ready); self.assertEqual("READY", first.status)
        self.assertEqual(set(policy.required_dimensions), {item.dimension for item in first.items})
        self.assertTrue(all(item.outcome == "MATCH" for item in first.items))

    def test_stage_records_mismatch_missing_source_and_missing_target_and_changed_policy(self):
        from projectos.looker.reconcile import LookerReconciler, ReconciliationPolicy
        snapshot = self.matching_snapshot(); snapshot["asset_counts"]["view"] = 2; snapshot["asset_counts"]["legacy_only"] = 1; del snapshot["asset_counts"]["file"]
        service = LookerReconciler(self.database); report = service.stage(self.project.project_id, "run-1", 1, snapshot, ReconciliationPolicy.default(), "owner@example.com")
        outcomes = {(item.dimension, item.item_key): item.outcome for item in report.items}
        self.assertEqual("MISMATCH", outcomes[("asset_counts", "view")]); self.assertEqual("MISSING_SOURCE", outcomes[("asset_counts", "legacy_only")]); self.assertEqual("MISSING_TARGET", outcomes[("asset_counts", "file")]); self.assertFalse(report.ready)
        optional = ReconciliationPolicy(("asset_counts",), ("relationships", "findings", "dashboards", "tracker_mappings", "validation", "refresh", "credential_usage"))
        changed = service.stage(self.project.project_id, "run-1", 1, snapshot, optional, "owner@example.com")
        self.assertNotEqual(report.reconciliation_id, changed.reconciliation_id); self.assertNotEqual(report.policy_sha256, changed.policy_sha256)

    def test_owner_waiver_creates_new_immutable_report_and_admin_user_cannot_waive(self):
        from projectos.looker.reconcile import LookerReconciler, ReconciliationPolicy
        snapshot = self.matching_snapshot(); snapshot["refresh"]["status"] = "STALE"
        service = LookerReconciler(self.database); report = service.stage(self.project.project_id, "run-1", 1, snapshot, ReconciliationPolicy.default(), "owner@example.com")
        for email in ("admin@example.com", "user@example.com"):
            with self.assertRaisesRegex(ValidationError, "Owner"):
                service.waive(report.reconciliation_id, "refresh", "status", "accepted fixture drift", self.authorization.resolve(email))
        waived = service.waive(report.reconciliation_id, "refresh", "status", "accepted fixture drift", self.authorization.resolve("owner@example.com"))
        self.assertTrue(waived.ready); self.assertNotEqual(report.reconciliation_id, waived.reconciliation_id)
        self.assertEqual("MISMATCH", next(item.outcome for item in service.report(report.reconciliation_id).items if item.dimension == "refresh" and item.item_key == "status"))
        self.assertEqual("WAIVED", next(item.outcome for item in waived.items if item.dimension == "refresh" and item.item_key == "status"))
        self.assertEqual(1, self.database.connection.execute("SELECT COUNT(*) FROM audit_events WHERE event_type='looker.reconciliation.waived'").fetchone()[0])

    def test_invalid_policy_duplicate_snapshot_mixed_version_and_missing_provenance_fail_closed(self):
        from projectos.looker.reconcile import LookerReconciler, ReconciliationPolicy
        with self.assertRaises(ValidationError): ReconciliationPolicy(("asset_counts", "asset_counts"), ())
        duplicate = self.matching_snapshot(); duplicate["asset_counts"] = [{"key": "view", "value": 1}, {"key": "view", "value": 1}]
        with self.assertRaisesRegex(ValidationError, "duplicate"):
            LookerReconciler(self.database).stage(self.project.project_id, "run-1", 1, duplicate, ReconciliationPolicy.default(), "owner@example.com")
        self.database.connection.execute("UPDATE looker_analytics SET source_run_id='wrong-run' WHERE analytic_type='LOOKER_GRAPH'")
        with self.assertRaisesRegex(ValidationError, "provenance"):
            LookerReconciler(self.database).stage(self.project.project_id, "run-1", 1, self.matching_snapshot(), ReconciliationPolicy.default(), "owner@example.com")
        with self.assertRaisesRegex(ValidationError, "version"):
            LookerReconciler(self.database).stage(self.project.project_id, "run-1", 99, self.matching_snapshot(), ReconciliationPolicy.default(), "owner@example.com")


if __name__ == "__main__":
    unittest.main()
