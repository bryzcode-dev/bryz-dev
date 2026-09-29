from __future__ import annotations
import hashlib, json, os, re, stat, tempfile, zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping
from projectos.errors import ValidationError
from projectos.validation import reject_secret_material

SECTION_MEMBERS=("repository.json","looker-assets.json","looker-relationships.json","legacy-tracker.json","automation.json","validation.json","credential-references.json","findings.json")
EVIDENCE_MEMBERS=("intake-manifest.json",*SECTION_MEMBERS,"SHA256SUMS.txt")
_EMAIL=re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",re.I)
_PATH=re.compile(r"(?:^|[\s\"'])/(?:Users|home|Volumes|private|var|tmp)/|\b[A-Za-z]:\\")
_IDENTIFIER=re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_HEX64=re.compile(r"[0-9a-f]{64}")
_MANIFEST_FIELDS={"completed","evidence_schema_version","format","host_family","intake_sha256","members","repository_sha256","run_id","source_machine_id","wheel_sha256"}

def _canonical(value): return (json.dumps(value,sort_keys=True,separators=(",",":"))+"\n").encode()
def _sha(content): return hashlib.sha256(content).hexdigest()
def _inspect(name,content):
    try: text=content.decode()
    except UnicodeDecodeError as exc: raise ValidationError(f"evidence member {name} must be UTF-8") from exc
    try: parsed=json.loads(text) if name.endswith(".json") else None
    except json.JSONDecodeError as exc: raise ValidationError(f"evidence member {name} is invalid JSON") from exc
    if parsed is not None:
        reject_secret_material(parsed)
        if content!=_canonical(parsed): raise ValidationError(f"evidence member {name} is not canonical")
    if _EMAIL.search(text) or _PATH.search(text) or any(term in text.casefold() for term in ("native_stdout","native_stderr","authorization: bearer")):
        raise ValidationError(f"evidence member {name} contains private data")
def _info(name):
    info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0)); info.compress_type=zipfile.ZIP_DEFLATED; info.external_attr=(stat.S_IFREG|0o644)<<16; return info

def _validate_manifest(value):
    if not isinstance(value,dict) or set(value)!=_MANIFEST_FIELDS:
        raise ValidationError("evidence manifest fields are invalid")
    if value["completed"] is not True or type(value["evidence_schema_version"]) is not int or value["evidence_schema_version"]!=1 or value["format"]!="projectos-looker-intake-v1" or value["host_family"] not in {"macos","windows"}:
        raise ValidationError("evidence manifest contract is invalid")
    if any(not isinstance(value[field],str) or _HEX64.fullmatch(value[field]) is None for field in ("intake_sha256","repository_sha256","wheel_sha256")):
        raise ValidationError("evidence manifest hash is invalid")
    if any(not isinstance(value[field],str) or _IDENTIFIER.fullmatch(value[field]) is None for field in ("run_id","source_machine_id")):
        raise ValidationError("evidence manifest identifier is invalid")
    members=value["members"]
    if not isinstance(members,list) or any(not isinstance(item,dict) or set(item)!={"path","sha256","size"} or not isinstance(item["path"],str) or not isinstance(item["sha256"],str) or _HEX64.fullmatch(item["sha256"]) is None or type(item["size"]) is not int or item["size"]<0 for item in members):
        raise ValidationError("evidence manifest member inventory is invalid")
    if len(members)!=len({item["path"] for item in members}):
        raise ValidationError("evidence manifest member inventory is duplicated")

@dataclass(frozen=True)
class VerifiedLookerEvidence:
    path: Path; sha256: str; size: int; members: tuple[str,...]; manifest: Mapping[str,Any]

class LookerEvidenceBuilder:
    def build(self,source_machine_id,host_family,run_id,repository_sha256,intake_sha256,wheel_sha256,sections,output_path):
        if set(sections)!={name[:-5] for name in SECTION_MEMBERS}: raise ValidationError("evidence section inventory is invalid")
        entries={f"{name}.json":_canonical(sections[name]) for name in sections}
        for name,content in entries.items(): _inspect(name,content)
        inventory=[{"path":name,"sha256":_sha(content),"size":len(content)} for name,content in sorted(entries.items())]
        manifest={"completed":True,"evidence_schema_version":1,"format":"projectos-looker-intake-v1","host_family":host_family,"intake_sha256":intake_sha256,"members":inventory,"repository_sha256":repository_sha256,"run_id":run_id,"source_machine_id":source_machine_id,"wheel_sha256":wheel_sha256}
        entries["intake-manifest.json"]=_canonical(manifest)
        entries["SHA256SUMS.txt"]="".join(f"{_sha(content)}  {name}\n" for name,content in sorted(entries.items())).encode()
        output=Path(output_path); output.parent.mkdir(parents=True,exist_ok=True)
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(prefix=f".{output.name}.",suffix=".tmp",dir=output.parent,delete=False) as item: temporary=Path(item.name)
            with zipfile.ZipFile(temporary,"w") as archive:
                for name,content in sorted(entries.items()): archive.writestr(_info(name),content)
            verify_intake_archive(temporary); os.replace(temporary,output); temporary=None
        finally:
            if temporary: temporary.unlink(missing_ok=True)
        return verify_intake_archive(output)

def verify_intake_archive(path):
    selected=Path(path)
    try:
        with zipfile.ZipFile(selected) as archive:
            infos=archive.infolist(); names=[item.filename for item in infos]
            if set(names)!=set(EVIDENCE_MEMBERS) or len(names)!=len(EVIDENCE_MEMBERS) or len({name.casefold() for name in names})!=len(names): raise ValidationError("evidence archive inventory is invalid")
            for item in infos:
                posix=PurePosixPath(item.filename); windows=PureWindowsPath(item.filename)
                if posix.is_absolute() or windows.is_absolute() or windows.drive or ".." in posix.parts or not stat.S_ISREG(item.external_attr>>16): raise ValidationError("evidence archive path or type is invalid")
            content={name:archive.read(name) for name in names}
            if archive.testzip() is not None: raise ValidationError("evidence archive is corrupt")
            for name in (*SECTION_MEMBERS,"intake-manifest.json"): _inspect(name,content[name])
            manifest=json.loads(content["intake-manifest.json"])
            _validate_manifest(manifest)
            expected={item["path"]:(item["sha256"],item["size"]) for item in manifest.get("members",[])}
            if set(expected)!=set(SECTION_MEMBERS) or any(expected[name]!=(_sha(content[name]),len(content[name])) for name in SECTION_MEMBERS): raise ValidationError("evidence member hashes are invalid")
            sums="".join(f"{_sha(content[name])}  {name}\n" for name in sorted(set(EVIDENCE_MEMBERS)-{"SHA256SUMS.txt"})).encode()
            if content["SHA256SUMS.txt"]!=sums: raise ValidationError("evidence checksum inventory is invalid")
    except (OSError,zipfile.BadZipFile,KeyError,TypeError,ValueError) as exc:
        if isinstance(exc,ValidationError): raise
        raise ValidationError("Looker evidence is unavailable or invalid") from exc
    raw=selected.read_bytes(); return VerifiedLookerEvidence(selected,_sha(raw),len(raw),tuple(sorted(names)),manifest)
