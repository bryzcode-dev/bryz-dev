from __future__ import annotations
import hashlib, sys, tempfile, unittest
from pathlib import Path
from uuid import UUID
from tests.helpers import REPO_ROOT
if str(REPO_ROOT/"src") not in sys.path: sys.path.insert(0,str(REPO_ROOT/"src"))
from projectos.database import ProjectOSDatabase
from projectos.errors import ValidationError
from projectos.looker.evidence import LookerEvidenceBuilder, verify_intake_archive
from projectos.repositories import ProjectRepository
from projectos.types import ProjectCreate,ProjectType,ProjectVisibility


class LookerImporterTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup); self.root=Path(self.temporary.name)
        self.db=ProjectOSDatabase(self.root/"db.sqlite").initialize(); self.addCleanup(self.db.close)
        self.project=ProjectRepository(self.db).create(ProjectCreate("looker","Looker",ProjectType.LOOKER,ProjectVisibility.PUBLIC),"owner@example.com")
    def evidence(self,run="run-1",asset="orders",mappings=()):
        sections={name:{"format":name,"items":[]} for name in ("repository","looker-assets","looker-relationships","legacy-tracker","automation","validation","credential-references","findings")}
        sections["repository"]={"format":"repository-v1","git":{"head":"a"*40,"branch":"main","dirty":False,"behind":0,"ahead":0,"remote":"origin","primary_branch":"main"}}
        sections["looker-assets"]["items"]=[{"asset_type":"view","name":asset,"source_path":"views/orders.view.lkml","content_sha256":"b"*64,"parser_version":"1.0.0","line":1}]
        sections["legacy-tracker"]={"format":"legacy-tracker-v1","value":{},"mappings":list(mappings)}
        path=self.root/f"{run}-{asset}.zip"; LookerEvidenceBuilder().build("source-machine-01","macos",run,"1"*64,"2"*64,"3"*64,sections,path); return verify_intake_archive(path)
    def test_preview_is_read_only_and_import_is_atomic_provenance_bound_and_idempotent(self):
        from projectos.looker.importer import LookerImporter
        service=LookerImporter(self.db); evidence=self.evidence()
        preview=service.preview(self.project.project_id,evidence)
        self.assertEqual(1,preview.asset_count); self.assertEqual(0,self.db.connection.execute("SELECT COUNT(*) FROM looker_intake_runs").fetchone()[0])
        first=service.import_archive(self.project.project_id,evidence,"owner@example.com"); second=service.import_archive(self.project.project_id,evidence,"owner@example.com")
        self.assertEqual(first,second); self.assertFalse(first.existing); self.assertEqual(1,self.db.connection.execute("SELECT COUNT(*) FROM looker_assets WHERE project_id=?",(str(self.project.project_id),)).fetchone()[0])
        self.assertEqual(1,self.db.connection.execute("SELECT COUNT(*) FROM looker_asset_occurrences WHERE intake_run_id='run-1'").fetchone()[0])
        row=self.db.connection.execute("SELECT archive_sha256,source_run_id FROM looker_intake_runs").fetchone(); self.assertEqual((evidence.sha256,"run-1"),tuple(row))
    def test_reused_source_run_with_different_bytes_and_missing_project_fail_without_partial_rows(self):
        from projectos.looker.importer import LookerImporter
        service=LookerImporter(self.db); service.import_archive(self.project.project_id,self.evidence(),"owner@example.com")
        with self.assertRaisesRegex(ValidationError,"source run"):
            service.import_archive(self.project.project_id,self.evidence(asset="customers"),"owner@example.com")
        with self.assertRaisesRegex(ValidationError,"project"):
            service.import_archive(UUID("00000000-0000-0000-0000-000000000099"),self.evidence(run="run-2"),"owner@example.com")
        self.assertEqual(1,self.db.connection.execute("SELECT COUNT(*) FROM looker_intake_runs").fetchone()[0])

    def test_successive_intakes_reuse_canonical_asset_and_retain_run_occurrences(self):
        from projectos.looker.importer import LookerImporter
        service=LookerImporter(self.db); service.import_archive(self.project.project_id,self.evidence(),"owner@example.com"); service.import_archive(self.project.project_id,self.evidence(run="run-2"),"owner@example.com")
        self.assertEqual(1,self.db.connection.execute("SELECT COUNT(*) FROM looker_assets").fetchone()[0]); self.assertEqual(2,self.db.connection.execute("SELECT COUNT(*) FROM looker_asset_occurrences").fetchone()[0])

    def test_import_persists_explicit_legacy_mappings(self):
        from projectos.looker.importer import LookerImporter
        mapping={"legacy_key":"tracker:orders","entity_type":"view","entity_id":"orders","status":"MATCHED","provenance":{"source":"legacy-tracker"}}
        LookerImporter(self.db).import_archive(self.project.project_id,self.evidence(mappings=(mapping,)),"owner@example.com")
        row=self.db.connection.execute("SELECT legacy_key,entity_type,entity_id,status,provenance_json FROM looker_legacy_mappings").fetchone()
        asset_id=self.db.connection.execute("SELECT looker_asset_id FROM looker_asset_occurrences WHERE intake_run_id='run-1'").fetchone()[0]
        self.assertEqual(("tracker:orders","view",asset_id,"MATCHED",'{"source":"legacy-tracker"}'),tuple(row))

    def test_import_rejects_matched_mapping_without_unique_canonical_asset(self):
        from projectos.looker.importer import LookerImporter
        mapping={"legacy_key":"tracker:missing","entity_type":"view","entity_id":"missing","status":"MATCHED","provenance":{}}
        with self.assertRaisesRegex(ValidationError,"canonical asset"):
            LookerImporter(self.db).import_archive(self.project.project_id,self.evidence(mappings=(mapping,)),"owner@example.com")
        self.assertEqual(0,self.db.connection.execute("SELECT COUNT(*) FROM looker_intake_runs").fetchone()[0])

if __name__=="__main__": unittest.main()
