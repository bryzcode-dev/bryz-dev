from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import unittest
import zipfile
from pathlib import Path

from tests.helpers import REPO_ROOT

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import build_backend


class InstalledAcceptanceTests(unittest.TestCase):
    def extracted(self, root: Path) -> Path:
        wheel = root / build_backend.build_wheel(str(root))
        extracted = root / "extracted"
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(extracted)
        return extracted

    def run_program(self, extracted: Path, root: Path, body: str):
        return subprocess.run(
            [sys.executable, "-I", "-c", textwrap.dedent(body)],
            cwd=root, text=True, capture_output=True,
            env={"PYTHONPATH": str(extracted)}, timeout=30,
        )

    @staticmethod
    def manifest_source() -> str:
        return """
        from projectos.acceptance.model import AcceptanceManifest, ACCEPTANCE_TASKS, REQUIRED_ACCEPTANCE_CASES
        manifest = AcceptanceManifest.from_mapping({
          'schema_version':2,'projectos_version':'0.1.0','source_revision':'1111111111111111111111111111111111111111',
          'wheel':{'filename':'projectos-0.1.0-py3-none-any.whl','size':1,'member_count':1,'sha256':'2222222222222222222222222222222222222222222222222222222222222222'},
          'extension_bundle':{'filename':'projectos-extension.zip','size':1,'member_count':1,'sha256':'7777777777777777777777777777777777777777777777777777777777777777','extension_id':'projectos','product_version':'0.1.0','manifest_sha256':'9999999999999999999999999999999999999999999999999999999999999999'},
          'supported_hosts':['macos','windows'],'python_contract':'>=3.11','contextos_contract':'>=3.0.1,<4',
          'acceptance_tasks':ACCEPTANCE_TASKS,'required_cases':list(REQUIRED_ACCEPTANCE_CASES),
          'created_at':'2026-09-27T12:00:00Z','members':[]})
        """

    def test_extracted_wheel_prepares_schema2_package_without_source_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            extracted = self.extracted(root)
            wheel = next(root.glob("*.whl"))
            program = f"""
            import sys
            from datetime import datetime, timezone
            from pathlib import Path
            sys.path.insert(0, {str(extracted)!r})
            from projectos.adoption.bundle import ArtifactPolicy, ExtensionBundleBuilder
            from projectos.adoption.host import HostFamily
            from projectos.adoption.manifest import CommandDeclaration, CompatibilityDeclaration, ExtensionManifest, SkillDeclaration
            from projectos.acceptance.package import AcceptancePackageBuilder, verify_acceptance_package
            root = Path({str(root)!r})
            payload = root / 'payload'
            (payload / 'skills/projectos').mkdir(parents=True)
            (payload / 'skills/projectos/SKILL.md').write_text('# ProjectOS\\n')
            (payload / 'projectos.whl').write_bytes(b'portable')
            extension = root / 'projectos-extension.zip'
            extension_manifest = ExtensionManifest(
              1,1,'projectos','0.1.0','2026-09-27T00:00:00Z',
              CompatibilityDeclaration('3.0.1','4.0.0',1,(HostFamily.MACOS,HostFamily.WINDOWS)),
              SkillDeclaration('projectos','0.1.0','skills/projectos/SKILL.md',('sync',)),
              (CommandDeclaration('health',('projectos','doctor'),False),),
              2,'CURRENT','machine-profile.json',True,(),'STAGED',())
            ExtensionBundleBuilder().build(extension_manifest,payload,extension,ArtifactPolicy(()))
            output = root / 'acceptance.zip'
            AcceptancePackageBuilder().build(Path({str(wheel)!r}), extension, {'1' * 40!r}, datetime(2026,9,27,12,0,tzinfo=timezone.utc), output)
            verified = verify_acceptance_package(output)
            assert verified.manifest.schema_version == 2
            assert verified.member_count == 7
            """
            result = self.run_program(extracted, root, program)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_extracted_wheel_simulates_run_with_recording_executor_and_native_trigger_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            extracted = self.extracted(root)
            program = f"""
            import json, sys
            sys.path.insert(0, {str(extracted)!r})
            from projectos.acceptance.native import RecordingProcessExecutor, NativeProcessResult
            from projectos.acceptance.native_probe import NativeTriggerWindow
            recorder = RecordingProcessExecutor((NativeProcessResult(0,'',''),))
            assert recorder.run(('launchctl','kickstart','gui/501/com.contextos.projectos.acceptance.sync'),30).returncode == 0
            window = NativeTriggerWindow('window-1','run-1',1,'immediate_trigger','receipt-1','2'*64,'3'*64)
            assert NativeTriggerWindow.from_mapping(json.loads(window.canonical_bytes())).run_id == 'run-1'
            """
            result = self.run_program(extracted, root, program)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_extracted_wheel_recovers_each_persisted_boundary_after_process_reconstruction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            extracted = self.extracted(root)
            program = f"""
            import json, sys
            sys.path.insert(0, {str(extracted)!r})
            from projectos.acceptance.journal import HostAcceptanceJournal, HostAcceptanceState
            for state in (item for item in HostAcceptanceState if item is not HostAcceptanceState.FAILED):
                journal = HostAcceptanceJournal('run-1',state,'acceptance-1','receipt-1','1'*64,'2'*64,'3'*64,(state.value,),(),False,(),None)
                assert HostAcceptanceJournal.from_mapping(json.loads(journal.canonical_bytes())) == journal
            uncertain = HostAcceptanceJournal('run-1',HostAcceptanceState.NATIVE_STAGED,'acceptance-1','receipt-1','1'*64,'2'*64,'3'*64,('NATIVE_STAGED',),(),False,(),'enable')
            assert HostAcceptanceJournal.from_mapping(json.loads(uncertain.canonical_bytes())).pending_effect == 'enable'
            """
            result = self.run_program(extracted, root, program)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_extracted_wheel_seals_verifies_and_reconciles_native_shaped_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            extracted = self.extracted(root)
            program = f"""
            import hashlib, sys
            from pathlib import Path
            sys.path.insert(0, {str(extracted)!r})
{textwrap.indent(textwrap.dedent(self.manifest_source()), '            ')}
            from projectos.acceptance.evidence import AcceptanceCaseResult, AcceptanceEvidenceBuilder, AcceptanceEvidenceVerifier, HostAcceptanceRecord
            from projectos.acceptance.model import SupportState
            from projectos.acceptance.reconcile import AcceptanceReconciler
            cases = tuple(AcceptanceCaseResult(i,c,'PASS','CASE_'+str(i),'NATIVE','2026-09-27T12:00:00Z','2026-09-27T12:00:00Z',{{'proved':True}}) for i,c in enumerate(REQUIRED_ACCEPTANCE_CASES,1))
            record = HostAcceptanceRecord('projectos-host-acceptance-v2','0.1.0','1'*40,'2'*64,'7'*64,'6'*64,hashlib.sha256(manifest.canonical_bytes()).hexdigest(),'a'*64,'8'*64,'macos','15.0','arm64','3.14.7','run-1',True,True,cases,('installed-disabled','enabled','installed-disabled','absent'),'DEACTIVATED','DEFINITION_ROLLED_BACK',True,True,True,('database','raw-logs'),())
            output = Path({str(root / 'evidence.zip')!r})
            AcceptanceEvidenceBuilder().build(record,{{}},output)
            verified = AcceptanceEvidenceVerifier().verify(output,manifest)
            assert AcceptanceReconciler().reconcile(manifest,(verified,)).support_state is SupportState.MACOS_VERIFIED
            """
            result = self.run_program(extracted, root, program)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_installed_flow_never_constructs_network_client_or_executes_native_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            extracted = self.extracted(root)
            program = f"""
            import socket, subprocess, sys
            sys.path.insert(0, {str(extracted)!r})
            subprocess.run = lambda *a, **k: (_ for _ in ()).throw(AssertionError('native execution'))
            socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network'))
            from projectos.acceptance.host_context import HostAcceptanceContextFactory
            from projectos.acceptance.native import RecordingProcessExecutor, NativeProcessResult
            recorder = RecordingProcessExecutor((NativeProcessResult(0,'',''),))
            assert recorder.run(('recording-only',),1).returncode == 0
            assert HostAcceptanceContextFactory
            """
            result = self.run_program(extracted, root, program)
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
