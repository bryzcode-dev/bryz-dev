from __future__ import annotations
import json, subprocess, sys, tempfile, unittest, zipfile
from pathlib import Path
from tests.helpers import REPO_ROOT

if str(REPO_ROOT) not in sys.path: sys.path.insert(0,str(REPO_ROOT))
import build_backend


class LookerHostCliTests(unittest.TestCase):
    def test_help_exposes_only_guarded_commands(self):
        result=subprocess.run([sys.executable,"-m","projectos.looker_host","--help"],cwd=REPO_ROOT,env={"PYTHONPATH":str(REPO_ROOT/"src")},text=True,capture_output=True)
        self.assertEqual(0,result.returncode,result.stderr)
        self.assertIn("preflight",result.stdout); self.assertIn("collect",result.stdout); self.assertIn("verify",result.stdout); self.assertIn("recover",result.stdout)
        self.assertNotIn("force",result.stdout); self.assertNotIn("delete",result.stdout)

    def test_verify_returns_one_redacted_json_document(self):
        result=subprocess.run([sys.executable,"-m","projectos.looker_host","verify","--archive","missing.zip"],cwd=REPO_ROOT,env={"PYTHONPATH":str(REPO_ROOT/"src")},text=True,capture_output=True)
        payload=json.loads(result.stdout)
        self.assertFalse(payload["ok"]); self.assertEqual(2,result.returncode); self.assertNotIn(str(REPO_ROOT),result.stdout)

    def test_extracted_wheel_loads_collector_and_verifier_without_source_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); wheel=root/build_backend.build_wheel(str(root)); extracted=root/"wheel"
            with zipfile.ZipFile(wheel) as archive: archive.extractall(extracted)
            program="from projectos.looker.collector import LookerCollector; from projectos.looker.evidence import verify_intake_archive; assert LookerCollector and verify_intake_archive"
            result=subprocess.run([sys.executable,"-I","-c",f"import sys; sys.path.insert(0,{str(extracted)!r}); {program}"],cwd=root,text=True,capture_output=True)
            self.assertEqual(0,result.returncode,result.stderr)

if __name__=="__main__": unittest.main()
