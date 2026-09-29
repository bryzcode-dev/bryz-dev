from __future__ import annotations

import json
import os
import shutil
import socket
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


class LookerInstalledTests(unittest.TestCase):
    def test_extracted_wheel_runs_phase4_fixture_and_builds_scanned_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel = root / build_backend.build_wheel(root)
            extracted = root / "wheel"
            with zipfile.ZipFile(wheel) as archive:
                archive.extractall(extracted)
            repository = root / "repository"
            shutil.copytree(REPO_ROOT / "tests/fixtures/looker/repository", repository)
            (repository / "sync.py").write_text("print('fixture sync')\n", encoding="utf-8")
            (repository / "scheduler.txt").write_text("interval=7200\n", encoding="utf-8")
            release = root / "release"
            program = self._program(extracted, wheel, repository, release)
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(extracted)
            result = subprocess.run(
                (sys.executable, "-I", "-c", program),
                cwd=root,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            inventory = json.loads((release / "artifact-inventory.json").read_text())
            names = {item["name"] for item in inventory["artifacts"]}
            expected = {"projectos-0.1.0-py3-none-any.whl", "projectos-extension.zip", "intake.zip", "schema3.sqlite", "analytics.json", "reconciliation.json", "simulated-refresh-receipt.json", "cutover.zip", "rollback-package.json"}
            self.assertEqual(expected, names)
            self.assertEqual("SIMULATED", inventory["support_state"])
            with zipfile.ZipFile(release / "cutover.zip") as archive:
                self.assertEqual("SIMULATED", json.loads(archive.read("manifest.json"))["support_state"])
            self.assertEqual(3, inventory["migration_version"])
            self.assertEqual(0, inventory["network_calls"])
            self.assertEqual(["inspect-owner", "disable", "inspect-owner", "remove", "inspect-owner", "restore"], inventory["recording_actions"])
            self.assertTrue(all(len(item["sha256"]) == 64 and item["size"] > 0 for item in inventory["artifacts"]))

    @staticmethod
    def _program(extracted: Path, wheel: Path, repository: Path, release: Path) -> str:
        return textwrap.dedent(
            f"""
            import hashlib,json,os,re,shutil,socket,sqlite3,sys,zipfile
            from dataclasses import asdict,replace
            from pathlib import Path
            from uuid import uuid4
            sys.path.insert(0,{str(extracted)!r})

            class NoNetworkSocket:
                def __init__(self,*args,**kwargs): raise AssertionError('network access is prohibited')
            socket.socket=NoNetworkSocket

            from projectos.acceptance.authority import HostSession
            from projectos.acceptance.native import NativeProcessResult,RecordingProcessExecutor
            from projectos.adoption.bundle import ArtifactPolicy,ExtensionBundleBuilder
            from projectos.adoption.host import HostFamily
            from projectos.adoption.manifest import CommandDeclaration,CompatibilityDeclaration,ExtensionManifest,SkillDeclaration
            from projectos.adoption.skill import render_projectos_skill
            from projectos.backup import BackupService
            from projectos.bindings import GoogleBindingRepository
            from projectos.credentials import CredentialReferenceCreate,CredentialReferenceService
            from projectos.database import ProjectOSDatabase
            from projectos.errors import ValidationError
            from projectos.google.types import GoogleBindingCreate
            from projectos.looker.analytics import LookerAnalyticsService
            from projectos.looker.collector import LookerCollector
            from projectos.looker.cutover import CutoverPreparationRequest,CutoverPreparer,CutoverTarget,verify_cutover_package
            from projectos.looker.evidence import verify_intake_archive
            from projectos.looker.importer import LookerImporter
            from projectos.looker.model import LookerIntake
            from projectos.looker.reconcile import LookerReconciler,ReconciliationPolicy
            from projectos.looker.refresh import RefreshReceipt
            from projectos.looker_cutover_host import CutoverApproval,CutoverHostTransaction
            from projectos.repositories import ProjectRepository
            from projectos.sync.projection import ProjectionBuilder
            from projectos.types import ProjectCreate,ProjectType,ProjectVisibility
            from projectos.users import UserRepository

            root=Path.cwd(); repository=Path({str(repository)!r}); release=Path({str(release)!r}); release.mkdir()
            output=root/'collector-output'; output.mkdir()
            intake=LookerIntake.from_mapping({{
              'schema_version':1,'source_machine_id':'fixture-source','host_family':'macos','repository_root':str(repository),'output_root':str(output),
              'git':{{'remote':'origin','primary_branch':'main','ownership_context':'fixture-owned'}},
              'master_sheet':{{'spreadsheet_id':'sheet-fixture','url':'https://docs.google.com/spreadsheets/d/sheet-fixture','tabs':['Models','Views']}},
              'gas':{{'script_id':'script-fixture','deployment_ids':['deploy-fixture'],'source_root':str(repository)}},
              'sync_script_paths':[str(repository/'sync.py')],'scheduler_definition_paths':[str(repository/'scheduler.txt')],
              'validation_commands':[{{'command_id':'tests','executable':'python3','arguments':['-m','unittest'],'working_directory':str(repository),'timeout_seconds':30,'expected_exit_codes':[0],'parser':'TEST_SUMMARY'}}],
              'credential_references':[{{'provider':'google','label':'looker-sheet','storage_system':'keychain','storage_reference':'projectos/fixture'}}]
            }})
            class CollectorExecutor:
                def __init__(self): self.responses=list((NativeProcessResult(0,'a'*40,''),NativeProcessResult(0,'main\\n',''),NativeProcessResult(0,'',''),NativeProcessResult(0,'0 0\\n',''),NativeProcessResult(0,'tests=1 passed=1\\n','')))
                def run(self,argv,timeout_seconds,cwd): return self.responses.pop(0)
            def collector_executor(): return CollectorExecutor()
            session=HostSession(HostFamily.MACOS,'1'*64,False,True); collector=LookerCollector()
            first=collector.collect(intake,session,collector_executor(),output/'intake-a.zip','2'*64)
            second=collector.collect(intake,session,collector_executor(),output/'intake-b.zip','2'*64)
            assert first.sha256==second.sha256 and first.output_path.read_bytes()==second.output_path.read_bytes()
            evidence=verify_intake_archive(first.output_path); shutil.copy2(first.output_path,release/'intake.zip')

            database=ProjectOSDatabase(root/'projectos.sqlite').initialize(); owner='fixture-owner@example.invalid'; UserRepository(database,owner).seed_owner(owner,'Fixture Owner')
            project=ProjectRepository(database).create(ProjectCreate('fixture-looker','Fixture Looker',ProjectType.LOOKER,ProjectVisibility.PUBLIC),owner)
            imported=LookerImporter(database).import_archive(project.project_id,evidence,owner)
            mapped_asset=database.connection.execute("SELECT a.looker_asset_id FROM looker_assets a JOIN looker_asset_occurrences o ON o.looker_asset_id=a.looker_asset_id WHERE o.intake_run_id=? AND a.asset_type='view' AND a.name='orders'",(first.run_id,)).fetchone()[0]
            database.connection.execute("INSERT INTO looker_legacy_mappings VALUES(?,?,?,?,?,?,?,?)",(str(uuid4()),first.run_id,str(project.project_id),'legacy:fixture','view',mapped_asset,'MATCHED','{{}}'))
            analytics=LookerAnalyticsService(database); version=analytics.build(project.project_id,first.run_id); summary=analytics.summary(project.project_id,version.version)
            projection=ProjectionBuilder().build(database.connection,uuid4()); assert projection.public_tabs['Looker_Assets']
            reconciler=LookerReconciler(database); source=reconciler._source(str(project.project_id),first.run_id,version.version)
            reconciliation=reconciler.stage(project.project_id,first.run_id,version.version,source,ReconciliationPolicy.default(),owner); assert reconciliation.ready
            credential=CredentialReferenceService(database).create(CredentialReferenceCreate('GOOGLE','fixture','ADC','fixture','KEYCHAIN','projectos/fixture'),owner)
            binding=GoogleBindingRepository(database).create(GoogleBindingCreate('DEV','sheet-fixture','ProjectOS',1,credential.credential_id,enabled=True,write_enabled=True),owner)
            revision=str(projection.revision_id); sync_run=str(uuid4())
            database.connection.execute("INSERT INTO projection_revisions(revision_id,binding_id,schema_version,snapshot_hash,entity_counts_json,state,started_at,verified_at,activated_at) VALUES(?,?,?,?,?,'ACTIVE','t','t','t')",(revision,str(binding.binding_id),projection.schema_version,projection.snapshot_hash,'{{}}'))
            database.connection.execute("INSERT INTO sync_runs(run_id,trigger,status,started_at,finished_at,summary_json,binding_id,starting_checkpoint,ending_checkpoint) VALUES(?,'skill','COMPLETE','t','t','{{}}',?,'before','after')",(sync_run,str(binding.binding_id)))
            receipt_value={{'receipt_version':1,'support_state':'REAL','project_id':str(project.project_id),'intake_run_id':first.run_id,'analytic_version':version.version,'reconciliation_id':reconciliation.reconciliation_id,'binding_id':str(binding.binding_id),'sync_run_id':sync_run,'projection_revision_id':revision,'validation_command_ids':['tests'],'source_revision':'a'*40,'refreshed_at':'2026-09-27T12:00:00Z'}}
            verified_receipt=RefreshReceipt.from_mapping(receipt_value).verify(database); assert verified_receipt.ok
            simulated={{**receipt_value,'support_state':'SIMULATED'}}
            (release/'simulated-refresh-receipt.json').write_text(json.dumps(simulated,sort_keys=True,separators=(',',':'))+'\\n')
            try: RefreshReceipt.from_mapping(simulated).verify(database)
            except ValidationError: pass
            else: raise AssertionError('simulated receipt was accepted')
            backup=BackupService(database).create(root/'backup')
            legacy=root/'legacy'; legacy.mkdir(); (legacy/'tracker.json').write_text('{{"legacy":true}}\\n'); (legacy/'sync.js').write_text('function sync() {{}}\\n'); (legacy/'schedule.plist').write_text('<plist/>\\n')
            target=CutoverTarget('legacy-sync','LAUNCHD','owner-fingerprint',('inspect-owner','legacy-sync'),('disable','legacy-sync'),('remove','legacy-sync'),('restore','legacy-sync'))
            cutover_request=CutoverPreparationRequest(str(project.project_id),first.run_id,reconciliation.reconciliation_id,RefreshReceipt.from_mapping(receipt_value),backup.manifest_path,legacy,(target,),owner,owner,'2026-09-27T12:30:00Z',release/'cutover.zip')
            cutover=CutoverPreparer(database).prepare(cutover_request)
            verified_cutover=verify_cutover_package(cutover.path); assert verified_cutover.ready
            executable_cutover=CutoverPreparer(database).prepare(replace(cutover_request,output_path=root/'real-cutover.zip',support_state='REAL'))
            approval_key=b'a'*32; approval=CutoverApproval.issue(executable_cutover,owner,'2026-09-27T13:00:00Z','installed-approval',approval_key)
            responses=(NativeProcessResult(0,'owner-fingerprint\\n',''),NativeProcessResult(0,'',''),NativeProcessResult(0,'owner-fingerprint\\n',''),NativeProcessResult(1,'','failed'),NativeProcessResult(0,'owner-fingerprint\\n',''),NativeProcessResult(0,'',''))
            recorder=RecordingProcessExecutor(responses); transaction=CutoverHostTransaction(executable_cutover,root/'cutover-journal.json',recorder,approval_key,owner); result=transaction.execute(approval); assert result.state=='ROLLED_BACK'; assert transaction.recover(approval).state=='ROLLED_BACK'
            (release/'analytics.json').write_text(json.dumps({{'version':version.version,'summary':summary}},sort_keys=True,separators=(',',':'))+'\\n')
            (release/'reconciliation.json').write_text(json.dumps(asdict(reconciliation),sort_keys=True,separators=(',',':'))+'\\n')
            with zipfile.ZipFile(cutover.path) as archive: (release/'rollback-package.json').write_bytes(archive.read('rollback.json'))
            final_snapshot=release/'schema3.sqlite'; target_db=sqlite3.connect(final_snapshot); database.connection.backup(target_db); target_db.close(); database.close()

            payload=root/'extension-payload'; skill_path=payload/'skills/projectos/SKILL.md'; skill_path.parent.mkdir(parents=True)
            looker_caps=('status','looker-status','looker-assets','looker-dependencies','looker-findings','looker-impact','looker-reconciliation')
            manifest=ExtensionManifest(1,1,'projectos','0.1.0','2026-09-27T00:00:00Z',CompatibilityDeclaration('3.0.1','4.0.0',1,(HostFamily.MACOS,HostFamily.WINDOWS)),SkillDeclaration('projectos','0.2.0','skills/projectos/SKILL.md',looker_caps),(CommandDeclaration('health',('projectos','doctor'),False),),3,'CURRENT','machine-profile.json',True,(),'STAGED',())
            skill_path.write_bytes(render_projectos_skill(manifest)); shutil.copy2(Path({str(wheel)!r}),payload/'projectos.whl'); ExtensionBundleBuilder().build(manifest,payload,release/'projectos-extension.zip',ArtifactPolicy(()))
            shutil.copy2(Path({str(wheel)!r}),release/Path({str(wheel.name)!r}))

            artifact_names=['projectos-0.1.0-py3-none-any.whl','projectos-extension.zip','intake.zip','schema3.sqlite','analytics.json','reconciliation.json','simulated-refresh-receipt.json','cutover.zip','rollback-package.json']
            forbidden=(str(Path.home()),{str(REPO_ROOT)!r},os.environ.get('USER',''),socket.gethostname(),'-----BEGIN PRIVATE KEY-----','ghp_','AIza')
            email_pattern=re.compile(rb'(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]{{1,64}}@[A-Za-z0-9.-]+\\.[A-Za-z]{{2,}}')
            discovered_emails=set(); artifacts=[]
            for name in artifact_names:
                path=release/name; content=path.read_bytes()
                for marker in forbidden:
                    if marker: assert marker.encode() not in content,(name,marker)
                if path.suffix=='.json': discovered_emails.update(item.decode() for item in email_pattern.findall(content))
                if owner.encode() in content: discovered_emails.add(owner)
                members=None
                if zipfile.is_zipfile(path):
                    with zipfile.ZipFile(path) as archive:
                        infos=archive.infolist(); names=[item.filename for item in infos]
                        assert len(names)==len(set(item.casefold() for item in names)); assert all(not Path(item).is_absolute() and '..' not in Path(item).parts for item in names); assert all((item.external_attr>>16)&0o170000!=0o120000 for item in infos); members=len(infos)
                        for member in infos:
                            if member.file_size<=2_000_000: discovered_emails.update(item.decode() for item in email_pattern.findall(archive.read(member)))
                artifacts.append({{'name':name,'size':len(content),'members':members,'sha256':hashlib.sha256(content).hexdigest()}})
            assert discovered_emails <= {{owner,'invalid-caller@projectos.invalid'}},sorted(discovered_emails)
            inventory={{'support_state':'SIMULATED','migration_version':3,'analytic_versions':1,'reconciliation_reports':1,'network_calls':0,'recording_actions':[item[0] for item in recorder.history],'fixture_emails':sorted(discovered_emails),'artifacts':artifacts}}
            (release/'artifact-inventory.json').write_text(json.dumps(inventory,sort_keys=True,indent=2)+'\\n')
            """
        )


if __name__ == "__main__":
    unittest.main()
