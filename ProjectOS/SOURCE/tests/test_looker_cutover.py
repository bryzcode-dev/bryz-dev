from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from tests.helpers import REPO_ROOT

if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from projectos.backup import BackupService
from projectos.bindings import GoogleBindingRepository
from projectos.credentials import CredentialReferenceCreate, CredentialReferenceService
from projectos.database import ProjectOSDatabase
from projectos.errors import ValidationError
from projectos.google.types import GoogleBindingCreate
from projectos.looker.analytics import LookerAnalyticsService
from projectos.looker.cutover import CutoverPreparationRequest, CutoverPreparer, CutoverTarget, verify_cutover_package
from projectos.looker.evidence import LookerEvidenceBuilder, verify_intake_archive
from projectos.looker.importer import LookerImporter
from projectos.looker.reconcile import LookerReconciler, ReconciliationPolicy
from projectos.looker.refresh import RefreshReceipt
from projectos.repositories import ProjectRepository
from projectos.types import ProjectCreate, ProjectType, ProjectVisibility
from projectos.users import UserRepository


class CutoverFixture:
    def build(self, root: Path):
        path = root / "projectos.sqlite"; database = ProjectOSDatabase(path).initialize()
        UserRepository(database, "owner@example.invalid").seed_owner("owner@example.invalid", "Owner")
        project = ProjectRepository(database).create(ProjectCreate("looker", "Looker", ProjectType.LOOKER, ProjectVisibility.PUBLIC), "owner@example.invalid")
        sections = {name: {"format": name, "items": []} for name in ("repository", "looker-assets", "looker-relationships", "legacy-tracker", "automation", "validation", "credential-references", "findings")}
        sections["repository"] = {"format": "repository-v1", "git": {"head": "a" * 40, "branch": "main", "dirty": False, "behind": 0, "ahead": 0, "remote": "origin", "primary_branch": "main"}}
        sections["looker-assets"]["items"] = [{"asset_type": "view", "name": "orders", "source_path": "orders.view.lkml", "content_sha256": "b" * 64, "parser_version": "1.0.0", "line": 1}]
        sections["validation"]["items"] = [{"command_id": "tests", "passed": True, "returncode": 0, "timed_out": False, "parser": "TEST_SUMMARY", "summary": "passed=1"}]
        archive = root / "intake.zip"; LookerEvidenceBuilder().build("machine", "windows", "run-1", "1" * 64, "2" * 64, "3" * 64, sections, archive)
        LookerImporter(database).import_archive(project.project_id, verify_intake_archive(archive), "owner@example.invalid")
        asset_id=database.connection.execute("SELECT looker_asset_id FROM looker_asset_occurrences WHERE intake_run_id='run-1'").fetchone()[0]
        database.connection.execute(
            "INSERT INTO looker_legacy_mappings VALUES(?,?,?,?,?,?,?,?)",
            (str(uuid4()), "run-1", str(project.project_id), "legacy:orders", "view", asset_id, "MATCHED", "{}"),
        )
        analytics = LookerAnalyticsService(database); analytics.build(project.project_id, "run-1"); summary = analytics.summary(project.project_id, 1)
        snapshot = {"asset_counts": summary["asset_counts"], "relationships": {}, "findings": {"duplicate_count": 0, "orphan:view:orders": True, "unresolved_count": 0}, "dashboards": {"count": 0}, "tracker_mappings": summary["legacy"], "validation": {"code_status": "PASS", "failed": 0, "passed": 1}, "refresh": {"status": "UNAVAILABLE"}, "credential_usage": summary["credential_usage"]}
        reconciliation = LookerReconciler(database).stage(project.project_id, "run-1", 1, snapshot, ReconciliationPolicy.default(), "owner@example.invalid")
        credential = CredentialReferenceService(database).create(CredentialReferenceCreate("GOOGLE", "cutover", "ADC", "cutover", "KEYCHAIN", "projectos/cutover"), "owner@example.invalid")
        binding = GoogleBindingRepository(database).create(GoogleBindingCreate("DEV", "sheet", "ProjectOS", 1, credential.credential_id, enabled=True, write_enabled=True), "owner@example.invalid")
        revision = str(uuid4()); sync_run = str(uuid4())
        database.connection.execute("INSERT INTO projection_revisions(revision_id,binding_id,schema_version,snapshot_hash,entity_counts_json,state,started_at,verified_at,activated_at) VALUES(?,?,?,?,?,'ACTIVE','t','t','t')", (revision, str(binding.binding_id), 1, "c" * 64, "{}"))
        database.connection.execute("INSERT INTO sync_runs(run_id,trigger,status,started_at,finished_at,summary_json,binding_id,starting_checkpoint,ending_checkpoint) VALUES(?,'skill','COMPLETE','t','t','{}',?,'before','after')", (sync_run, str(binding.binding_id)))
        receipt = RefreshReceipt.from_mapping({"receipt_version": 1, "support_state": "REAL", "project_id": str(project.project_id), "intake_run_id": "run-1", "analytic_version": 1, "reconciliation_id": reconciliation.reconciliation_id, "binding_id": str(binding.binding_id), "sync_run_id": sync_run, "projection_revision_id": revision, "validation_command_ids": ["tests"], "source_revision": "a" * 40, "refreshed_at": "2026-09-27T12:00:00Z"})
        backup = BackupService(database).create(root / "backup")
        legacy = root / "legacy"; legacy.mkdir(); (legacy / "tracker.json").write_text('{"legacy":true}\n'); (legacy / "sync.js").write_text("function sync() {}\n"); (legacy / "schedule.xml").write_text("<Task/>\n")
        target = CutoverTarget("legacy-sync", "WINDOWS_TASK", "owner-fingerprint", ("inspect-owner", "legacy-sync"), ("disable", "legacy-sync"), ("remove", "legacy-sync"), ("restore", "legacy-sync"))
        request = CutoverPreparationRequest(str(project.project_id), "run-1", reconciliation.reconciliation_id, receipt, backup.manifest_path, legacy, (target,), "owner@example.invalid", "owner@example.invalid", "2026-09-27T12:30:00Z", root / "cutover.zip")
        return database, request


class LookerCutoverTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup); self.root = Path(self.temporary.name)
        self.database, self.request = CutoverFixture().build(self.root); self.addCleanup(self.database.close)

    def test_prepare_is_deterministic_and_contains_permanent_legacy_checklist_and_rollback(self):
        first = CutoverPreparer(self.database).prepare(self.request)
        second = CutoverPreparer(self.database).prepare(replace(self.request, output_path=self.root / "second.zip"))
        self.assertEqual(first.sha256, second.sha256); self.assertEqual(first.path.read_bytes(), second.path.read_bytes())
        verified = verify_cutover_package(first.path); self.assertTrue(verified.ready); self.assertEqual("SIMULATED", verified.support_state)
        with zipfile.ZipFile(first.path) as archive:
            names = set(archive.namelist()); checklist = json.loads(archive.read("checklist.json")); rollback = json.loads(archive.read("rollback.json"))
        self.assertTrue({"manifest.json", "checklist.json", "rollback.json", "effect-plan.json", "legacy/tracker.json", "legacy/sync.js", "legacy/schedule.xml"}.issubset(names))
        self.assertTrue(all(checklist.values())); self.assertEqual(["restore", "legacy-sync"], rollback["targets"][0]["restore_argv"])

    def test_cutover_package_does_not_embed_execution_credential(self):
        package=CutoverPreparer(self.database).prepare(self.request)
        with zipfile.ZipFile(package.path) as archive: manifest=json.loads(archive.read("manifest.json"))
        self.assertNotIn("approval_token",manifest)
        self.assertFalse(hasattr(package,"approval_token"))

    def test_every_readiness_prerequisite_fails_closed(self):
        cases = (
            (replace(self.request, refresh_receipt=replace(self.request.refresh_receipt, support_state="SIMULATED")), "REAL"),
            (replace(self.request, expected_owner_email="different@example.invalid"), "Owner"),
            (replace(self.request, legacy_root=self.root / "missing"), "legacy"),
            (replace(self.request, backup_manifest=self.root / "missing.json"), "backup"),
            (replace(self.request, targets=()), "target"),
        )
        for request, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValidationError, message): CutoverPreparer(self.database).prepare(request)
        self.database.connection.execute("UPDATE looker_reconciliation_runs SET status='BLOCKED'")
        with self.assertRaisesRegex(ValidationError, "reconciliation"): CutoverPreparer(self.database).prepare(self.request)
        self.database.connection.execute("UPDATE looker_reconciliation_runs SET status='READY'")
        self.database.connection.execute("UPDATE looker_validation_results SET passed=0")
        with self.assertRaisesRegex(ValidationError, "validation"): CutoverPreparer(self.database).prepare(self.request)

    def test_unresolved_mapping_or_important_finding_blocks_preparation(self):
        self.database.connection.execute("INSERT INTO looker_legacy_mappings VALUES(?,?,?,?,?,?,?,?)", (str(uuid4()), "run-1", self.request.project_id, "legacy", "view", None, "UNMATCHED", "{}"))
        with self.assertRaisesRegex(ValidationError, "mapping"): CutoverPreparer(self.database).prepare(self.request)
        self.database.connection.execute("DELETE FROM looker_legacy_mappings")
        asset_id=self.database.connection.execute("SELECT looker_asset_id FROM looker_asset_occurrences WHERE intake_run_id='run-1'").fetchone()[0]
        self.database.connection.execute("INSERT INTO looker_legacy_mappings VALUES(?,?,?,?,?,?,?,?)", (str(uuid4()), "run-1", self.request.project_id, "legacy", "view", asset_id, "MATCHED", "{}"))
        self.database.connection.execute("INSERT INTO looker_findings VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (str(uuid4()), "run-1", self.request.project_id, "IMPORTANT", "code", "RISK", "orders", "OPEN", "orders.view.lkml", 1, "{}", "t"))
        with self.assertRaisesRegex(ValidationError, "finding"): CutoverPreparer(self.database).prepare(self.request)

    def test_zero_legacy_mapping_rows_block_preparation(self):
        self.database.connection.execute("DELETE FROM looker_legacy_mappings")
        with self.assertRaisesRegex(ValidationError, "mapping"):
            CutoverPreparer(self.database).prepare(self.request)

    def test_matched_mapping_must_reference_current_intake_asset(self):
        self.database.connection.execute("UPDATE looker_legacy_mappings SET entity_id='missing'")
        with self.assertRaisesRegex(ValidationError,"mapping"):
            CutoverPreparer(self.database).prepare(self.request)

    def test_verify_rejects_changed_or_symlinked_package_and_cli_has_no_effect_command(self):
        package = CutoverPreparer(self.database).prepare(self.request).path
        changed = self.root / "changed.zip"; changed.write_bytes(package.read_bytes() + b"x")
        with self.assertRaises(ValidationError): verify_cutover_package(changed)
        linked = self.root / "linked.zip"; linked.symlink_to(package)
        with self.assertRaises(ValidationError): verify_cutover_package(linked)
        from projectos.cli import build_parser
        help_text = build_parser().format_help()
        self.assertNotIn("looker cutover disable", help_text); self.assertNotIn("looker cutover remove", help_text)
        verified = build_parser().parse_args(["looker", "cutover", "verify", str(package)])
        self.assertEqual("looker cutover verify", verified.command)
        for action in ("disable", "remove", "execute"):
            with self.assertRaises(ValidationError): build_parser().parse_args(["looker", "cutover", action])


if __name__ == "__main__":
    unittest.main()
