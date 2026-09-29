from __future__ import annotations
import hashlib,json
from collections import Counter,defaultdict,deque
from dataclasses import dataclass
from uuid import UUID
from projectos.database import ProjectOSDatabase,utc_now
from projectos.errors import ValidationError
from projectos.validation import canonical_json
from .repository import LookerRepository

def _id(*parts): return str(UUID(hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:32]))
@dataclass(frozen=True)
class AnalyticVersion: project_id:str; intake_run_id:str; version:int; summary_id:str; graph_id:str

class LookerAnalyticsService:
    def __init__(self,database:ProjectOSDatabase): self.database=database; self.repository=LookerRepository(database)
    def _facts(self,project_id,run_id):
        intake=self.repository.intake(project_id,run_id)
        if not intake: raise ValidationError("Looker intake run does not exist")
        assets=self.repository.assets(project_id,run_id); edges=self.repository.relationships(project_id,run_id); findings=self.repository.findings(project_id,run_id); validations=self.repository.validations(run_id)
        nodes={f"{row['asset_type']}:{row['name']}" for row in assets}; graph=defaultdict(set); reverse=defaultdict(set); incident=set()
        for row in edges:
            source=f"{row['source_type']}:{row['source_name']}"; target=f"{row['target_type']}:{row['target_name']}"; graph[source].add(target); reverse[target].add(source); incident.update((source,target))
        counts=Counter(row["asset_type"] for row in assets)
        counts["file"]=len({row["file_path"] for row in assets})
        counts["connection_reference"]=len({row["target_name"] for row in edges if row["relationship_type"]=="model_connection"})
        codes=Counter(row["code"] for row in findings); relation_counts=Counter(row["relationship_type"] for row in edges)
        credentials=json.loads(intake["credential_refs_json"]).get("items",[]); legacy=json.loads(intake["legacy_json"]); legacy_value=legacy.get("value",{})
        mapping_rows=self.database.connection.execute("SELECT status,COUNT(*) AS count FROM looker_legacy_mappings WHERE project_id=? AND intake_run_id=? GROUP BY status ORDER BY status",(str(project_id),run_id)).fetchall()
        mapping_counts={row["status"]:row["count"] for row in mapping_rows}; validation_passed=sum(bool(row["passed"]) for row in validations); validation_failed=len(validations)-validation_passed
        summary={"asset_counts":dict(sorted(counts.items())),"code_status":"PASS" if validation_failed==0 else "FAIL","credential_usage":{"by_provider":dict(sorted(Counter(item["provider"] for item in credentials).items())),"by_storage_system":dict(sorted(Counter(item["storage_system"] for item in credentials).items())),"reference_count":len(credentials)},"dependency_counts":dict(sorted(relation_counts.items())),"duplicate_count":codes["DUPLICATE_ASSET"],"finding_counts":dict(sorted(codes.items())),"git":{"ahead":intake["git_ahead"],"behind":intake["git_behind"],"branch":intake["git_branch"],"dirty":bool(intake["git_dirty"]),"head":intake["git_head"]},"import":{"archive_sha256":intake["archive_sha256"],"host_family":intake["host_family"],"intake_run_id":run_id,"source_machine_id":intake["source_machine_id"]},"legacy":{"declared_deployment_count":len(legacy_value.get("deployment_ids",[])),"declared_sheet_tab_count":len(legacy_value.get("sheet_tabs",[])),"mapping_counts":mapping_counts,"mapping_total":sum(mapping_counts.values())},"migration_version":self.database.schema_version(),"orphans":{kind:sorted(node for node in nodes-incident if node.startswith(f"{kind}:")) for kind in sorted({row["asset_type"] for row in assets})},"parser_versions":sorted({row["parser_version"] for row in assets}),"refresh_status":"UNAVAILABLE","unresolved_count":sum(code.startswith("UNRESOLVED") for code in codes.elements()),"validation":{"failed":validation_failed,"passed":validation_passed}}
        graph_value={"forward":{key:sorted(value) for key,value in sorted(graph.items())},"nodes":sorted(nodes|incident),"reverse":{key:sorted(value) for key,value in sorted(reverse.items())}}
        return summary,graph_value
    def build(self,project_id,run_id):
        summary,graph=self._facts(project_id,run_id)
        rows=self.database.connection.execute("SELECT value_json FROM looker_analytics WHERE project_id=? AND analytic_type='LOOKER_SUMMARY'",(str(project_id),)).fetchall(); version=max((int(json.loads(row[0])["version"]) for row in rows),default=0)+1
        summary_value={"data":summary,"version":version}; graph_value={"data":graph,"version":version}; summary_id=_id(project_id,run_id,"summary",version); graph_id=_id(project_id,run_id,"graph",version); now=utc_now()
        with self.database.transaction() as connection:
            connection.execute("INSERT INTO looker_analytics VALUES(?,?,?,?,?,?)",(summary_id,str(project_id),"LOOKER_SUMMARY",canonical_json(summary_value),run_id,now))
            connection.execute("INSERT INTO looker_analytics VALUES(?,?,?,?,?,?)",(graph_id,str(project_id),"LOOKER_GRAPH",canonical_json(graph_value),run_id,now))
        return AnalyticVersion(str(project_id),run_id,version,summary_id,graph_id)
    def _analytic(self,project_id,kind,version=None):
        rows=self.database.connection.execute("SELECT value_json FROM looker_analytics WHERE project_id=? AND analytic_type=? ORDER BY created_at,analytic_id",(str(project_id),kind)).fetchall()
        values=[json.loads(row[0]) for row in rows]
        if not values: raise ValidationError("Looker analytics are unavailable")
        if version is None: return values[-1]["data"]
        for value in values:
            if value["version"]==version: return value["data"]
        raise ValidationError("Looker analytic version is unavailable")
    def summary(self,project_id,version=None): return self._analytic(project_id,"LOOKER_SUMMARY",version)
    @staticmethod
    def _walk(mapping,start):
        seen={start}; queue=deque([start])
        while queue:
            node=queue.popleft()
            for target in mapping.get(node,[]):
                if target not in seen: seen.add(target); queue.append(target)
        return tuple(sorted(seen))
    def dependencies(self,project_id,node): return self._walk(self._analytic(project_id,"LOOKER_GRAPH")["forward"],node)
    def impact(self,project_id,node): return self._walk(self._analytic(project_id,"LOOKER_GRAPH")["reverse"],node)
