from __future__ import annotations
from projectos.database import ProjectOSDatabase

class LookerRepository:
    def __init__(self,database:ProjectOSDatabase): self.database=database
    def intake_by_archive(self,sha256): return self.database.connection.execute("SELECT * FROM looker_intake_runs WHERE archive_sha256=?",(sha256,)).fetchone()
    def intake_by_source_run(self,run_id): return self.database.connection.execute("SELECT * FROM looker_intake_runs WHERE source_run_id=?",(run_id,)).fetchone()
    def project_exists(self,project_id): return self.database.connection.execute("SELECT 1 FROM projects WHERE project_id=?",(str(project_id),)).fetchone() is not None
    def intake(self,project_id,run_id): return self.database.connection.execute("SELECT * FROM looker_intake_runs WHERE project_id=? AND intake_run_id=?",(str(project_id),run_id)).fetchone()
    def assets(self,project_id,run_id): return self.database.connection.execute("SELECT a.*,o.content_sha256,o.parser_version,o.source_line FROM looker_assets a JOIN looker_asset_occurrences o ON o.looker_asset_id=a.looker_asset_id WHERE a.project_id=? AND o.intake_run_id=? ORDER BY a.asset_type,a.name,a.file_path",(str(project_id),run_id)).fetchall()
    def relationships(self,project_id,run_id): return self.database.connection.execute("SELECT * FROM looker_relationships WHERE project_id=? AND intake_run_id=? ORDER BY relationship_type,source_name,target_name",(str(project_id),run_id)).fetchall()
    def findings(self,project_id,run_id): return self.database.connection.execute("SELECT * FROM looker_findings WHERE project_id=? AND intake_run_id=? ORDER BY code,subject",(str(project_id),run_id)).fetchall()
    def validations(self,run_id): return self.database.connection.execute("SELECT * FROM looker_validation_results WHERE intake_run_id=? ORDER BY command_id",(run_id,)).fetchall()
    def reconciliation(self,reconciliation_id): return self.database.connection.execute("SELECT * FROM looker_reconciliation_runs WHERE reconciliation_id=?",(reconciliation_id,)).fetchone()
    def reconciliation_items(self,reconciliation_id): return self.database.connection.execute("SELECT * FROM looker_reconciliation_items WHERE reconciliation_id=? ORDER BY dimension,item_key",(reconciliation_id,)).fetchall()
