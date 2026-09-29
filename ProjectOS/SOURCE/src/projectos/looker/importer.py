from __future__ import annotations
import hashlib,json,zipfile
from dataclasses import dataclass
from uuid import UUID
from projectos.audit import AuditLog
from projectos.database import ProjectOSDatabase,utc_now
from projectos.errors import ValidationError
from projectos.validation import canonical_json,require_text
from .evidence import VerifiedLookerEvidence,verify_intake_archive
from .repository import LookerRepository

def _id(*parts): return str(UUID(hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:32]))
def _sections(evidence):
    verified=verify_intake_archive(evidence.path)
    with zipfile.ZipFile(verified.path) as archive:
        return verified,{name:json.loads(archive.read(f"{name}.json")) for name in ("repository","looker-assets","looker-relationships","legacy-tracker","automation","validation","credential-references","findings")}
@dataclass(frozen=True)
class LookerImportPreview: project_id:str; source_run_id:str; asset_count:int; relationship_count:int; finding_count:int
@dataclass(frozen=True)
class LookerImportResult: intake_run_id:str; archive_sha256:str; asset_count:int; relationship_count:int; existing:bool=False

class LookerImporter:
    def __init__(self,database:ProjectOSDatabase): self.database=database; self.repository=LookerRepository(database)
    def preview(self,project_id,evidence):
        if not self.repository.project_exists(project_id): raise ValidationError("Looker import project does not exist")
        verified,sections=_sections(evidence); run=str(verified.manifest["run_id"])
        return LookerImportPreview(str(project_id),run,len(sections["looker-assets"]["items"]),len(sections["looker-relationships"]["items"]),len(sections["findings"]["items"]))
    def import_archive(self,project_id,evidence,actor):
        actor=require_text(actor,"actor")
        preview=self.preview(project_id,evidence); verified,sections=_sections(evidence)
        existing=self.repository.intake_by_archive(verified.sha256)
        if existing: return LookerImportResult(existing["intake_run_id"],verified.sha256,preview.asset_count,preview.relationship_count)
        conflict=self.repository.intake_by_source_run(preview.source_run_id)
        if conflict: raise ValidationError("Looker source run is already bound to different evidence")
        intake_id=preview.source_run_id; now=utc_now(); git=sections["repository"].get("git",{})
        try:
            with self.database.transaction() as connection:
                connection.execute("INSERT INTO looker_intake_runs(intake_run_id,project_id,archive_sha256,source_run_id,source_machine_id,host_family,repository_sha256,git_head,git_branch,git_dirty,git_behind,git_ahead,legacy_json,credential_refs_json,status,imported_by,imported_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(intake_id,str(project_id),verified.sha256,preview.source_run_id,verified.manifest["source_machine_id"],verified.manifest["host_family"],verified.manifest["repository_sha256"],git.get("head",""),git.get("branch",""),int(bool(git.get("dirty",False))),int(git.get("behind",0)),int(git.get("ahead",0)),canonical_json(sections["legacy-tracker"]),canonical_json(sections["credential-references"]),"IMPORTED",actor,now))
                for member in verified.manifest["members"]: connection.execute("INSERT INTO looker_source_members VALUES(?,?,?,?)",(intake_id,member["path"],member["sha256"],member["size"]))
                for item in sections["looker-assets"]["items"]:
                    asset_id=_id(project_id,item["asset_type"],item["source_path"],item["name"]); provenance=canonical_json({"intake_run_id":intake_id,"content_sha256":item["content_sha256"],"parser_version":item["parser_version"],"line":item["line"]})
                    connection.execute("INSERT INTO looker_assets(looker_asset_id,project_id,asset_type,file_path,name,metadata_json,provenance_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(project_id,asset_type,file_path,name) DO UPDATE SET provenance_json=excluded.provenance_json,updated_at=excluded.updated_at",(asset_id,str(project_id),item["asset_type"],item["source_path"],item["name"],"{}",provenance,now,now))
                    connection.execute("INSERT INTO looker_asset_occurrences VALUES(?,?,?,?,?) ON CONFLICT(intake_run_id,looker_asset_id) DO UPDATE SET content_sha256=excluded.content_sha256,parser_version=excluded.parser_version,source_line=excluded.source_line",(intake_id,asset_id,item["content_sha256"],item["parser_version"],item["line"]))
                for item in sections["looker-relationships"]["items"]:
                    connection.execute("INSERT INTO looker_relationships VALUES(?,?,?,?,?,?,?,?,?,?,?)",(_id(intake_id,"edge",*item.values()),intake_id,str(project_id),item["relationship_type"],item["source_type"],item["source_name"],item["target_type"],item["target_name"],item["source_path"],item["line"],canonical_json({"intake_run_id":intake_id})))
                for item in sections["legacy-tracker"].get("mappings", []):
                    expected={"legacy_key","entity_type","entity_id","status","provenance"}
                    if not isinstance(item,dict) or set(item)!=expected or item["status"] not in {"MATCHED","UNMATCHED","AMBIGUOUS"} or not isinstance(item["provenance"],dict):
                        raise ValidationError("legacy mapping evidence is invalid")
                    legacy_key=require_text(item["legacy_key"],"legacy_key"); entity_type=require_text(item["entity_type"],"entity_type")
                    entity_id=item["entity_id"]
                    if entity_id is not None: entity_id=require_text(entity_id,"entity_id")
                    if item["status"]=="MATCHED" and entity_id is None: raise ValidationError("matched legacy mapping requires an entity")
                    if item["status"]=="MATCHED":
                        candidates=connection.execute("SELECT a.looker_asset_id FROM looker_assets a JOIN looker_asset_occurrences o ON o.looker_asset_id=a.looker_asset_id WHERE o.intake_run_id=? AND a.project_id=? AND a.asset_type=? AND a.name=?",(intake_id,str(project_id),entity_type,entity_id)).fetchall()
                        if len(candidates)!=1: raise ValidationError("matched legacy mapping requires one canonical asset")
                        entity_id=candidates[0]["looker_asset_id"]
                    connection.execute("INSERT INTO looker_legacy_mappings VALUES(?,?,?,?,?,?,?,?)",(_id(intake_id,"mapping",legacy_key),intake_id,str(project_id),legacy_key,entity_type,entity_id,item["status"],canonical_json(item["provenance"])))
                for item in sections["findings"]["items"]:
                    connection.execute("INSERT INTO looker_findings VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(_id(intake_id,"finding",item["code"],item["subject"],item["source_path"],item["line"]),intake_id,str(project_id),"WARNING","PARSER",item["code"],item["subject"],"OPEN",item["source_path"],item["line"],canonical_json({"intake_run_id":intake_id}),now))
                for item in sections["validation"]["items"]:
                    connection.execute("INSERT INTO looker_validation_results VALUES(?,?,?,?,?,?,?,?)",(_id(intake_id,"validation",item["command_id"]),intake_id,item["command_id"],int(item["passed"]),item["returncode"],int(item["timed_out"]),item["parser"],item["summary"]))
                AuditLog().append(connection,"looker.intake.imported",actor,"looker_intake",intake_id,{"archive_sha256":verified.sha256,"project_id":str(project_id)})
        except KeyError as exc: raise ValidationError("Looker evidence section is invalid") from exc
        return LookerImportResult(intake_id,verified.sha256,preview.asset_count,preview.relationship_count)
