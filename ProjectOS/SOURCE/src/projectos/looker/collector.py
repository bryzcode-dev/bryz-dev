from __future__ import annotations
import hashlib, json, os, tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import UUID
from projectos.acceptance.authority import HostSession
from projectos.errors import ValidationError
from .evidence import LookerEvidenceBuilder
from .inspectors import inspect_automation, inspect_git, inspect_legacy, run_validations
from .lookml import parse_repository
from .model import LookerIntake
from .policy import validate_collector_environment

STAGES=("VALIDATED","INVENTORIED","INSPECTED","SCANNED","SEALED")
def _canonical(value): return (json.dumps(value,sort_keys=True,separators=(",",":"))+"\n").encode()
def _sha(content): return hashlib.sha256(content).hexdigest()
def _write(path,content):
    path.parent.mkdir(parents=True,exist_ok=True); temporary=None
    try:
        with tempfile.NamedTemporaryFile(prefix=f".{path.name}.",suffix=".tmp",dir=path.parent,delete=False) as item: temporary=Path(item.name); item.write(content); item.flush(); os.fsync(item.fileno())
        os.replace(temporary,path); temporary=None
    finally:
        if temporary: temporary.unlink(missing_ok=True)
def _fingerprint(root):
    entries=[]
    for path in sorted(root.rglob("*")):
        if path.is_symlink(): raise ValidationError("repository cannot contain a symlink")
        if path.is_file(): entries.append((path.relative_to(root).as_posix(),_sha(path.read_bytes())))
    return _sha(_canonical(entries))
def _value(item): return asdict(item)

@dataclass(frozen=True)
class CollectionResult:
    run_id:str; state:str; sha256:str; output_path:Path

class LookerCollector:
    def collect(self,intake:LookerIntake,session:HostSession,executor,output_path:Path,wheel_sha256:str,*,stage_hook=lambda stage:None):
        paths=validate_collector_environment(intake,session); output=Path(output_path)
        if output.exists() or output.is_symlink() or output.parent.resolve()!=paths.output_root: raise ValidationError("collection output must be new below the declared output root")
        journal_path=paths.output_root/"collection-journal.json"; before=_fingerprint(paths.repository_root); run_id=str(UUID(hashlib.sha256(intake.canonical_bytes()+before.encode()+wheel_sha256.encode()).hexdigest()[:32])); completed=[]
        def stage(name):
            completed.append(name); _write(journal_path,_canonical({"completed_stages":completed,"format":"projectos-looker-collection-journal-v1","intake_sha256":_sha(intake.canonical_bytes()),"run_id":run_id,"state":name})); stage_hook(name)
        stage("VALIDATED"); parsed=parse_repository(paths.repository_root); stage("INVENTORIED")
        git=inspect_git(intake,paths.repository_root,executor); legacy=inspect_legacy(intake); automation=inspect_automation(intake); validations=run_validations(intake,executor); stage("INSPECTED")
        if _fingerprint(paths.repository_root)!=before: raise ValidationError("repository changed during collection")
        sections={"repository":{"format":"repository-v1","git":_value(git)},"looker-assets":{"format":"looker-assets-v1","items":[_value(item) for item in parsed.assets]},"looker-relationships":{"format":"looker-relationships-v1","items":[_value(item) for item in parsed.relationships]},"legacy-tracker":{"format":"legacy-tracker-v1","value":_value(legacy)},"automation":{"format":"automation-v1","items":[_value(item) for item in automation.items]},"validation":{"format":"validation-v1","items":[_value(item) for item in validations]},"credential-references":{"format":"credential-references-v1","items":[item.to_mapping() for item in intake.credential_references]},"findings":{"format":"findings-v1","items":[_value(item) for item in parsed.findings]}}
        stage("SCANNED"); built=LookerEvidenceBuilder().build(intake.source_machine_id,intake.host_family.value,run_id,before,_sha(intake.canonical_bytes()),wheel_sha256,sections,output); stage("SEALED")
        return CollectionResult(run_id,"SEALED",built.sha256,output)
    def recover(self,intake,session):
        paths=validate_collector_environment(intake,session)
        for path in paths.output_root.glob(".*.tmp"):
            if path.is_file() and not path.is_symlink(): path.unlink()
