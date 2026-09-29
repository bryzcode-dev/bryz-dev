from __future__ import annotations
import json, shutil, sys, tempfile, unittest
from pathlib import Path
from tests.helpers import REPO_ROOT
if str(REPO_ROOT / "src") not in sys.path: sys.path.insert(0, str(REPO_ROOT / "src"))
from projectos.acceptance.authority import HostSession
from projectos.adoption.host import HostFamily
from projectos.errors import ValidationError
from projectos.looker.model import LookerIntake
from tests.test_looker_inspectors import Recorder, Result


class LookerCollectorTests(unittest.TestCase):
    def setup_system(self, root):
        repo=root/"repo"; shutil.copytree(REPO_ROOT/"tests/fixtures/looker/repository",repo)
        (repo/"sync.py").write_text("print('sync')\n"); (repo/"scheduler.txt").write_text("interval=7200\n")
        out=root/"out"; out.mkdir()
        value=json.loads((REPO_ROOT/"tests/fixtures/looker/intake-macos.json").read_text())
        value.update(repository_root=str(repo),output_root=str(out),sync_script_paths=[str(repo/"sync.py")],scheduler_definition_paths=[str(repo/"scheduler.txt")])
        value["gas"]["source_root"]=str(repo); value["validation_commands"][0]["working_directory"]=str(repo)
        return LookerIntake.from_mapping(value),out

    def recorder(self):
        return Recorder(Result(stdout="a"*40),Result(stdout="main"),Result(stdout=""),Result(stdout="0 0"),Result(stdout="tests=1 passed=1"))

    def test_collection_journals_ordered_stages_and_seals_verified_archive(self):
        from projectos.looker.collector import LookerCollector
        from projectos.looker.evidence import verify_intake_archive
        with tempfile.TemporaryDirectory() as temporary:
            intake,out=self.setup_system(Path(temporary)); output=out/"projectos-looker-intake-v1.zip"
            result=LookerCollector().collect(intake,HostSession(HostFamily.MACOS,"1"*64,False,True),self.recorder(),output,"2"*64)
            self.assertEqual("SEALED",result.state); self.assertEqual(result.sha256,verify_intake_archive(output).sha256)
            journal=json.loads((out/"collection-journal.json").read_text())
            self.assertEqual(["VALIDATED","INVENTORIED","INSPECTED","SCANNED","SEALED"],journal["completed_stages"])

    def test_repository_mutation_during_collection_fails_without_archive(self):
        from projectos.looker.collector import LookerCollector
        with tempfile.TemporaryDirectory() as temporary:
            intake,out=self.setup_system(Path(temporary)); output=out/"evidence.zip"
            def hook(stage):
                if stage=="INSPECTED": Path(intake.repository_root,"changed.lkml").write_text("view: changed {}")
            with self.assertRaisesRegex(ValidationError,"changed"):
                LookerCollector().collect(intake,HostSession(HostFamily.MACOS,"1"*64,False,True),self.recorder(),output,"2"*64,stage_hook=hook)
            self.assertFalse(output.exists())

    def test_recovery_removes_only_incomplete_temporary_archive(self):
        from projectos.looker.collector import LookerCollector
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); intake,out=self.setup_system(root); keep=out/"keep.txt"; keep.write_text("keep"); partial=out/".projectos-looker-intake-v1.zip.tmp"; partial.write_text("partial")
            LookerCollector().recover(intake,HostSession(HostFamily.MACOS,"1"*64,False,True))
            self.assertFalse(partial.exists()); self.assertEqual("keep",keep.read_text())

