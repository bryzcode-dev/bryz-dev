from __future__ import annotations
import sqlite3, sys, tempfile, unittest
from importlib.resources import files
from pathlib import Path
from tests.helpers import REPO_ROOT
if str(REPO_ROOT/"src") not in sys.path: sys.path.insert(0,str(REPO_ROOT/"src"))
from projectos.database import ProjectOSDatabase, SCHEMA_VERSION


TABLES={"looker_intake_runs","looker_source_members","looker_asset_occurrences","looker_relationships","looker_findings","looker_validation_results","looker_legacy_mappings","looker_reconciliation_runs","looker_reconciliation_items","looker_cutover_packages"}

class Phase4DatabaseTests(unittest.TestCase):
    def test_fresh_database_reaches_schema_three_with_exact_phase4_tables_and_indexes(self):
        with tempfile.TemporaryDirectory() as temporary:
            db=ProjectOSDatabase(Path(temporary)/"db.sqlite").initialize()
            self.assertEqual(3,SCHEMA_VERSION); self.assertEqual(3,db.schema_version())
            names={row[0] for row in db.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue(TABLES<=names)
            indexes={row[0] for row in db.connection.execute("SELECT name FROM sqlite_master WHERE type='index'")}
            self.assertIn("idx_looker_relationships_source",indexes); self.assertIn("idx_looker_findings_status",indexes); self.assertIn("idx_looker_asset_occurrences_run",indexes)
            db.close()

    def test_schema_two_database_upgrades_without_losing_existing_looker_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/"db.sqlite"; connection=sqlite3.connect(path)
            one=files("projectos").joinpath("migrations/0001.sql").read_text(); two=files("projectos").joinpath("migrations/0002.sql").read_text()
            connection.executescript(one); connection.execute("INSERT INTO schema_migrations VALUES(1,'0001.sql','t')"); connection.executescript(two); connection.execute("INSERT INTO schema_migrations VALUES(2,'0002.sql','t')")
            connection.execute("INSERT INTO projects(project_id,slug,name,project_type,status,visibility,created_at,updated_at) VALUES('p','p','P','LOOKER','ACTIVE','PUBLIC','t','t')")
            connection.execute("INSERT INTO looker_assets(looker_asset_id,project_id,asset_type,file_path,name,created_at,updated_at) VALUES('a','p','view','v','v','t','t')"); connection.commit(); connection.close()
            db=ProjectOSDatabase(path).initialize()
            self.assertEqual(1,db.connection.execute("SELECT COUNT(*) FROM looker_assets").fetchone()[0]); self.assertEqual(3,db.schema_version()); db.close()

    def test_migration_three_failure_rolls_back_schema_and_version(self):
        from projectos.database import Migration, PackagedMigrationSource
        class Source:
            def list(self):
                base=PackagedMigrationSource().list()[:2]
                return (*base,Migration(3,"broken.sql","CREATE TABLE partial(id); INVALID SQL;"))
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/"db.sqlite"
            with self.assertRaises(Exception): ProjectOSDatabase(path,Source()).initialize()
            connection=sqlite3.connect(path)
            self.assertNotIn("partial",{row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}); connection.close()

if __name__=="__main__": unittest.main()
