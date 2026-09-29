from __future__ import annotations
import sys,tempfile,unittest
from pathlib import Path
from tests.helpers import REPO_ROOT
if str(REPO_ROOT/"src") not in sys.path: sys.path.insert(0,str(REPO_ROOT/"src"))
from projectos.database import ProjectOSDatabase
from projectos.looker.evidence import LookerEvidenceBuilder,verify_intake_archive
from projectos.looker.importer import LookerImporter
from projectos.repositories import ProjectRepository
from projectos.types import ProjectCreate,ProjectType,ProjectVisibility

class LookerAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); root=Path(self.tmp.name)
        self.db=ProjectOSDatabase(root/"db.sqlite").initialize(); self.addCleanup(self.db.close)
        self.project=ProjectRepository(self.db).create(ProjectCreate("looker","Looker",ProjectType.LOOKER,ProjectVisibility.PUBLIC),"owner")
        sections={name:{"format":name,"items":[]} for name in ("repository","looker-assets","looker-relationships","legacy-tracker","automation","validation","credential-references","findings")}
        sections["repository"]={"format":"repository-v1","git":{"head":"a"*40,"branch":"feature","dirty":True,"behind":2,"ahead":3,"remote":"origin","primary_branch":"main"}}
        sections["legacy-tracker"]={"format":"legacy-tracker-v1","value":{"spreadsheet_id":"sheet-1","sheet_tabs":["Projects","Models"],"script_id":"script-1","deployment_ids":["deployment-1"]}}
        sections["credential-references"]["items"]=[{"provider":"gcp","label":"looker-reader","storage_system":"keychain","storage_reference":"projectos/looker-reader"}]
        def asset(kind,name,path): return {"asset_type":kind,"name":name,"source_path":path,"content_sha256":"b"*64,"parser_version":"1.0.0","line":1}
        sections["looker-assets"]["items"]=[asset("model","commerce","commerce.model.lkml"),asset("explore","orders","commerce.model.lkml"),asset("view","orders","orders.view.lkml"),asset("view","orphan","orphan.view.lkml"),asset("dashboard","sales","sales.dashboard.lookml")]
        def edge(kind,st,s,tt,t): return {"relationship_type":kind,"source_type":st,"source_name":s,"target_type":tt,"target_name":t,"source_path":"commerce.model.lkml","line":1}
        sections["looker-relationships"]["items"]=[edge("model_connection","model","commerce","connection","warehouse"),edge("explore_view","explore","orders","view","orders"),edge("dashboard_explore","dashboard","sales","explore","orders"),edge("view_extends","view","orders","view","orders"),edge("explore_view","explore","removed","view","orders")]
        sections["findings"]["items"]=[{"code":"UNRESOLVED_REFERENCE","subject":"view:missing","source_path":"commerce.model.lkml","line":2},{"code":"DUPLICATE_ASSET","subject":"view:orders","source_path":"","line":1}]
        sections["validation"]["items"]=[{"command_id":"tests","passed":True,"returncode":0,"timed_out":False,"parser":"TEST_SUMMARY","summary":"passed=1"}]
        archive=root/"evidence.zip"; LookerEvidenceBuilder().build("machine","macos","run-1","1"*64,"2"*64,"3"*64,sections,archive)
        LookerImporter(self.db).import_archive(self.project.project_id,verify_intake_archive(archive),"owner")

    def test_build_counts_graph_findings_git_validation_orphans_and_status(self):
        from projectos.looker.analytics import LookerAnalyticsService
        service=LookerAnalyticsService(self.db); version=service.build(self.project.project_id,"run-1"); summary=service.summary(self.project.project_id,version.version)
        self.assertEqual({"connection_reference":1,"dashboard":1,"explore":1,"file":4,"model":1,"view":2},summary["asset_counts"])
        self.assertEqual(1,summary["unresolved_count"]); self.assertEqual(1,summary["duplicate_count"]); self.assertIn("view:orphan",summary["orphans"]["view"])
        self.assertEqual({"ahead":3,"behind":2,"branch":"feature","dirty":True,"head":"a"*40},summary["git"])
        self.assertEqual({"failed":0,"passed":1},summary["validation"]); self.assertEqual("PASS",summary["code_status"]); self.assertEqual("UNAVAILABLE",summary["refresh_status"])
        self.assertEqual({"by_provider":{"gcp":1},"by_storage_system":{"keychain":1},"reference_count":1},summary["credential_usage"])
        self.assertEqual(2,summary["legacy"]["declared_sheet_tab_count"]); self.assertEqual(1,summary["legacy"]["declared_deployment_count"]); self.assertEqual(0,summary["legacy"]["mapping_total"])
        self.assertEqual(["1.0.0"],summary["parser_versions"]); self.assertEqual("run-1",summary["import"]["intake_run_id"])

    def test_dependencies_and_impact_are_stable_and_cycle_safe(self):
        from projectos.looker.analytics import LookerAnalyticsService
        service=LookerAnalyticsService(self.db); service.build(self.project.project_id,"run-1")
        self.assertEqual(("explore:orders","view:orders"),service.dependencies(self.project.project_id,"explore:orders"))
        self.assertEqual(("dashboard:sales","explore:orders","explore:removed","view:orders"),service.impact(self.project.project_id,"view:orders"))
        self.assertEqual(("explore:removed",),service.impact(self.project.project_id,"explore:removed"))

    def test_recalculation_retains_prior_version_with_deterministic_payload(self):
        from projectos.looker.analytics import LookerAnalyticsService
        service=LookerAnalyticsService(self.db); one=service.build(self.project.project_id,"run-1"); two=service.build(self.project.project_id,"run-1")
        self.assertEqual((1,2),(one.version,two.version)); self.assertEqual(service.summary(self.project.project_id,1),service.summary(self.project.project_id,2))
        self.assertEqual(4,self.db.connection.execute("SELECT COUNT(*) FROM looker_analytics WHERE project_id=?",(str(self.project.project_id),)).fetchone()[0])

if __name__=="__main__": unittest.main()
