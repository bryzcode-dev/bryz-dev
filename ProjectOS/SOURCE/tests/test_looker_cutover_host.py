from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path

from tests.helpers import REPO_ROOT
from tests.test_looker_cutover import CutoverFixture

if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from projectos.acceptance.native import NativeProcessResult, RecordingProcessExecutor
from projectos.errors import ValidationError
from projectos.looker.cutover import CutoverPreparer, verify_cutover_package


class LookerCutoverHostTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup); self.root = Path(self.temporary.name)
        self.database, self.request = CutoverFixture().build(self.root); self.addCleanup(self.database.close)
        self.simulated_package = CutoverPreparer(self.database).prepare(self.request)
        self.package_path = self.root / "real-cutover.zip"
        self.package = CutoverPreparer(self.database).prepare(replace(self.request, output_path=self.package_path, support_state="REAL"))
        self.key=b"a"*32; self.owner="owner@example.invalid"; self.journal = self.root / "journal.json"
        from projectos.looker_cutover_host import CutoverApproval
        self.approval=CutoverApproval.issue(self.package,self.owner,"2026-09-27T13:00:00Z","approval-001",self.key)

    def test_intent_is_durable_before_effect_and_disable_precedes_remove(self):
        from projectos.looker_cutover_host import CutoverHostTransaction
        observations = []
        class Executor:
            def run(inner, argv, timeout_seconds):
                value = json.loads(self.journal.read_text()); observations.append((tuple(argv), value["pending_effect"]))
                if argv[0] == "inspect-owner": return NativeProcessResult(0, "owner-fingerprint\n", "")
                return NativeProcessResult(0, "", "")
        result = CutoverHostTransaction(self.package, self.journal, Executor(), self.key, self.owner).execute(self.approval)
        self.assertEqual("COMPLETE", result.state)
        effects = [argv[0] for argv, pending in observations if argv[0] != "inspect-owner"]
        self.assertEqual(["disable", "remove"], effects); self.assertTrue(all(pending for _, pending in observations))
        self.assertTrue(self.package_path.is_file()); self.assertIn("legacy/tracker.json", zipfile.ZipFile(self.package_path).namelist())

    def test_changed_ownership_stops_before_effect(self):
        from projectos.looker_cutover_host import CutoverHostTransaction
        executor = RecordingProcessExecutor((NativeProcessResult(0, "different-owner\n", ""),))
        with self.assertRaisesRegex(ValidationError, "ownership"): CutoverHostTransaction(self.package, self.journal, executor, self.key, self.owner).execute(self.approval)
        self.assertEqual([("inspect-owner", "legacy-sync")], executor.history)

    def test_later_ownership_failure_rolls_back_completed_targets(self):
        from projectos.looker_cutover_host import CutoverApproval, CutoverHostTransaction
        first=self.request.targets[0]
        second=replace(first,target_id="legacy-sync-2",inspect_owner_argv=("inspect-owner","legacy-sync-2"),disable_argv=("disable","legacy-sync-2"),remove_argv=("remove","legacy-sync-2"),restore_argv=("restore","legacy-sync-2"))
        package=CutoverPreparer(self.database).prepare(replace(self.request,targets=(first,second),output_path=self.root/"two-targets.zip",support_state="REAL"))
        approval=CutoverApproval.issue(package,self.owner,"2026-09-27T13:00:00Z","approval-002",self.key)
        executor=RecordingProcessExecutor((NativeProcessResult(0,"owner-fingerprint\n",""),NativeProcessResult(0,"",""),NativeProcessResult(0,"changed-owner\n",""),NativeProcessResult(0,"owner-fingerprint\n",""),NativeProcessResult(0,"","")))
        result=CutoverHostTransaction(package,self.root/"two-targets-journal.json",executor,self.key,self.owner).execute(approval)
        self.assertEqual("ROLLED_BACK",result.state)
        self.assertEqual(("restore","legacy-sync"),executor.history[-1])

    def test_failed_effect_rolls_back_and_recovery_is_idempotent(self):
        from projectos.looker_cutover_host import CutoverHostTransaction
        executor = RecordingProcessExecutor((NativeProcessResult(0, "owner-fingerprint\n", ""), NativeProcessResult(0, "", ""), NativeProcessResult(0, "owner-fingerprint\n", ""), NativeProcessResult(1, "", "failed"), NativeProcessResult(0, "owner-fingerprint\n", ""), NativeProcessResult(0, "", "")))
        transaction = CutoverHostTransaction(self.package, self.journal, executor, self.key, self.owner)
        result = transaction.execute(self.approval)
        self.assertEqual("ROLLED_BACK", result.state); self.assertEqual("restore", executor.history[-1][0])
        count = len(executor.history); recovered = transaction.recover(self.approval)
        self.assertEqual("ROLLED_BACK", recovered.state); self.assertEqual(count, len(executor.history))

    def test_changed_approval_or_package_and_unknown_pending_effect_fail_closed(self):
        from projectos.looker_cutover_host import CutoverHostTransaction
        with self.assertRaises(ValidationError): CutoverHostTransaction(self.package, self.journal, RecordingProcessExecutor(), self.key, self.owner).execute(replace(self.approval,signature="0"*64))
        self.journal.write_text(json.dumps({"format": "projectos-looker-cutover-journal-v1", "cutover_id": self.package.cutover_id, "package_sha256": self.package.sha256, "state": "RUNNING", "completed_effects": [], "pending_effect": {"target_id": "legacy-sync", "action": "remove"}, "errors": []}, sort_keys=True, separators=(",", ":")) + "\n")
        with self.assertRaisesRegex(ValidationError, "reconstruction"): CutoverHostTransaction(self.package, self.journal, RecordingProcessExecutor(), self.key, self.owner).recover(self.approval)

    def test_simulated_package_cannot_execute_native_effects(self):
        from projectos.looker_cutover_host import CutoverHostTransaction
        with self.assertRaisesRegex(ValidationError, "REAL"):
            CutoverHostTransaction(self.simulated_package, self.journal, RecordingProcessExecutor(), self.key, self.owner).execute(self.approval)

    def test_real_package_requires_separate_signed_owner_approval(self):
        from projectos.looker_cutover_host import CutoverApproval, CutoverHostTransaction
        real_path=self.root/"real-cutover.zip"
        package=verify_cutover_package(CutoverPreparer(self.database).prepare(replace(self.request,output_path=real_path,support_state="REAL")).path)
        signing_key=b"a"*32
        approval=CutoverApproval.issue(package,"owner@example.invalid","2026-09-27T13:00:00Z","approval-001",signing_key)
        responses=(NativeProcessResult(0,"owner-fingerprint\n",""),NativeProcessResult(0,"",""),NativeProcessResult(0,"owner-fingerprint\n",""),NativeProcessResult(0,"",""))
        result=CutoverHostTransaction(package,self.journal,RecordingProcessExecutor(responses),signing_key,"owner@example.invalid").execute(approval)
        self.assertEqual("COMPLETE",result.state)
        with self.assertRaisesRegex(ValidationError,"approval"):
            CutoverHostTransaction(package,self.root/"wrong-journal.json",RecordingProcessExecutor(),signing_key,"owner@example.invalid").execute(replace(approval,package_sha256="0"*64))
        rogue=CutoverApproval.issue(package,"attacker@example.invalid","2026-09-27T13:00:00Z","approval-rogue",signing_key)
        with self.assertRaisesRegex(ValidationError,"approval"):
            CutoverHostTransaction(package,self.root/"rogue-journal.json",RecordingProcessExecutor(),signing_key,"attacker@example.invalid").execute(rogue)

    def test_wheel_contains_cutover_preparation_and_host_recovery_modules(self):
        import build_backend
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); wheel = root / build_backend.build_wheel(root); extracted = root / "extracted"
            with zipfile.ZipFile(wheel) as archive: names = set(archive.namelist()); archive.extractall(extracted)
            request_path = root / "request.json"
            request_path.write_text(json.dumps({"project_id": self.request.project_id, "intake_run_id": self.request.intake_run_id, "reconciliation_id": self.request.reconciliation_id, "refresh_receipt": self.request.refresh_receipt.to_mapping(), "backup_manifest": str(self.request.backup_manifest), "legacy_root": str(self.request.legacy_root), "targets": [item.to_mapping() for item in self.request.targets], "actor": self.request.actor, "expected_owner_email": self.request.expected_owner_email, "prepared_at": self.request.prepared_at, "output_path": str(root / "wheel-cutover.zip")}, sort_keys=True))
            self.database.close()
            script = textwrap.dedent("""
                import json,sys
                from pathlib import Path
                from projectos.acceptance.native import NativeProcessResult,RecordingProcessExecutor
                from projectos.database import ProjectOSDatabase
                from projectos.looker.cutover import CutoverPreparationRequest,CutoverPreparer,CutoverTarget,verify_cutover_package
                from projectos.looker.refresh import RefreshReceipt
                from projectos.looker_cutover_host import CutoverApproval,CutoverHostTransaction
                value=json.loads(Path(sys.argv[1]).read_text()); db=ProjectOSDatabase.open_existing(Path(sys.argv[2]))
                request=CutoverPreparationRequest(value['project_id'],value['intake_run_id'],value['reconciliation_id'],RefreshReceipt.from_mapping(value['refresh_receipt']),Path(value['backup_manifest']),Path(value['legacy_root']),tuple(CutoverTarget.from_mapping(item) for item in value['targets']),value['actor'],value['expected_owner_email'],value['prepared_at'],Path(value['output_path']),'REAL')
                package=CutoverPreparer(db).prepare(request); db.close()
                key=b'a'*32; approval=CutoverApproval.issue(package,value['actor'],'2026-09-27T13:00:00Z','wheel-approval',key)
                responses=(NativeProcessResult(0,'owner-fingerprint\\n',''),NativeProcessResult(0,'',''),NativeProcessResult(0,'owner-fingerprint\\n',''),NativeProcessResult(1,'','failed'),NativeProcessResult(0,'owner-fingerprint\\n',''),NativeProcessResult(0,'',''))
                transaction=CutoverHostTransaction(verify_cutover_package(package.path),Path(sys.argv[3]),RecordingProcessExecutor(responses),key,value['actor']); result=transaction.execute(approval); assert result.state=='ROLLED_BACK'; assert transaction.recover(approval).state=='ROLLED_BACK'
            """)
            environment = dict(os.environ); environment["PYTHONPATH"] = str(extracted)
            result = subprocess.run((sys.executable, "-c", script, str(request_path), str(self.database.path), str(root / "journal.json")), cwd=root, env=environment, text=True, capture_output=True, check=False)
        self.assertIn("projectos/looker/cutover.py", names); self.assertIn("projectos/looker_cutover_host.py", names); self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
